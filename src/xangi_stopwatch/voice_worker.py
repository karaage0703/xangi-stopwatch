#!/usr/bin/env python3
"""Shared voice service for StopWatch and Avatar; adapted from xangi-avatar (MIT, copyright 2026 karaage)."""

from __future__ import annotations

import io
import json
import os
import subprocess
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(os.environ.get("XANGI_VOICE_ROOT", ".voice")).resolve()
PIPER_BIN = Path(os.environ.get("XANGI_PIPER_BIN", ROOT / "piper/PiperPlus.Cli"))
PIPER_MODEL = Path(
    os.environ.get("XANGI_PIPER_MODEL", ROOT / "models/tsukuyomi-chan-6lang-fp16.onnx")
)
PIPER_CONFIG = Path(os.environ.get("XANGI_PIPER_CONFIG", ROOT / "models/config.json"))
VOICEVOX_URL = os.environ.get("XANGI_VOICEVOX_URL", "http://127.0.0.1:50021").rstrip(
    "/"
)
_model = None
_backend = None
_device = None
_inference_lock = threading.Lock()
_model_lock = threading.Lock()
_piper_lock = threading.Lock()


def detect_backend(device: str) -> tuple[str, str]:
    """Prefer CUDA, including PyTorch when CTranslate2 is CPU-only."""
    if device not in {"auto", "cpu", "cuda"}:
        raise ValueError(f"Unsupported Whisper device: {device}")
    if device == "cpu":
        return "cpu", "faster-whisper"
    try:
        import ctranslate2

        if (
            ctranslate2.get_cuda_device_count() > 0
            and ctranslate2.get_supported_compute_types("cuda")
        ):
            return "cuda", "faster-whisper"
    except (ImportError, RuntimeError, ValueError):
        pass
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda", "openai-whisper"
    except ImportError:
        pass
    if device == "cuda":
        raise RuntimeError("CUDA requested but neither Whisper backend supports it")
    return "cpu", "faster-whisper"


def whisper_model():
    global _model, _backend, _device
    with _model_lock:
        if _model is None:
            device, backend = detect_backend(
                os.environ.get("XANGI_WHISPER_DEVICE", "auto")
            )
            name = os.environ.get("XANGI_WHISPER_MODEL", "medium")
            if backend == "openai-whisper":
                import whisper

                model = whisper.load_model(name, device=device)
            else:
                from faster_whisper import WhisperModel

                compute = (
                    "float16"
                    if device == "cuda"
                    else os.environ.get("XANGI_WHISPER_COMPUTE", "int8")
                )
                model = WhisperModel(name, device=device, compute_type=compute)
            _model, _backend, _device = model, backend, device
        return _model


def transcribe(audio: bytes, language: str) -> dict:
    # A shared model must not process concurrent requests on different threads.
    with _inference_lock:
        return _transcribe(audio, language)


def _transcribe(audio: bytes, language: str) -> dict:
    started = time.monotonic()
    model = whisper_model()
    lang = language.split("-")[0]
    if _backend == "openai-whisper":
        from faster_whisper.audio import decode_audio
        from faster_whisper.vad import get_speech_timestamps

        samples = decode_audio(io.BytesIO(audio), sampling_rate=16000)
        duration = len(samples) / 16000
        # Keep original timestamps; use VAD to reject silence, not concatenate audio.
        speech = get_speech_timestamps(samples)
        result = (
            model.transcribe(
                samples,
                language=lang,
                beam_size=5,
                temperature=0,
                logprob_threshold=-0.8,
                no_speech_threshold=0.5,
                condition_on_previous_text=False,
                fp16=_device == "cuda",
            )
            if speech
            else {"segments": [], "language": lang}
        )
        detected_language = result["language"]
        items = [
            {
                "start": part["start"],
                "end": part["end"],
                "text": part["text"].strip(),
                "averageLogProbability": round(part["avg_logprob"], 4),
                "noSpeechProbability": round(part["no_speech_prob"], 4),
            }
            for part in result["segments"]
        ]
    else:
        segments, info = model.transcribe(
            io.BytesIO(audio),
            language=lang,
            beam_size=5,
            log_prob_threshold=-0.8,
            no_speech_threshold=0.5,
            condition_on_previous_text=False,
            vad_filter=True,
            vad_parameters={
                "threshold": 0.5,
                "min_speech_duration_ms": 250,
                "min_silence_duration_ms": 500,
                "speech_pad_ms": 250,
            },
        )
        items = [
            {
                "start": part.start,
                "end": part.end,
                "text": part.text.strip(),
                "averageLogProbability": round(part.avg_logprob, 4),
                "noSpeechProbability": round(part.no_speech_prob, 4),
            }
            for part in segments
        ]
        duration, detected_language = info.duration, info.language
    text = "".join(part["text"] for part in items).strip()
    speech_seconds = round(
        sum(max(0, part["end"] - part["start"]) for part in items), 3
    )
    total_weight = sum(max(0.001, part["end"] - part["start"]) for part in items)
    average_log_probability = (
        round(
            sum(
                part["averageLogProbability"] * max(0.001, part["end"] - part["start"])
                for part in items
            )
            / total_weight,
            4,
        )
        if items
        else None
    )
    no_speech_probability = round(
        max((part["noSpeechProbability"] for part in items), default=1.0), 4
    )
    result = {
        "text": text,
        "language": detected_language,
        "segments": items,
        "durationSeconds": round(duration, 3),
        "speechSeconds": speech_seconds,
        "averageLogProbability": average_log_probability,
        "noSpeechProbability": no_speech_probability,
        "backend": _backend,
        "device": _device,
        "elapsedSeconds": round(time.monotonic() - started, 3),
    }
    return result


