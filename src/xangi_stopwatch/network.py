"""Device-stored Wi-Fi profiles. Passwords are write-only and never returned."""

MAX_PROFILES = 5


class Network:
    def __init__(self, output, settings):
        self.output, self.settings = output, settings

    def get(self):
        with self.output.lock:
            data = self.output.transport.request("WIFI_LIST")
        return {
            "active": data["active"],
            "profiles": [
                {
                    "id": p["id"],
                    "ssid": bytes.fromhex(p["ssid_hex"]).decode("utf-8"),
                    "built_in": p["built_in"],
                }
                for p in data["profiles"]
            ],
        }

    def save(self, payload):
        if not isinstance(payload, dict):
            raise ValueError("invalid network settings")
        action = payload.get("action")
        if action == "add":
            if set(payload) != {"action", "ssid", "password"}:
                raise ValueError("SSIDとパスワードを入力してください")
            ssid, password = payload["ssid"], payload["password"]
            if (
                not isinstance(ssid, str)
                or not isinstance(password, str)
                or "\0" in ssid
                or "\0" in password
                or not 1 <= len(ssid.encode()) <= 32
                or not (
                    len(password.encode()) == 0 or 8 <= len(password.encode()) <= 63
                )
            ):
                raise ValueError(
                    "SSIDは1〜32バイト、パスワードは8〜63バイト（認証なしは空欄）です"
                )
            command = f"WIFI_ADD:{ssid.encode().hex()},{password.encode().hex()}"
        elif action in {"select", "delete"}:
            slot = payload.get("id")
            if (
                set(payload) != {"action", "id"}
                or type(slot) is not int
                or not 0 <= slot < MAX_PROFILES
            ):
                raise ValueError("invalid Wi-Fi id")
            command = f"WIFI_{action.upper()}:{slot}"
        else:
            raise ValueError("invalid network action")
        with self.settings.lock:
            conversation = self.settings.conversation
            if conversation and (
                conversation.busy or conversation.state == "recording"
            ):
                raise RuntimeError("会話が終わってからWi-Fi設定を変更してください")
            with self.output.lock:
                # Transport never logs requests; do not return credentials even on error.
                self.output.transport.request(command)
        return {"status": "ok", "reconnecting": action == "select"}
