"""Managed HTTP extension for standalone StopWatch conversations."""

import argparse
import hmac
import ipaddress
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import constants
from .dashboard import Dashboard
from .network import Network
from .output import Output
from .settings import Settings
from .transport import Transport
from .ui import SETTINGS_HTML
from .usb_wifi import setup_html


def create_server(
    output,
    token,
    configuration="unconfigured",
    conversation=None,
    settings_store=None,
    dashboard=None,
):
    initial_conversation = conversation
    network = Network(output, settings_store) if settings_store else None

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def send_json(self, status, data):
            body = json.dumps(data).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def authorized(self):
            if hmac.compare_digest(
                self.headers.get("Authorization", "").encode(),
                f"Bearer {token}".encode(),
            ):
                return True
            self.send_json(401, {"error": "unauthorized"})
            return False

        def do_GET(self):
            conversation = (
                settings_store.conversation if settings_store else initial_conversation
            )
            if not self.authorized():
                return
            if self.path == "/api/wifi-setup":
                body = setup_html()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header(
                    "Content-Disposition", 'attachment; filename="stopwatch-wifi.html"'
                )
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
            elif self.path == "/":
                body = SETTINGS_HTML.encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
            elif (
                self.path in ("/api/config", "/api/agents", "/api/speakers")
                and settings_store
            ):
                try:
                    if self.path == "/api/config":
                        data = settings_store.get()
                    elif self.path == "/api/agents":
                        data = {"agents": settings_store.agents()}
                    else:
                        data = {"speakers": settings_store.speakers()}
                    self.send_json(200, data)
                except (OSError, ValueError, KeyError):
                    self.send_json(503, {"error": "設定情報を取得できません"})
            elif self.path == "/api/display" and settings_store:
                self.send_json(
                    200,
                    {
                        **settings_store.display_get(),
                        "snapshot": dashboard.snapshot if dashboard else None,
                    },
                )
            elif self.path == "/api/settings":
                try:
                    with output.lock:
                        status = output.transport.request("STATUS")
                    self.send_json(
                        200,
                        {
                            "volume": status["volume"],
                            "batteryPosition": status.get("battery_position"),
                            "textVisible": status.get("text_visible"),
                            "activeCharacter": settings_store.selected
                            if settings_store
                            else None,
                            "transcript": conversation.transcript
                            if conversation
                            else "",
                            "reply": conversation.reply_text if conversation else "",
                            "conversation": conversation.state
                            if conversation
                            else "unavailable",
                            "conversationTimings": conversation.timings
                            if conversation
                            else {},
                            "conversationError": conversation.error
                            if conversation
                            else None,
                        },
                    )
                except (RuntimeError, OSError, KeyError):
                    self.send_json(503, {"error": "StopWatchに接続できません"})
            elif self.path == "/api/network" and network:
                try:
                    self.send_json(200, network.get())
                except (RuntimeError, OSError, ValueError, KeyError):
                    self.send_json(
                        503,
                        {
                            "error": "Wi-Fi設定を取得できません。接続状態と対応ファームを確認してください"
                        },
                    )
            elif self.path == "/api/health":
                self.send_json(
                    200,
                    dict(
                        status="ok",
                        device="stopwatch",
                        connected=output.transport.is_connected,
                        configuration=configuration,
                    ),
                )
            else:
                self.send_json(404, {"error": "not found"})

        def do_POST(self):
            if not self.authorized():
                return
            settings = self.path == "/api/settings"
            config_settings = (
                self.path
                in (
                    "/api/config",
                    "/api/preview",
                    "/api/voice-test",
                    "/api/characters",
                    "/api/network",
                    "/api/display",
                )
                and settings_store is not None
            )
            if not settings and not config_settings:
                self.send_json(404, {"error": "not found"})
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= constants.MAX_HTTP_BODY_BYTES:
                    self.send_json(413, {"error": "invalid or oversized body"})
                    return
                if (
                    not self.headers.get("Content-Type", "")
                    .lower()
                    .startswith("application/json")
                ):
                    self.send_json(415, {"error": "JSON required"})
                    return
                self.connection.settimeout(constants.HTTP_READ_TIMEOUT_SECONDS)
                data = self.rfile.read(size)
                if len(data) != size:
                    raise ValueError("incomplete request body")
                payload = json.loads(data)
                if config_settings:
                    result = (
                        settings_store.display_save(payload)
                        if self.path == "/api/display"
                        else network.save(payload)
                        if self.path == "/api/network"
                        else settings_store.character_action(payload)
                        if self.path == "/api/characters"
                        else settings_store.preview(payload)
                        if self.path == "/api/preview"
                        else settings_store.voice_test(payload)
                        if self.path == "/api/voice-test"
                        else settings_store.save(payload)
                    )
                elif settings:
                    if (
                        not isinstance(payload, dict)
                        or not payload
                        or set(payload) - {"volume", "batteryPosition"}
                    ):
                        raise ValueError("expected volume or batteryPosition")
                    volume = payload.get("volume")
                    position = payload.get("batteryPosition")
                    if "volume" in payload and (
                        type(volume) is not int
                        or not 0 <= volume <= constants.MAX_VOLUME
                    ):
                        raise ValueError(
                            f"volume must be an integer from 0 to {constants.MAX_VOLUME}"
                        )
                    if "batteryPosition" in payload and position not in (
                        "right",
                        "left",
                        "center",
                        "hidden",
                    ):
                        raise ValueError("invalid batteryPosition")
                    result = {}
                    with output.lock:
                        if "volume" in payload:
                            output.transport.request(f"VOLUME:{volume}")
                            result["volume"] = volume
                        if "batteryPosition" in payload:
                            output.transport.request(f"BATTERY_POSITION:{position}")
                            result["batteryPosition"] = position
                if self.path == "/api/display" and dashboard:
                    dashboard.usage_at = 0
                    dashboard.wake.set()
                self.send_json(200, result)
            except (ValueError, UnicodeError) as exc:
                self.send_json(400, {"error": str(exc)})
            except RuntimeError as exc:
                self.send_json(409, {"error": str(exc)})
            except (OSError, TimeoutError):
                self.send_json(503, {"error": "device or request timed out"})

    return ThreadingHTTPServer((constants.HTTP_BIND_HOST, 0), Handler)


