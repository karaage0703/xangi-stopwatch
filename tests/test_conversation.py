import io
import struct
import wave

import pytest

from xangi_stopwatch.conversation import Conversation, Services, wav_from_pcm


class Device:
    generation = 1
    is_connected = True
    user_stopped = False

    def __init__(self, pcm):
        self.pcm = pcm
        self.commands = []

    def request(self, command):
        self.commands.append(command)
        if command.startswith("MIC_READ:"):
            offset, size = map(int, command[9:].split(","))
            return {"pcm": self.pcm[offset : offset + size].hex()}
        return {"status": "ok"}


class Output:
    def __init__(self, device):
        self.transport = device
        self.actions = []

    def request(self, action, payload):
        self.actions.append(action)
        if action == "enqueue":
            return {"id": "job"}
        if action == "status":
            return {"job": {"state": "done"}}
        return {"status": "ok"}


class Voice:
    def __init__(self):
        self.calls = []
        self.on_reply = lambda: None

    def transcribe(self, data):
        self.calls.append("stt")
        with wave.open(io.BytesIO(data)) as wav:
            assert wav.getframerate() == 16000
        return "こんにちは"

    def reply(self, text):
        self.calls.append("agent")
        self.on_reply()
        return "こんにちは。"

    def reply_chunks(self, text):
        yield self.reply(text)

    def synthesize(self, text):
        self.calls.append("tts")
        return wav_from_pcm(bytes(3200))


def setup(pcm=None):
    if pcm is None:
        pcm = struct.pack("<h", 1000) * 8000
    output = Output(Device(pcm))
    voice = Voice()
    conversation = Conversation(output, voice)
    conversation.generation = 1
    conversation.busy = True
    return conversation, output, voice, {"mic_bytes": len(pcm)}


def test_recording_passes_stt_agent_tts_and_returns_to_manual_mode():
    c, output, voice, status = setup()
    c._process(status)
    assert voice.calls == ["stt", "agent", "tts"]
    assert "enqueue" in output.actions
    assert output.transport.commands[-2:] == ["MIC_CLEAR", "MIC_BUTTON:on"]
    assert c.state == "idle" and not c.busy


def test_cancel_during_agent_does_not_synthesize_or_play():
    c, output, voice, status = setup()
    voice.on_reply = c.cancelled.set
    c._process(status)
    assert voice.calls == ["stt", "agent"]
    assert "enqueue" not in output.actions


def test_reconnect_during_agent_drops_old_reply():
    c, output, voice, status = setup()
    voice.on_reply = lambda: setattr(output.transport, "generation", 2)
    c._process(status)
    assert voice.calls == ["stt", "agent"]
    assert "enqueue" not in output.actions
    assert "MIC_BUTTON:on" not in output.transport.commands


def test_silence_does_not_call_services():
    c, output, voice, status = setup(bytes(16000))
    c._process(status)
    assert voice.calls == []
    assert "enqueue" not in output.actions


@pytest.mark.parametrize("size", [True, -1, 3, 960002])
def test_invalid_recording_length_is_rejected(size):
    c, _, voice, _ = setup()
    c._process({"mic_bytes": size})
    assert c.error and voice.calls == []


def test_services_reject_invalid_configuration():
    with pytest.raises(ValueError):
        Services({"provider": "browser"}, "http://localhost:18888")
    with pytest.raises(ValueError):
        Services({"voice_url": "file:///tmp/private"}, "http://localhost:18888")


def test_large_mic_reads_preserve_audio_and_reduce_round_trips():
    pcm = struct.pack("<h", 1000) * 24000
    c, output, voice, status = setup(pcm)
    status["mic_read_max"] = 16384
    received = []
    original = voice.transcribe

    def transcribe(wav):
        with wave.open(io.BytesIO(wav)) as reader:
            received.append(reader.readframes(reader.getnframes()))
        return original(wav)

    voice.transcribe = transcribe
    c._process(status)
    reads = [x for x in output.transport.commands if x.startswith("MIC_READ:")]
    assert len(reads) == 3
    assert received == [pcm]
    assert set(c.timings) == {"transfer", "stt", "agent", "tts", "total", "first_audio"}


