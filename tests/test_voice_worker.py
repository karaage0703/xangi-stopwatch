import importlib.util
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

WORKER = Path(__file__).resolve().parents[1] / "src/xangi_stopwatch/voice_worker.py"
spec = importlib.util.spec_from_file_location("voice_worker_test_target", WORKER)
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)


class VoiceWorkerTests(unittest.TestCase):
    def test_cpu_override(self):
        self.assertEqual(worker.detect_backend("cpu"), ("cpu", "faster-whisper"))

    def test_cuda_ctranslate(self):
        ct = SimpleNamespace(
            get_cuda_device_count=lambda: 1,
            get_supported_compute_types=lambda _: {"float16"},
        )
        with patch.dict(sys.modules, {"ctranslate2": ct}):
            self.assertEqual(worker.detect_backend("auto"), ("cuda", "faster-whisper"))

    def test_cpu_only_ctranslate_uses_torch_cuda(self):
        ct = SimpleNamespace(
            get_cuda_device_count=lambda: 1,
            get_supported_compute_types=Mock(side_effect=ValueError("CPU build")),
        )
        torch = SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: True))
        with patch.dict(sys.modules, {"ctranslate2": ct, "torch": torch}):
            self.assertEqual(worker.detect_backend("auto"), ("cuda", "openai-whisper"))

    def test_explicit_cuda_does_not_silently_use_cpu(self):
        ct = SimpleNamespace(get_cuda_device_count=lambda: 0)
        torch = SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: False))
        with patch.dict(sys.modules, {"ctranslate2": ct, "torch": torch}):
            self.assertEqual(worker.detect_backend("auto"), ("cpu", "faster-whisper"))
            with self.assertRaises(RuntimeError):
                worker.detect_backend("cuda")

    def test_torch_response_retains_confidence_and_duration(self):
        model = Mock()
        model.transcribe.return_value = {
            "language": "ja",
            "segments": [
                {
                    "start": 0.1,
                    "end": 0.9,
                    "text": " こんにちは ",
                    "avg_logprob": -0.1,
                    "no_speech_prob": 0.02,
                }
            ],
        }
        decoded = [0.0] * 16000
        decoder = Mock(return_value=decoded)
        with (
            patch.object(worker, "whisper_model", return_value=model),
            patch.object(worker, "_backend", "openai-whisper"),
            patch.object(worker, "_device", "cuda"),
            patch.dict(
                sys.modules,
                {
                    "faster_whisper.audio": SimpleNamespace(decode_audio=decoder),
                    "faster_whisper.vad": SimpleNamespace(
                        get_speech_timestamps=lambda _: [1]
                    ),
                },
            ),
        ):
            result = worker.transcribe(b"browser audio", "ja-JP")
        self.assertEqual(result["text"], "こんにちは")
        self.assertEqual(result["durationSeconds"], 1)
        self.assertEqual(result["averageLogProbability"], -0.1)
        self.assertEqual(result["device"], "cuda")
        self.assertEqual(result["backend"], "openai-whisper")
        self.assertEqual(model.transcribe.call_args.kwargs["language"], "ja")
        self.assertEqual(decoder.call_args.args[0].getvalue(), b"browser audio")

    def test_silence_does_not_invoke_torch_inference(self):
        model = Mock()
        with (
            patch.object(worker, "whisper_model", return_value=model),
            patch.object(worker, "_backend", "openai-whisper"),
            patch.dict(
                sys.modules,
                {
                    "faster_whisper.audio": SimpleNamespace(
                        decode_audio=lambda *a, **kw: [0.0] * 16000
                    ),
                    "faster_whisper.vad": SimpleNamespace(
                        get_speech_timestamps=lambda _: []
                    ),
                },
            ),
        ):
            result = worker.transcribe(b"silence", "ja-JP")
        model.transcribe.assert_not_called()
        self.assertEqual(result["text"], "")
        self.assertEqual(result["speechSeconds"], 0)
        self.assertEqual(result["noSpeechProbability"], 1)