def configure(transport, path):
    if not path.exists():
        return "unconfigured"
    config = json.loads(path.read_text())
    mode = config.get("transport")
    if mode == "usb":
        port = config.get("port")
        if not isinstance(port, str) or not port:
            raise ValueError("USB port is required")
        transport.start_usb(port)
    elif mode == "tailnet":
        bind = str(ipaddress.IPv4Address(config["bind"]))
        peer = str(ipaddress.IPv4Address(config["peer"]))
        tailnet = ipaddress.IPv4Network(constants.TAILNET_CIDR)
        if (
            ipaddress.IPv4Address(bind) not in tailnet
            or ipaddress.IPv4Address(peer) not in tailnet
        ):
            raise ValueError("bind and peer must be Tailnet IPv4 addresses")
        port = config.get("port", constants.DEFAULT_TAILNET_PORT)
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError("invalid TCP port")
        transport.start_tcp(bind, port, peer)
    else:
        raise ValueError("transport must be usb or tailnet")
    return mode


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["serve"])
    parser.add_argument("--workspace", default=".")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path.home() / constants.CONFIG_RELATIVE_PATH,
    )
    args = parser.parse_args()
    token = os.environ.get("XANGI_EXTENSION_AUTH_TOKEN", "")
    if not token:
        raise SystemExit("XANGI_EXTENSION_AUTH_TOKEN is required")
    transport = Transport()
    configuration = configure(transport, args.config)
    output = Output(transport)
    output.start()
    settings_store = Settings(
        output,
        args.config,
        os.environ.get("XANGI_EXTENSION_HOST_URL", "http://127.0.0.1:18888"),
    )
    dashboard = Dashboard(output, settings_store)
    dashboard.start()
    server = create_server(
        output, token, configuration, settings_store=settings_store, dashboard=dashboard
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(
        json.dumps(
            dict(
                schemaVersion=2,
                event="ready",
                id="xangi-stopwatch",
                baseUrl=f"http://{constants.HTTP_BIND_HOST}:{server.server_port}",
                workspace=str(Path(args.workspace).resolve()),
                pid=os.getpid(),
            )
        ),
        flush=True,
    )
    try:
        sys.stdin.buffer.read()
    finally:
        dashboard.close()
        settings_store.close()
        output.close()
        transport.close()
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
