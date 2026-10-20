import http.client
import json
import threading

import pytest

from xangi_stopwatch.extension import configure, create_server
from xangi_stopwatch.output import Output
from xangi_stopwatch.transport import Transport


def test_http_auth_limits_and_routes():
    transport = Transport()
    output = Output(transport)
    server = create_server(output, "secret")
    threading.Thread(target=server.serve_forever, daemon=True).start()

    def request(method, path, body=None, headers=None):
        client = http.client.HTTPConnection("127.0.0.1", server.server_port)
        client.request(method, path, body, headers or {})
        response = client.getresponse()
        result = response.status, json.loads(response.read())
        client.close()
        return result

    auth = {"Authorization": "Bearer secret", "Content-Type": "application/json"}
    try:
        assert request("GET", "/api/health")[0] == 401
        assert request("GET", "/api/health", headers=auth)[1]["connected"] is False
        assert request("POST", "/api/avatar/acquire", "{}", auth)[0] == 404
        assert request("POST", "/api/avatar/unknown", "{}", auth)[0] == 404
        assert (
            request(
                "POST",
                "/api/settings",
                headers={**auth, "Content-Length": "900001"},
            )[0]
            == 413
        )
    finally:
        server.shutdown()
        server.server_close()
        output.close()
        transport.close()


def test_config_does_not_autodetect_usb_or_bind_all_interfaces(tmp_path):
    transport = Transport()
    path = tmp_path / "config.json"
    assert configure(transport, path) == "unconfigured"
    for config in [
        dict(transport="usb"),
        dict(transport="other"),
        dict(transport="tailnet", bind="0.0.0.0", peer="100.64.0.2"),
    ]:
        path.write_text(json.dumps(config))
        with pytest.raises(ValueError):
            configure(transport, path)


def test_volume_settings_auth_validation_and_device_errors():
    class Device:
        def __init__(self):
            self.volume = 25
            self.position = "right"
            self.connected = True

        def request(self, command):
            if not self.connected:
                raise RuntimeError("disconnected")
            if command.startswith("VOLUME:"):
                self.volume = int(command.split(":")[1])
            if command.startswith("BATTERY_POSITION:"):
                self.position = command.split(":")[1]
            return {
                "volume": self.volume,
                "battery_position": self.position,
                "status": "ok",
            }

    device = Device()
    server = create_server(Output(device), "secret")
    threading.Thread(target=server.serve_forever, daemon=True).start()

    def request(method, data=None, auth=True):
        headers = {"Content-Type": "application/json"}
        if auth:
            headers["Authorization"] = "Bearer secret"
        client = http.client.HTTPConnection("127.0.0.1", server.server_port)
        client.request(
            method,
            "/api/settings",
            json.dumps(data) if data is not None else None,
            headers,
        )
        response = client.getresponse()
        result = response.status, json.loads(response.read())
        client.close()
        return result

    try:
        assert request("POST", {"volume": 255}, auth=False)[0] == 401
        assert device.volume == 25
        for invalid in [True, -1, 256, "25", 2.5, None]:
            assert request("POST", {"volume": invalid})[0] == 400
        assert device.volume == 25
        assert request("POST", {"volume": 0}) == (200, {"volume": 0})
        assert request("GET")[1]["volume"] == 0
        for position in ("right", "left", "center", "hidden"):
            assert request("POST", {"batteryPosition": position}) == (
                200,
                {"batteryPosition": position},
            )
            assert request("GET")[1]["batteryPosition"] == position
        for invalid in ("bottom", None, [], True):
            assert request("POST", {"batteryPosition": invalid, "volume": 12})[0] == 400
            assert device.volume == 0
        assert request("POST", {"batteryPosition": "left"}, auth=False)[0] == 401
        device.connected = False
        assert request("GET")[0] == 503
        assert request("POST", {"volume": 10})[0] != 200
    finally:
        server.shutdown()
        server.server_close()
