import io
import json
from unittest.mock import Mock

import pytest

from xangi_stopwatch.conversation import Services
from xangi_stopwatch.settings import Settings


@pytest.fixture
def settings(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"transport": "tailnet", "peer": "100.64.0.1"}))
    monkeypatch.setattr(Settings, "_start", lambda self: None)
    store = Settings(Mock(), path, "http://localhost:18888")
    monkeypatch.setattr(
        store, "agents", lambda: [{"id": "xangi:default"}, {"id": "other"}]
    )
    monkeypatch.setattr(Services, "face_images", lambda self: {})
    return store


def test_settings_save_preserves_connection_and_reloads(settings):
    settings.save(
        {
            "agent_id": "other",
            "speaker": 3,
            "image_closed": "assets/closed.png",
        }
    )
    saved = json.loads(settings.path.read_text())
    assert saved["peer"] == "100.64.0.1"
    assert saved["conversation"]["agent_id"] == "other"
    assert settings.path.stat().st_mode & 0o777 == 0o600
    reloaded = Settings(Mock(), settings.path, "http://localhost:18888")
    assert reloaded.get() == settings.get()


@pytest.mark.parametrize(
    "payload",
    [
        {"enabled": "true"},
        {"speaker": True},
        {"speaker": -1},
        {"provider": "browser"},
        {"face": "../../x"},
        {"agent_id": "absent"},
        {"voice_url": "http://attacker"},
        {"language": []},
        [],
    ],
)
def test_invalid_settings_leave_disk_unchanged(settings, payload):
    before = settings.path.read_text()
    with pytest.raises((ValueError, TypeError)):
        settings.save(payload)
    assert settings.path.read_text() == before


def test_save_during_recording_does_not_interrupt(settings):
    settings.conversation = Mock(busy=False, state="recording")
    with pytest.raises(RuntimeError):
        settings.save({"speaker": 4})
    settings.conversation.close.assert_not_called()


def test_voice_requests_do_not_use_avatar(monkeypatch):
    service = Services({"speaker": 3, "language": "en-US"}, "http://localhost:18888")
    calls = []

    def request(url, body, content_type="application/json"):
        calls.append((url, body))
        return io.BytesIO(b'{"text":"hello"}' if "/stt?" in url else b"wave")

    monkeypatch.setattr(service, "request", request)
    assert service.transcribe(b"wav") == "hello"
    assert service.synthesize("hello") == b"wave"
    assert calls[0][0] == "http://127.0.0.1:4174/stt?language=en-US"
    assert calls[1][0] == "http://127.0.0.1:4174/tts"
    assert json.loads(calls[1][1])["speaker"] == 3


def test_voice_test_uses_unsaved_selection_without_changing_config(
    settings, monkeypatch
):
    before = settings.path.read_text()
    seen = []

    def synth(service, text):
        seen.append((service.speaker, service.provider, text))
        return b"wave"

    monkeypatch.setattr(Services, "synthesize", synth)
    assert settings.voice_test({"speaker": 17}) == {"wav": "d2F2ZQ=="}
    assert seen[0][0] == 17
    assert settings.path.read_text() == before


@pytest.mark.parametrize(
    "payload",
    [
        {"speaker": True},
        {"speaker": -1},
        {"voice_url": "http://other"},
        {"language": []},
    ],
)
def test_voice_test_rejects_invalid_input(settings, payload):
    with pytest.raises(ValueError):
        settings.voice_test(payload)


@pytest.mark.parametrize("legacy", [True, False])
def test_legacy_enabled_is_ignored_and_conversation_starts(
    tmp_path, monkeypatch, legacy
):
    from xangi_stopwatch import settings as module

    path = tmp_path / "config.json"
    path.write_text(json.dumps({"conversation": {"enabled": legacy, "speaker": 17}}))
    conversation = Mock()
    monkeypatch.setattr(module, "Conversation", Mock(return_value=conversation))
    store = Settings(Mock(), path, "http://localhost:18888")
    conversation.start.assert_called_once()
    assert "enabled" not in store.get()
    assert "enabled" not in store.voice
    assert store.get()["speaker"] == 17


