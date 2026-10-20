"""StopWatch-owned conversation settings and lifecycle."""

import base64
import json
import os
import threading
import urllib.request
import uuid
from pathlib import Path

from .conversation import Conversation, Services
from .faces import FACE_PATHS, load_faces

IMAGE_SETTINGS = {"image_" + name: path for name, path in FACE_PATHS.items()}

DEFAULTS = dict(
    name="キャラ1",
    agent_id="xangi:default",
    provider="voicevox",
    speaker=1,
    language="ja-JP",
    **IMAGE_SETTINGS,
)
LANGUAGES = {"ja-JP", "en-US", "zh-CN", "es-ES", "fr-FR", "pt-BR"}


class Settings:
    def __init__(self, output, path, host_url):
        self.output, self.path, self.host_url = output, Path(path), host_url
        self.lock = threading.RLock()
        self.conversation = None
        self.config = json.loads(self.path.read_text()) if self.path.exists() else {}
        self.voice = {**DEFAULTS, **self.config.get("conversation", {})}
        # Ignore the retired opt-in flag in existing configuration files.
        self.voice.pop("enabled", None)
        self.characters = self.config.get("characters") or [
            {"id": "default", **{k: self.voice[k] for k in DEFAULTS}}
        ]
        for character in self.characters:
            for key, value in IMAGE_SETTINGS.items():
                character.setdefault(key, value)
        self.selected = self.config.get("active_character", self.characters[0]["id"])
        selected = next(
            (c for c in self.characters if c["id"] == self.selected), self.characters[0]
        )
        self.selected = selected["id"]
        self.voice.update({k: selected[k] for k in DEFAULTS})
        self._start()

    def _start(self):
        services = Services(self.voice, self.host_url)
        self.conversation = Conversation(self.output, services)
        self.conversation.on_next_character = self.next_character
        self.conversation.start()

    def agents(self):
        service = Services(self.voice, self.host_url)
        with service.request(
            self.host_url.rstrip("/") + "/api/agents", None
        ) as response:
            data = json.loads(response.read(4_000_000))
        return [
            {k: a.get(k, "") for k in ("id", "name", "backend", "model")}
            for a in data.get("agents", [])
        ]

    def speakers(self):
        # VOICEVOX is shared with the voice service; no Avatar process is involved.
        url = self.config.get("voicevox_url", "http://127.0.0.1:50021").rstrip("/")
        with urllib.request.urlopen(url + "/speakers", timeout=5) as response:
            data = json.loads(response.read(4_000_000))
        return [
            dict(id=s["id"], name=f"{v['name']} / {s['name']}")
            for v in data
            for s in v["styles"]
        ]

    def preview(self, payload):
        if not isinstance(payload, dict) or set(payload) - {
            "agent_id",
            "image_closed",
            "image_open",
        }:
            raise ValueError("invalid image settings")
        voice = {**self.voice, **payload}
        return load_faces(Services(voice, self.host_url), voice, include_status=True)

    def voice_test(self, payload):
        if not isinstance(payload, dict) or set(payload) - {
            "provider",
            "speaker",
            "language",
        }:
            raise ValueError("invalid voice test settings")
        voice = {**self.voice, **payload}
        if voice["provider"] not in ("voicevox", "piper"):
            raise ValueError("invalid voice")
        if type(voice["speaker"]) is not int or not 0 <= voice["speaker"] <= 1000000:
            raise ValueError("invalid speaker")
        if not isinstance(voice["language"], str) or voice["language"] not in LANGUAGES:
            raise ValueError("invalid language")
        wav = Services(voice, self.host_url).synthesize(
            "こんにちは。音声のテストです。"
        )
        return {"wav": base64.b64encode(wav).decode()}

    def display_get(self):
        from .dashboard import DEFAULT_DISPLAY, PROVIDERS

        with self.lock:
            return {
                **DEFAULT_DISPLAY,
                "backends": sorted(PROVIDERS),
                **self.config.get("display", {}),
            }

    def display_save(self, payload):
        from .dashboard import PROVIDERS

        if (
            not isinstance(payload, dict)
            or not {"mode", "backend"} <= set(payload)
            or set(payload) - {"mode", "backend", "backends"}
        ):
            raise ValueError("invalid display settings")
        if not all(isinstance(payload[key], str) for key in ("mode", "backend")):
            raise ValueError("invalid display selection")
        if payload["mode"] not in ("single", "multiple") or payload[
            "backend"
        ] not in PROVIDERS | {"default", "selected"}:
            raise ValueError("invalid display selection")
        with self.lock:
            backends = payload.get("backends", self.display_get()["backends"])
            if (
                not isinstance(backends, list)
                or not backends
                or any(
                    not isinstance(item, str) or item not in PROVIDERS
                    for item in backends
                )
                or len(backends) != len(set(backends))
            ):
                raise ValueError("表示するバックエンドを1つ以上選んでください")
            config = {**self.config, "display": {**payload, "backends": list(backends)}}
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            with temporary.open("w") as stream:
                os.chmod(temporary, 0o600)
                json.dump(config, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
            os.replace(temporary, self.path)
            self.config = config
            return self.display_get()

    def get(self):
        with self.lock:
            return {
                **{key: self.voice[key] for key in DEFAULTS},
                "active_character": self.selected,
                "characters": [dict(c) for c in self.characters],
            }

    def save(self, payload, *, character_id=None, force=False, characters=None):
        if not isinstance(payload, dict) or set(payload) - set(DEFAULTS):
            raise ValueError("invalid conversation settings")
        with self.lock:
            voice = {**self.voice, **payload}
            if (
                not isinstance(voice["name"], str)
                or not 1 <= len(voice["name"].strip()) <= 40
            ):
                raise ValueError("キャラ名は1〜40文字で入力してください")
            voice["name"] = voice["name"].strip()
            if voice["provider"] not in ("voicevox", "piper"):
                raise ValueError("invalid voice")
            if (
                not isinstance(voice["language"], str)
                or voice["language"] not in LANGUAGES
            ):
                raise ValueError("invalid language")
            if (
                type(voice["speaker"]) is not int
                or not 0 <= voice["speaker"] <= 1000000
            ):
                raise ValueError("invalid speaker")
            if voice["agent_id"] not in {a["id"] for a in self.agents()}:
                raise ValueError("選択したAgentが見つかりません")
            old = self.conversation
            if old and not force and (old.busy or old.state == "recording"):
                raise RuntimeError("会話が終わってから保存してください")
            Services(
                voice, self.host_url
            ).face_images()  # Validate both images before saving.
            selected = character_id or self.selected
            saved_characters = [
                dict(c) for c in (self.characters if characters is None else characters)
            ]
            character = {"id": selected, **{k: voice[k] for k in DEFAULTS}}
            if any(c["id"] == selected for c in saved_characters):
                saved_characters = [
                    character if c["id"] == selected else c for c in saved_characters
                ]
            else:
                if len(saved_characters) >= 20:
                    raise ValueError("保存できるキャラは20件までです")
                saved_characters.append(character)
            config = {
                **self.config,
                "conversation": voice,
                "characters": saved_characters,
                "active_character": selected,
            }
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            with temporary.open("w") as stream:
                os.chmod(temporary, 0o600)
                json.dump(config, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
            # Finish any monitor request before releasing ownership and replacing it.
            if old:
                old.close()
            try:
                os.replace(temporary, self.path)
            except OSError:
                self.conversation = None
                self._start()
                raise
            self.config, self.voice, self.conversation = config, voice, None
            self.characters, self.selected = saved_characters, selected
            self._start()
            return self.get()

    def character_action(self, payload):
        if not isinstance(payload, dict) or set(payload) - {"action", "id"}:
            raise ValueError("invalid character action")
        with self.lock:
            action = payload.get("action")
            if action == "duplicate":
                return self.save(
                    {"name": (self.voice["name"][:36] + " コピー")},
                    character_id=str(uuid.uuid4()),
                )
            target = next(
                (c for c in self.characters if c["id"] == payload.get("id")), None
            )
            if target is None:
                raise ValueError("キャラが見つかりません")
            if action == "select":
                return self.save(
                    {k: target[k] for k in DEFAULTS}, character_id=target["id"]
                )
            if action == "delete":
                remaining = [c for c in self.characters if c["id"] != target["id"]]
                if not remaining:
                    raise ValueError("最後のキャラは削除できません")
                active = next(
                    (c for c in remaining if c["id"] == self.selected), remaining[0]
                )
                return self.save(
                    {k: active[k] for k in DEFAULTS},
                    character_id=active["id"],
                    characters=remaining,
                )
            raise ValueError("invalid character action")

    def next_character(self, source):
        # Called on a separate thread so closing the old monitor cannot join itself.
        with self.lock:
            if source is not self.conversation or len(self.characters) < 2:
                return
            index = next(
                i for i, c in enumerate(self.characters) if c["id"] == self.selected
            )
            target = self.characters[(index + 1) % len(self.characters)]
            try:
                self.save(
                    {k: target[k] for k in DEFAULTS},
                    character_id=target["id"],
                    force=True,
                )
            except Exception as exc:
                source.error = str(exc)

    def close(self):
        if self.conversation:
            self.conversation.close()