def piper_synthesize(text: str) -> bytes:
    if not PIPER_BIN.exists() or not PIPER_MODEL.exists():
        raise RuntimeError(
            "Piper assets are not installed; configure the shared Piper assets"
        )
    with _piper_lock, tempfile.NamedTemporaryFile(suffix=".wav") as output:
        command = [
            str(PIPER_BIN),
            "--model",
            str(PIPER_MODEL),
            "--language",
            "ja-en-zh-es-fr-pt",
            "--length-scale",
            "1.5",
            "--noise-scale",
            "0.667",
            "--quiet",
            "--output_file",
            output.name,
            "-t",
            text,
        ]
        if PIPER_CONFIG.exists():
            command[3:3] = ["--config", str(PIPER_CONFIG)]
        result = subprocess.run(
            command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=60
        )
        if result.returncode:
            raise RuntimeError(result.stderr.decode(errors="replace")[-500:])
        return Path(output.name).read_bytes()


def voicevox_synthesize(text: str, speaker: int) -> bytes:
    params = urllib.parse.urlencode({"text": text, "speaker": speaker})
    with urllib.request.urlopen(
        urllib.request.Request(f"{VOICEVOX_URL}/audio_query?{params}", method="POST"),
        timeout=15,
    ) as response:
        query = json.loads(response.read())
    synth = urllib.request.Request(
        f"{VOICEVOX_URL}/synthesis?speaker={speaker}",
        data=json.dumps(query).encode(),
        headers={"content-type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(synth, timeout=60) as response:
        return response.read()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"voice-worker: {fmt % args}", flush=True)

    def json(self, status: int, payload: dict):
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self.json(
                200,
                {
                    "ok": True,
                    "whisper": True,
                    "whisperLoaded": _model is not None,
                    "whisperBackend": _backend,
                    "whisperDevice": _device,
                    "whisperModel": os.environ.get("XANGI_WHISPER_MODEL", "medium"),
                    "piper": PIPER_BIN.exists() and PIPER_MODEL.exists(),
                    "voicevox": True,
                },
            )
        else:
            self.json(404, {"error": "not found"})

    def do_POST(self):
        try:
            length = int(self.headers.get("content-length", "0"))
            if length > 32 * 1024 * 1024:
                return self.json(413, {"error": "audio is too large"})
            body = self.rfile.read(length)
            route = urllib.parse.urlparse(self.path)
            query = urllib.parse.parse_qs(route.query)
            if route.path == "/stt":
                return self.json(
                    200, transcribe(body, query.get("language", ["ja-JP"])[0])
                )
            if route.path == "/tts":
                payload = json.loads(body or b"{}")
                text = str(payload.get("text", "")).strip()[:2000]
                if not text:
                    return self.json(400, {"error": "text is required"})
                wav = (
                    voicevox_synthesize(text, int(payload.get("speaker", 1)))
                    if payload.get("provider") == "voicevox"
                    else piper_synthesize(text)
                )
                self.send_response(200)
                self.send_header("content-type", "audio/wav")
                self.send_header("content-length", str(len(wav)))
                self.end_headers()
                self.wfile.write(wav)
                return
            self.json(404, {"error": "not found"})
        except Exception as error:
            self.json(500, {"error": str(error)})


if __name__ == "__main__":
    host = os.environ.get("XANGI_VOICE_HOST", "127.0.0.1")
    port = int(os.environ.get("XANGI_VOICE_PORT", "4174"))
    print(f"voice-worker: http://{host}:{port}", flush=True)
    ThreadingHTTPServer((host, port), Handler).serve_forever()
