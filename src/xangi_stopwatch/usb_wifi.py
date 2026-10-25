"""Serve the self-contained USB setup page on the user's PC (no credentials API)."""

import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path


def setup_html():
    return Path(__file__).with_name("usb_wifi.html").read_bytes()


def create_setup_server():
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            if self.path != "/":
                self.send_error(404)
                return
            body = setup_html()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

    return HTTPServer(("127.0.0.1", 0), Handler)


def main():
    with create_setup_server() as server:
        url = f"http://127.0.0.1:{server.server_port}/"
        print(
            f"StopWatchをこのPCにUSB接続し、Chrome・Edgeで開いてください: {url}",
            flush=True,
        )
        print("終了: Ctrl+C。Wi-Fi情報はサーバーへ送信しません。", flush=True)
        webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