@pytest.mark.parametrize("limit", [True, 0, -1, 16385, "16384"])
def test_invalid_mic_read_limit_falls_back_to_legacy_size(limit):
    c, output, _, status = setup()
    status["mic_read_max"] = limit
    c._process(status)
    reads = [x for x in output.transport.commands if x.startswith("MIC_READ:")]
    assert len(reads) == 16
    assert not c.error


def test_transcript_and_reply_are_available_without_caption_firmware():
    c, output, _, status = setup()
    c._process(status)
    assert c.transcript == "こんにちは"
    assert c.reply_text == "こんにちは。"
    assert not any(x.startswith("CAPTION:") for x in output.transport.commands)


def test_caption_commands_follow_recognition_and_reply():
    c, output, _, status = setup()
    c.caption_supported = True
    c._process(status)
    captions = [x for x in output.transport.commands if x.startswith("CAPTION:")]
    assert captions == [
        "CAPTION:U:",
        "CAPTION:U:こんにちは",
        "CAPTION:A:こんにちは。",
        "CAPTION:U:",
    ]
    c.caption("U", "a\r\nMIC_START\nb")
    assert output.transport.commands[-1] == "CAPTION:U:a MIC_START b"


def test_cancel_does_not_publish_agent_reply():
    c, _, voice, status = setup()
    voice.on_reply = c.cancelled.set
    c._process(status)
    assert c.transcript == "こんにちは"
    assert c.reply_text == ""


def test_stream_speaks_sentence_before_done_and_does_not_repeat(monkeypatch):
    service = Services({}, "http://localhost:18888")
    service.session_id = "test"
    stream = io.BytesIO(
        'event: text\ndata: {"fullText":"最初です。続き"}\n\nevent: text\ndata: {"fullText":"最初です。続きです。"}\n\nevent: done\ndata: {"response":"最初です。続きです。最後"}\n\n'.encode()
    )
    monkeypatch.setattr(service, "request", lambda *args: stream)
    chunks = service.reply_chunks("hello")
    assert next(chunks) == "最初です。"
    assert not stream.closed and stream.tell() < len(stream.getvalue())
    assert list(chunks) == ["続きです。", "最後"]


def test_prefetch_synthesizes_next_sentence_during_playback():
    import threading

    c, output, voice, status = setup()
    second_ready = threading.Event()
    voice.reply_chunks = lambda text: (x for x in ["最初。", "次。"])
    original = voice.synthesize

    def synth(text):
        result = original(text)
        if text == "次。":
            second_ready.set()
        return result

    voice.synthesize = synth
    original_call = output.request

    def request(action, payload):
        if action == "status":
            assert second_ready.wait(2), "next TTS waited for playback completion"
        return original_call(action, payload)

    output.request = request
    c._process(status)
    assert not c.error
    assert output.actions.count("enqueue") == 2
    assert c.reply_text == "最初。次。"


def test_final_answer_replaces_commentary_without_aborting(monkeypatch):
    service = Services({}, "http://localhost:18888")
    service.session_id = "test"
    monkeypatch.setattr(
        service,
        "request",
        lambda *args: io.BytesIO(
            'event: text\ndata: {"fullText":"最初。"}\n\nevent: done\ndata: {"response":"変更。"}\n\n'.encode()
        ),
    )
    chunks = service.reply_chunks("hello")
    assert next(chunks) == "最初。"
    assert list(chunks) == ["変更。"]


def test_synthesis_error_reaches_consumer_without_hanging():
    c, _, voice, _ = setup()

    def fail(text):
        raise RuntimeError("synthesis failed")

    voice.synthesize = fail
    with pytest.raises(RuntimeError, match="synthesis failed"):
        next(c.prepared_replies("hello"))


def test_cancel_during_prefetched_synthesis_drops_audio():
    import threading

    c, _, voice, _ = setup()
    entered, release = threading.Event(), threading.Event()
    original = voice.synthesize

    def synth(text):
        entered.set()
        assert release.wait(2)
        return original(text)

    voice.synthesize = synth
    results = []

    def consume():
        try:
            results.extend(c.prepared_replies("hello"))
        except RuntimeError:
            pass

    consumer = threading.Thread(target=consume)
    consumer.start()
    assert entered.wait(2)
    c.cancelled.set()
    release.set()
    consumer.join(2)
    assert not consumer.is_alive() and results == []


