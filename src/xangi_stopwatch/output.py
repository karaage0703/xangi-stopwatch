"""Expiring conversation ownership, bounded audio queue and completion tracking."""

import base64
import contextlib
import io
import threading
import time
import uuid
import wave

from PIL import Image

from . import constants


class Output:
    TTL = constants.OWNER_TTL_SECONDS

    def __init__(self, transport):
        self.transport = transport
        self.lock = threading.RLock()
        self.owner = None
        self.deadline = 0
        self.generation = 0
        self.images = False
        self.jobs = {}
        self.pending = []
        self.last_job = None
        self.closed = threading.Event()

    def start(self):
        threading.Thread(target=self._watch, daemon=True).start()

    def _watch(self):
        while not self.closed.wait(constants.WATCH_INTERVAL_SECONDS):
            with self.lock:
                if not self.owner:
                    continue
                try:
                    if (
                        time.monotonic() >= self.deadline
                        or self.generation != self.transport.generation
                        or not self.transport.is_connected
                    ):
                        self._release()
                    elif self.pending:
                        self._poll()
                except Exception as exc:
                    jobs = [entry["job"] for entry in self.pending]
                    with contextlib.suppress(Exception):
                        self._stop()
                    for job in jobs:
                        job.update(state="error", error=str(exc))

    @staticmethod
    def decode(value, limit):
        if not isinstance(value, str) or len(value) > (limit * 4 // 3 + 8):
            raise ValueError("invalid or oversized payload")
        data = base64.b64decode(value, validate=True)
        if len(data) > limit:
            raise ValueError("payload too large")
        return data

    def _image(self, value):
        data = self.decode(value, constants.MAX_IMAGE_BYTES)
        try:
            with Image.open(io.BytesIO(data)) as image:
                if image.format != "JPEG" or image.size != (
                    constants.DISPLAY_WIDTH,
                    constants.DISPLAY_HEIGHT,
                ):
                    raise ValueError(
                        f"image must be {constants.DISPLAY_WIDTH}x{constants.DISPLAY_HEIGHT} JPEG"
                    )
                image.verify()
        except OSError as exc:
            raise ValueError("invalid JPEG") from exc
        return data

    def request(self, action, payload):
        if not isinstance(payload, dict):
            raise ValueError("JSON object required")
        owner = payload.get("owner")
        if not isinstance(owner, str):
            raise ValueError("owner must be UUID")
        uuid.UUID(owner)
        with self.lock:
            if self.owner and (
                time.monotonic() >= self.deadline
                or self.generation != self.transport.generation
            ):
                self._release()
            if action == "acquire":
                if self.owner and self.owner != owner:
                    raise RuntimeError("another conversation session owns the device")
                if not self.owner:
                    status = self.transport.request("STATUS")
                    if status.get("device") != "stopwatch":
                        raise RuntimeError("StopWatch conversation firmware required")
                    result = self.transport.request("AUDIO_STOP")
                    if result.get("audio_stopped") is not True:
                        raise RuntimeError("StopWatch firmware must support AUDIO_STOP")
                    self.transport.user_stopped = False
                    self.owner = owner
                    self.generation = self.transport.generation
                    self.images = False
                    self.jobs.clear()
                    self.last_job = None
                self.deadline = time.monotonic() + self.TTL
                return dict(
                    status="ok",
                    device="stopwatch",
                    width=constants.DISPLAY_WIDTH,
                    height=constants.DISPLAY_HEIGHT,
                )
            if owner != self.owner:
                raise RuntimeError("conversation session expired or is not the owner")
            self.deadline = time.monotonic() + self.TTL
            if action == "release":
                self._release()
            elif action == "stop":
                self._stop()
            elif action == "renew":
                pass
            elif action == "images":
                if self.pending:
                    raise RuntimeError("stop playback before changing character")
                frames = [self._image(payload.get(key)) for key in ("closed", "open")]
                for slot, data in enumerate(frames):
                    self.transport.request(f"SIMG:{slot},{len(data)}", data)
                self.transport.request("SFRAME:0")
                self.images = True
            elif action == "enqueue":
                return self._enqueue(payload.get("wav"))
            elif action == "status":
                job_id = payload.get("jobId", self.last_job)
                if job_id is not None and not isinstance(job_id, str):
                    raise ValueError("jobId must be a string")
                job = self.jobs.get(job_id)
                return dict(status="ok", job=dict(job) if job else None)
            else:
                raise ValueError("unknown conversation action")
            return {"status": "ok"}

    def _enqueue(self, value):
        if not self.images:
            raise RuntimeError("upload character images first")
        if len(self.pending) >= constants.MAX_PENDING_JOBS:
            raise RuntimeError("playback queue is full")
        if self.transport.user_stopped:
            raise RuntimeError(
                "StopWatch playback stopped; stop or reconnect before resuming"
            )
        data = self.decode(value, constants.MAX_AUDIO_BYTES)
        try:
            with wave.open(io.BytesIO(data), "rb") as wav:
                if (
                    wav.getnchannels() != 1
                    or wav.getsampwidth() != constants.PCM_SAMPLE_BYTES
                    or wav.getcomptype() != "NONE"
                    or not constants.MIN_SAMPLE_RATE_HZ
                    <= wav.getframerate()
                    <= constants.MAX_SAMPLE_RATE_HZ
                ):
                    raise ValueError("WAV must be 8–48kHz mono PCM16")
                duration = wav.getnframes() / wav.getframerate()
                if not 0 < duration <= constants.MAX_AUDIO_SECONDS:
                    raise ValueError(
                        f"WAV must be at most {constants.MAX_AUDIO_SECONDS} seconds"
                    )
                if (
                    len(wav.readframes(wav.getnframes()))
                    != wav.getnframes() * constants.PCM_SAMPLE_BYTES
                ):
                    raise ValueError("truncated WAV")
        except (wave.Error, EOFError) as exc:
            raise ValueError("invalid WAV") from exc
        self.transport.request(f"WAV:{len(data)}", data)
        started = time.monotonic()
        end = (
            max(started, self.pending[-1]["end"] if self.pending else started)
            + duration
        )
        job = dict(id=str(uuid.uuid4()), state="playing")
        self.jobs[job["id"]] = job
        self.last_job = job["id"]
        self.pending.append(dict(job=job, end=end))
        while len(self.jobs) > constants.JOB_HISTORY_LIMIT:
            del self.jobs[next(iter(self.jobs))]
        if len(self.pending) == 1:
            try:
                self.transport.request(f"SANIM:{constants.MOUTH_FRAME_INTERVAL_MS},0,1")
            except Exception:
                self._stop()
                raise
        self.deadline = time.monotonic() + self.TTL
        return dict(job)

    def _poll(self):
        if self.transport.user_stopped:
            self._stop(clear_user_stop=False)
            return
        status = self.transport.request("STATUS")
        now = time.monotonic()
        if now > self.pending[-1]["end"] + constants.PLAYBACK_GRACE_SECONDS:
            raise RuntimeError("device playback timed out")
        if (
            type(status.get("playing")) is not bool
            or type(status.get("queued")) is not int
        ):
            raise RuntimeError("invalid playback status")
        remaining = status["queued"] + int(status["playing"])
        completed = max(0, len(self.pending) - remaining)
        while completed and self.pending and now >= self.pending[0]["end"]:
            if len(self.pending) == 1:
                self.transport.request("SANIM:0")
                self.transport.request("SFRAME:0")
            self.pending.pop(0)["job"]["state"] = "done"
            completed -= 1

    def _stop(self, clear_user_stop=True):
        for entry in self.pending:
            entry["job"]["state"] = "cancelled"
        self.pending.clear()
        self.transport.request("AUDIO_STOP")
        if clear_user_stop:
            self.transport.user_stopped = False
        self.transport.request("SANIM:0")
        if self.images:
            self.transport.request("SFRAME:0")

    def _release(self):
        try:
            # Never send an old session's stop to a newly connected device.
            if self.generation == self.transport.generation:
                self._stop()
        finally:
            for entry in self.pending:
                entry["job"]["state"] = "cancelled"
            self.pending.clear()
            self.owner = None
            self.images = False

    def close(self):
        self.closed.set()
        with self.lock, contextlib.suppress(Exception):
            self._release()
