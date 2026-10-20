"""Button-operated voice conversation without a browser session.

Only completed, explicitly submitted recordings are sent to STT. Network work
runs separately from the ownership heartbeat; stop/disconnect suppresses replies.
"""

import base64
import contextlib
import io
import json
import os
import queue
import re
import struct
import threading
import time
import urllib.parse
import urllib.request
import uuid
import wave

MIC_RATE = 16_000
MIC_MAX_BYTES = MIC_RATE * 2 * 30
MIC_READ_BYTES = 1024
MIC_READ_MAX_BYTES = 16384
MIC_BASE64_MAX_BYTES = 32768
POLL_SECONDS = 0.5
SERVICE_TIMEOUT_SECONDS = 120
MAX_SERVICE_BYTES = 4_000_000
TTS_CHUNK_CHARS = 80


def wav_from_pcm(pcm):
    if not pcm or len(pcm) > MIC_MAX_BYTES or len(pcm) % 2:
        raise ValueError("invalid microphone PCM")
    data = io.BytesIO()
    with wave.open(data, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(MIC_RATE)
        wav.writeframes(pcm)
    return data.getvalue()


class Services:
    def __init__(self, config, host_url):
        self.host_url = host_url.rstrip("/")
        self.voice_url = config.get("voice_url", "http://127.0.0.1:4174").rstrip("/")
        for url in (self.host_url, self.voice_url):
            parsed = urllib.parse.urlparse(url)
            if parsed.scheme not in ("http", "https") or not parsed.hostname:
                raise ValueError("invalid conversation service URL")
        self.agent_id = config.get("agent_id")
        self.provider = config.get("provider", "voicevox")
        if self.provider not in ("voicevox", "piper"):
            raise ValueError("provider must be voicevox or piper")
        self.language = config.get("language", "ja-JP")
        self.speaker = config.get("speaker", 1)
        self.image_config = config
        self.session_id = None

    def face_images(self):
        from .faces import load_faces

        return load_faces(self, self.image_config)

    def request(self, url, body, content_type="application/json"):
        headers = {"Content-Type": content_type}
        token = os.environ.get("XANGI_TOKEN", "")
        if token and url.startswith(self.host_url + "/"):
            headers["Authorization"] = f"Bearer {token}"
        return urllib.request.urlopen(
            urllib.request.Request(url, data=body, headers=headers),
            timeout=SERVICE_TIMEOUT_SECONDS,
        )

    def json(self, path, payload):
        with self.request(
            self.host_url + path, json.dumps(payload).encode()
        ) as response:
            return json.loads(response.read(MAX_SERVICE_BYTES))

    def transcribe(self, wav):
        with self.request(
            self.voice_url
            + "/stt?"
            + urllib.parse.urlencode({"language": self.language}),
            wav,
            "audio/wav",
        ) as response:
            result = json.loads(response.read(MAX_SERVICE_BYTES))
        return str(result.get("text", "")).strip()

    def reply_chunks(self, text):
        if not self.session_id:
            payload = (
                {"agentId": self.agent_id}
                if self.agent_id
                else {"workspaceId": "default"}
            )
            self.session_id = self.json("/api/sessions", payload)["sessionId"]
        body = json.dumps({"appSessionId": self.session_id, "message": text}).encode()
        event = ""
        emitted = ""
        with self.request(self.host_url + "/api/chat", body) as response:
            for raw in response:
                line = raw.decode("utf-8").strip()
                if line.startswith("event:"):
                    event = line[6:].strip()
                elif line.startswith("data:"):
                    data = json.loads(line[5:])
                    if event == "error":
                        raise RuntimeError(
                            str(data.get("message", "conversation failed"))
                        )
                    if event in ("text", "done"):
                        full = str(
                            data.get("fullText" if event == "text" else "response", "")
                        )
                        if not full:
                            if event == "done":
                                return
                            continue
                        if not full.startswith(emitted):
                            # Some runners replace a commentary message with the
                            # final answer. Others stream both but return only the
                            # final answer in done. Neither is a transport error.
                            if event == "done" and emitted.endswith(full):
                                return
                            emitted = ""
                        pending = full[len(emitted) :]
                        while pending:
                            boundary = re.search(r"[。！？!?\n]", pending)
                            length = (
                                min(boundary.end(), TTS_CHUNK_CHARS)
                                if boundary
                                else TTS_CHUNK_CHARS
                            )
                            if (
                                not boundary
                                and len(pending) < TTS_CHUNK_CHARS
                                and event != "done"
                            ):
                                break
                            if length == TTS_CHUNK_CHARS:
                                # Prefer a phrase boundary over cutting a word at
                                # the hard limit. Keep latency and payload bounded.
                                pauses = list(
                                    re.finditer(r"[、，,；;\s]", pending[:length])
                                )
                                if pauses and pauses[-1].end() >= TTS_CHUNK_CHARS // 2:
                                    length = pauses[-1].end()
                            chunk, pending = pending[:length], pending[length:]
                            emitted += chunk
                            if chunk.strip():
                                yield chunk.strip()
                        if event == "done":
                            return
        raise RuntimeError("conversation ended without a reply")

    def reply(self, text):
        return "".join(self.reply_chunks(text))

    def synthesize(self, text):
        with self.request(
            self.voice_url + "/tts",
            json.dumps(
                {
                    "text": text,
                    "provider": self.provider,
                    "language": self.language,
                    "speaker": self.speaker,
                }
            ).encode(),
        ) as response:
            data = response.read(MAX_SERVICE_BYTES + 1)
        if len(data) > MAX_SERVICE_BYTES:
            raise ValueError("TTS response too large")
        return data


class Conversation:
    def __init__(self, output, services):
        self.output = output
        self.transport = output.transport
        self.services = services
        self.owner = str(uuid.uuid4())
        self.on_next_character = None
        self.closed = threading.Event()
        self.cancelled = threading.Event()
        self.busy = False
        self.generation = -1
        self.state = "connecting"
        self.error = None
        self.caption_supported = False
        self.caption_index_supported = False
        self.sentence_index = 0
        self.thread = None
        self.timings = {}
        self.transcript = ""
        self.reply_text = ""

    def call(self, action, **payload):
        return self.output.request(action, {"owner": self.owner, **payload})

    def caption(self, role, text, duration=None):
        if self.caption_supported:
            clean = " ".join(text.split())[:1000]
            if duration is not None:
                pages = max(1, (len(clean) + 23) // 24)
                interval = max(500, int(duration * 1000 / pages))
                self.transport.request(f"CAPTION_MS:{interval}")
            if role == "A" and self.caption_index_supported:
                self.sentence_index += 1
                self.transport.request(f"CAPTION_INDEX:{self.sentence_index}")
            self.transport.request(f"CAPTION:{role}:{clean}")

    def start(self):
        self.thread = threading.Thread(target=self._monitor, daemon=True)
        self.thread.start()

    def _monitor(self):
        while not self.closed.wait(POLL_SECONDS):
            try:
                if not self.transport.is_connected:
                    self.cancelled.set()
                    self.state = "disconnected"
                    continue
                if self.generation != self.transport.generation:
                    if self.busy:
                        self.cancelled.set()
                        continue
                    self.call("acquire")
                    status = self.transport.request("STATUS")
                    if not status.get("microphone"):
                        raise RuntimeError("microphone firmware required")
                    self.caption_supported = bool(status.get("caption"))
                    self.caption_index_supported = bool(status.get("caption_index"))
                    self.transport.request("MIC_CANCEL")
                    self.call(
                        "images",
                        **self.services.face_images(),
                    )
                    self.transport.request("MIC_BUTTON:on")
                    self.generation = self.transport.generation
                    self.state = "idle"
                    self.error = None
                self.call("renew")
                event = getattr(self.transport, "character_next", None)
                if event is not None and event.is_set():
                    event.clear()
                    if self.on_next_character:
                        threading.Thread(
                            target=self.on_next_character, args=(self,), daemon=True
                        ).start()
                        continue
                stop_event = getattr(self.transport, "conversation_stop", None)
                if stop_event is not None and stop_event.is_set():
                    self.error = None
                    self.cancelled.set()
                    stop_event.clear()
                    self.call("stop")
                    self.transport.request("MIC_CANCEL")
                    if not self.busy:
                        self.transport.request("MIC_BUTTON:on")
                if self.transport.user_stopped:
                    self.cancelled.set()
                    self.call("stop")
                status = self.transport.request("STATUS")
                if status.get("mic_recording"):
                    self.state = "recording"
                elif not self.busy and not status.get("mic_ready"):
                    self.state = "error" if self.error else "idle"
                if status.get("mic_ready") and not self.busy:
                    self.busy = True
                    self.cancelled.clear()
                    threading.Thread(
                        target=self._process, args=(status,), daemon=True
                    ).start()
            except Exception as exc:
                self.cancelled.set()
                self.error = str(exc)
                self.state = "error"
                self.generation = -1

    def stop_requested(self):
        event = getattr(self.transport, "conversation_stop", None)
        return self.cancelled.is_set() or (event is not None and event.is_set())

    def active(self):
        if (
            self.closed.is_set()
            or self.stop_requested()
            or self.generation != self.transport.generation
        ):
            raise RuntimeError("conversation cancelled")

    def _process(self, status):
        started = time.monotonic()
        self.timings = {}
        try:
            self.error = None
            self.transcript = ""
            self.reply_text = ""
            self.sentence_index = 0
            self.caption("U", "")
            self.state = "transcribing"
            size = status.get("mic_bytes")
            if type(size) is not int or not 0 < size <= MIC_MAX_BYTES or size % 2:
                raise ValueError("invalid recording length")
            chunk = status.get("mic_read_max", MIC_READ_BYTES)
            if type(chunk) is not int or not 1 <= chunk <= MIC_READ_MAX_BYTES:
                chunk = MIC_READ_BYTES
            encoded = status.get("mic_base64") is True
            if encoded:
                chunk = MIC_BASE64_MAX_BYTES
            pcm = bytearray()
            for offset in range(0, size, chunk):
                self.active()
                count = min(chunk, size - offset)
                if encoded:
                    part = base64.b64decode(
                        self.transport.request(f"MIC_READ_B64:{offset},{count}")["pcm"],
                        validate=True,
                    )
                else:
                    part = bytes.fromhex(
                        self.transport.request(f"MIC_READ:{offset},{count}")["pcm"]
                    )
                if len(part) != count:
                    raise ValueError("incomplete microphone read")
                pcm.extend(part)
            self.timings["transfer"] = round(time.monotonic() - started, 3)
            self.transport.request("MIC_BUTTON:off")
            self.active()
            samples = [sample[0] for sample in struct.iter_unpack("<h", pcm)]
            if sum(sample * sample for sample in samples) / len(samples) < 50**2:
                return  # Avoid STT hallucinations on silent recordings.
            stage = time.monotonic()
            text = self.services.transcribe(wav_from_pcm(pcm))
            self.timings["stt"] = round(time.monotonic() - stage, 3)
            if not text:
                return
            self.active()
            self.transcript = text
            self.caption("U", text)
            self.state = "thinking"
            with contextlib.closing(self.prepared_replies(text)) as prepared:
                for text, wav in prepared:
                    self.active()
                    self.state = "speaking"
                    with wave.open(io.BytesIO(wav)) as reader:
                        duration = reader.getnframes() / reader.getframerate()
                    job = self.call("enqueue", wav=base64.b64encode(wav).decode())
                    # Upload may take seconds; start caption paging only after
                    # the device has accepted the audio for playback.
                    self.caption("A", text, duration)
                    self.timings.setdefault(
                        "first_audio", round(time.monotonic() - started, 3)
                    )
                    while not self.closed.wait(POLL_SECONDS):
                        self.active()
                        state = self.call("status", jobId=job["id"])["job"]["state"]
                        if state == "done":
                            break
                        if state != "playing":
                            raise RuntimeError("playback stopped")

        except Exception as exc:
            if not self.stop_requested():
                self.error = str(exc)
        finally:
            self.timings["total"] = round(time.monotonic() - started, 3)
            with contextlib.suppress(Exception):
                if (
                    not self.closed.is_set()
                    and self.generation == self.transport.generation
                ):
                    self.call("stop")
                    self.caption("U", "")
                    self.transport.request("MIC_CLEAR")
                    stop_event = getattr(self.transport, "conversation_stop", None)
                    if stop_event is not None:
                        if stop_event.is_set():
                            self.cancelled.set()
                        stop_event.clear()
                    self.transport.request("MIC_BUTTON:on")
            if self.stop_requested():
                self.error = None
            self.busy = False
            self.state = "error" if self.error else "idle"

    def prepared_replies(self, prompt):
        """Bounded synthesis ahead of playback; cancelled workers never send audio."""
        ready = queue.Queue(maxsize=2)
        stopped = threading.Event()

        def put(item):
            while not stopped.is_set():
                self.active()
                try:
                    ready.put(item, timeout=POLL_SECONDS)
                    return
                except queue.Full:
                    pass

        def prepare():
            chunks = None
            try:
                chunks = self.services.reply_chunks(prompt)
                while not stopped.is_set():
                    self.active()
                    stage = time.monotonic()
                    try:
                        text = next(chunks)
                    except StopIteration:
                        break
                    self.active()
                    if stopped.is_set():
                        break
                    self.timings["agent"] = round(
                        self.timings.get("agent", 0) + time.monotonic() - stage, 3
                    )
                    self.reply_text += text
                    stage = time.monotonic()
                    wav = self.services.synthesize(text)
                    self.active()
                    if stopped.is_set():
                        break
                    self.timings["tts"] = round(
                        self.timings.get("tts", 0) + time.monotonic() - stage, 3
                    )
                    put((text, wav))
                put(None)
            except Exception as exc:
                with contextlib.suppress(Exception):
                    put(exc)
            finally:
                if chunks is not None:
                    chunks.close()

        threading.Thread(target=prepare, daemon=True).start()
        try:
            while True:
                self.active()
                try:
                    item = ready.get(timeout=POLL_SECONDS)
                except queue.Empty:
                    continue
                if item is None:
                    return
                if isinstance(item, Exception):
                    raise item
                yield item
        finally:
            stopped.set()

    def close(self):
        self.closed.set()
        self.cancelled.set()
        if self.thread:
            self.thread.join()
        with contextlib.suppress(Exception):
            self.transport.request("MIC_BUTTON:off")
            self.call("release")