def test_base64_transfer_preserves_pcm_with_fewer_requests():
    import base64

    pcm = struct.pack("<h", 1000) * 24000
    c, output, voice, status = setup(pcm)
    original = output.transport.request

    def request(command):
        if command.startswith("MIC_READ_B64:"):
            output.transport.commands.append(command)
            offset, count = map(int, command.split(":")[1].split(","))
            return {"pcm": base64.b64encode(pcm[offset : offset + count]).decode()}
        return original(command)

    output.transport.request = request
    received = []

    def transcribe(wav):
        with wave.open(io.BytesIO(wav)) as reader:
            received.append(reader.readframes(reader.getnframes()))
        return ""

    voice.transcribe = transcribe
    status["mic_base64"] = True
    c._process(status)
    assert not c.error and received == [pcm]
    assert (
        len(
            [
                cmd
                for cmd in output.transport.commands
                if cmd.startswith("MIC_READ_B64:")
            ]
        )
        == 2
    )


def test_sentence_index_and_final_caption_clear():
    c, output, _, status = setup()
    c.caption_supported = c.caption_index_supported = True
    c._process(status)
    assert "CAPTION_INDEX:1" in output.transport.commands
    assert output.transport.commands[-3:] == [
        "CAPTION:U:",
        "MIC_CLEAR",
        "MIC_BUTTON:on",
    ]


@pytest.mark.parametrize(
    "frames",
    [
        [
            ("text", "探してみます。"),
            ("text", "江戸では。続き"),
            ("text", "江戸では。続きです。"),
            ("done", "江戸では。続きです。"),
        ],
        [
            ("text", "探してみます。江戸では。続きです。"),
            ("done", "江戸では。続きです。"),
        ],
        [("text", "探してみます。"), ("text", ""), ("done", "江戸では。続きです。")],
    ],
)
def test_commentary_and_final_answer_are_both_spoken_once(monkeypatch, frames):
    import json

    service = Services({}, "http://localhost:18888")
    service.session_id = "test"
    payload = "".join(
        f"event: {event}\ndata: "
        + json.dumps({"response" if event == "done" else "fullText": text})
        + "\n\n"
        for event, text in frames
    )
    monkeypatch.setattr(service, "request", lambda *args: io.BytesIO(payload.encode()))
    assert list(service.reply_chunks("歴史の話")) == [
        "探してみます。",
        "江戸では。",
        "続きです。",
    ]


def test_answer_caption_starts_after_audio_upload():
    c, output, _, status = setup()
    c.caption_supported = True
    original = output.request
    uploaded = []

    def request(action, payload):
        if action == "enqueue":
            assert not any(
                x.startswith("CAPTION:A:") for x in output.transport.commands
            )
            uploaded.append(True)
        return original(action, payload)

    output.request = request
    c._process(status)
    assert uploaded and not c.error
    assert "CAPTION:A:こんにちは。" in output.transport.commands


def test_long_reply_prefers_phrase_boundary(monkeypatch):
    import json

    service = Services({}, "http://localhost:18888")
    service.session_id = "test"
    phrase = "あ" * 50 + "、"
    answer = phrase + "い" * 40 + "。"
    payload = "event: done\ndata: " + json.dumps({"response": answer}) + "\n\n"
    monkeypatch.setattr(service, "request", lambda *args: io.BytesIO(payload.encode()))
    assert list(service.reply_chunks("hello")) == [phrase, "い" * 40 + "。"]


def test_device_stop_during_reply_suppresses_late_audio_without_error():
    import threading

    c, output, voice, status = setup()
    output.transport.conversation_stop = threading.Event()
    voice.on_reply = output.transport.conversation_stop.set
    c._process(status)
    assert "enqueue" not in output.actions
    assert c.error is None and c.state == "idle"
    assert not output.transport.conversation_stop.is_set()
    assert output.transport.commands[-1] == "MIC_BUTTON:on"
    # A fresh recording can be processed after stopping the old reply.
    voice.on_reply = lambda: None
    c.busy = True
    c.cancelled.clear()
    c._process(status)
    assert "enqueue" in output.actions
    assert c.error is None
