import http.client
import threading

from xangi_stopwatch.usb_wifi import create_setup_server


def test_local_setup_serves_html_but_has_no_credentials_endpoint():
    server = create_setup_server()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        assert server.server_address[0] == "127.0.0.1"
        client = http.client.HTTPConnection(*server.server_address)
        client.request("GET", "/")
        response = client.getresponse()
        assert response.status == 200
        assert response.getheader("Cache-Control") == "no-store"
        assert b"navigator.serial.requestPort" in response.read()
        client.request("POST", "/", b"must-not-store")
        response = client.getresponse()
        assert response.status == 501
        response.read()
        client.request("GET", "/../pyproject.toml")
        response = client.getresponse()
        assert response.status == 404
        response.read()
        client.close()
    finally:
        server.shutdown()
        server.server_close()


def test_extension_download_requires_auth_and_works_without_device():
    from types import SimpleNamespace

    from xangi_stopwatch.extension import create_server

    server = create_server(SimpleNamespace(), "test-token")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        client = http.client.HTTPConnection(*server.server_address)
        client.request("GET", "/api/wifi-setup")
        response = client.getresponse()
        assert response.status == 401
        response.read()
        client.request(
            "GET", "/api/wifi-setup", headers={"Authorization": "Bearer test-token"}
        )
        response = client.getresponse()
        assert response.status == 200
        assert (
            response.getheader("Content-Disposition")
            == 'attachment; filename="stopwatch-wifi.html"'
        )
        assert b"navigator.serial.requestPort" in response.read()
        client.close()
    finally:
        server.shutdown()
        server.server_close()