def test_save_removes_legacy_flag_and_preserves_service(settings):
    settings.config["conversation"] = {"enabled": False}
    settings.voice["voice_url"] = "http://localhost:4174"
    settings.save({"speaker": 17})
    voice = json.loads(settings.path.read_text())["conversation"]
    assert "enabled" not in voice
    assert voice["voice_url"] == "http://localhost:4174"


def test_characters_duplicate_edit_select_delete_and_reload(settings):
    first = settings.get()["active_character"]
    settings.save({"name": "文香", "speaker": 17})
    second = settings.character_action({"action": "duplicate"})["active_character"]
    assert second != first
    settings.save({"name": "別のキャラ", "speaker": 3, "agent_id": "other"})
    settings.character_action({"action": "select", "id": first})
    assert settings.get()["speaker"] == 17
    assert settings.get()["name"] == "文香"
    reloaded = Settings(Mock(), settings.path, "http://localhost:18888")
    assert reloaded.get() == settings.get()
    settings.character_action({"action": "delete", "id": first})
    assert settings.get()["active_character"] == second
    assert settings.get()["speaker"] == 3
    with pytest.raises(ValueError, match="最後"):
        settings.character_action({"action": "delete", "id": second})


def test_button_cycles_busy_character_but_rejects_stale_callback(settings):
    first = settings.selected
    settings.character_action({"action": "duplicate"})
    current = Mock(busy=True, state="speaking")
    settings.conversation = current
    settings.next_character(Mock())
    current.close.assert_not_called()
    settings.next_character(current)
    current.close.assert_called_once()
    assert settings.selected == first


def test_character_switch_validation_failure_keeps_current(settings, monkeypatch):
    first = settings.selected
    second = settings.character_action({"action": "duplicate"})["active_character"]
    monkeypatch.setattr(
        Services, "face_images", Mock(side_effect=ValueError("missing image"))
    )
    before = settings.path.read_text()
    with pytest.raises(ValueError):
        settings.character_action({"action": "select", "id": first})
    assert settings.selected == second
    assert settings.path.read_text() == before


def test_character_actions_reject_unknown_or_invalid_values(settings):
    for payload in [
        {"action": "select", "id": "missing"},
        [],
        {"action": "duplicate", "voice_url": "x"},
    ]:
        with pytest.raises(ValueError):
            settings.character_action(payload)
    for name in ["", " " * 3, "a" * 41, 3]:
        with pytest.raises(ValueError):
            settings.save({"name": name})


def test_custom_character_paths_survive_save_and_reload(settings):
    settings.save({"image_closed": "old/closed.png", "image_open": "old/open.png"})
    saved = json.loads(settings.path.read_text())
    for character in saved["characters"] + [saved["conversation"]]:
        assert character["image_closed"] == "old/closed.png"
        assert character["image_open"] == "old/open.png"
    saved["characters"][0]["image_closed"] = "legacy/closed.png"
    settings.path.write_text(json.dumps(saved))
    reloaded = Settings(Mock(), settings.path, "http://localhost:18888")
    assert reloaded.get()["image_closed"] == "legacy/closed.png"


def test_preview_reports_fallback_and_uses_edited_paths(
    settings, monkeypatch, tmp_path
):
    from PIL import Image

    def request(self, url, body):
        value = (
            {"agents": [{"id": "xangi:default", "workspaceId": "w"}]}
            if url.endswith("/agents")
            else {"workspaces": [{"id": "w", "path": str(tmp_path)}]}
        )
        return io.BytesIO(json.dumps(value).encode())

    monkeypatch.setattr(Services, "request", request)
    assert settings.preview({})["fallback"] is True
    Image.new("RGB", (20, 20), "blue").save(tmp_path / "face.png")
    preview = settings.preview({"image_closed": "face.png", "image_open": "face.png"})
    assert preview["fallback"] is False
    assert preview["closed"] == preview["open"]
