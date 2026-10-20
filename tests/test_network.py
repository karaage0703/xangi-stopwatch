import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from xangi_stopwatch.network import Network


@pytest.fixture
def network():
    output = SimpleNamespace(lock=threading.RLock(), transport=Mock())
    settings = SimpleNamespace(
        lock=threading.RLock(), conversation=Mock(busy=False, state="idle")
    )
    return Network(output, settings)


def test_network_list_returns_only_ssid_and_metadata(network):
    network.output.transport.request.return_value = {
        "active": 0,
        "profiles": [
            {
                "id": 0,
                "ssid_hex": "家のWiFi".encode().hex(),
                "built_in": True,
                "password": "must-not-return",
            }
        ],
    }
    assert network.get() == {
        "active": 0,
        "profiles": [{"id": 0, "ssid": "家のWiFi", "built_in": True}],
    }


def test_add_encodes_credentials_without_changing_selected_profile(network):
    assert network.save(
        {"action": "add", "ssid": "SSID,\n名", "password": "a,\nsecret"}
    ) == {"status": "ok", "reconnecting": False}
    command = network.output.transport.request.call_args.args[0]
    assert (
        command
        == "WIFI_ADD:" + "SSID,\n名".encode().hex() + "," + "a,\nsecret".encode().hex()
    )
    assert "\n" not in command
    assert "secret" not in command
    network.output.transport.request.assert_called_once()


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {"action": "select", "id": True},
        {"action": "select", "id": 5},
        {"action": "delete", "id": -1},
        {"action": "add", "ssid": "", "password": "12345678"},
        {"action": "add", "ssid": "あ" * 11, "password": "12345678"},
        {"action": "add", "ssid": "x", "password": "short"},
        {"action": "add", "ssid": "x", "password": "x" * 64},
        {"action": "add", "ssid": "x\0y", "password": "12345678"},
        {"action": "unknown"},
    ],
)
def test_invalid_input_never_reaches_device(network, payload):
    with pytest.raises(ValueError):
        network.save(payload)
    network.output.transport.request.assert_not_called()


def test_select_has_no_fallback_command(network):
    assert network.save({"action": "select", "id": 2})["reconnecting"]
    network.output.transport.request.assert_called_once_with("WIFI_SELECT:2")


def test_busy_conversation_rejects_wifi_switch(network):
    network.settings.conversation.state = "recording"
    with pytest.raises(RuntimeError):
        network.save({"action": "select", "id": 2})
    network.output.transport.request.assert_not_called()


def test_device_failure_is_not_treated_as_success(network):
    network.output.transport.request.side_effect = RuntimeError("save failed")
    with pytest.raises(RuntimeError, match="save failed"):
        network.save({"action": "select", "id": 2})
