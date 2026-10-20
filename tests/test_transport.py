import json
import socket
import threading
import time

import pytest

from xangi_stopwatch.transport import Transport


def test_tcp_binary_ack_events_and_disconnect():
    transport = Transport()
    host, peer = socket.socketpair()
    transport._attach(host)
    seen = []

    def device():
        with peer, peer.makefile("rb") as stream:
            seen.append(stream.readline())
            peer.sendall(b'{"status":"ready"}\n')
            seen.append(stream.read(4))
            peer.sendall(b'{"status":"ok"}\n')
            seen.append(stream.readline())
            peer.sendall(b'{"event":"audio_stopped"}\n')
            peer.sendall(
                json.dumps(dict(device="stopwatch", playing=False, queued=0)).encode()
                + b"\n"
            )

    task = threading.Thread(target=device)
    task.start()
    assert transport.request("WAV:4", b"abcd")["status"] == "ok"
    assert transport.request("STATUS")["playing"] is False
    task.join(2)
    assert not task.is_alive()
    assert seen == [b"WAV:4\n", b"abcd", b"STATUS\n"]
    assert transport.user_stopped
    until = time.monotonic() + 1
    while transport.is_connected and time.monotonic() < until:
        time.sleep(0.01)
    assert not transport.is_connected
    with pytest.raises(RuntimeError, match="not connected"):
        transport.request("STATUS")
    transport.close()


def test_peer_filter_and_reconnect_generation():
    transport = Transport()
    transport.start_tcp("127.0.0.1", 0, "127.0.0.2")
    client = socket.create_connection(transport.listener.getsockname())
    client.settimeout(2)
    assert client.recv(1) == b""
    assert not transport.is_connected
    client.close()
    transport.close()


def test_reader_idle_timeout_does_not_disconnect():
    transport = Transport()
    host, peer = socket.socketpair()
    host.settimeout(0.01)
    transport._attach(host)
    time.sleep(0.05)
    assert transport.is_connected
    peer.close()
    transport.close()


def test_character_button_event_is_not_a_response_or_audio_stop():
    transport = Transport()
    host, peer = socket.socketpair()
    transport._attach(host)

    def device():
        with peer.makefile("rb") as stream:
            assert stream.readline() == b"STATUS\n"
            peer.sendall(b'{"event":"character_next"}\n{"status":"ok"}\n')

    task = threading.Thread(target=device)
    task.start()
    assert transport.request("STATUS")["status"] == "ok"
    assert transport.character_next.is_set()
    assert not transport.user_stopped
    task.join(2)
    peer.close()
    transport.close()


def test_discovery_only_when_disconnected_and_stops(monkeypatch):
    transport = Transport()
    calls = []
    monkeypatch.setattr(
        "xangi_stopwatch.transport.shutil.which", lambda _: "/bin/tailscale"
    )
    monkeypatch.setattr(
        "xangi_stopwatch.transport.subprocess.run",
        lambda *a, **kw: calls.append((a, kw)),
    )
    waits = []

    def wait(seconds):
        waits.append(seconds)
        if len(waits) == 1:
            transport.connection = object()
        elif len(waits) == 2:
            transport.connection = None
        else:
            transport.closed.set()

    monkeypatch.setattr(transport.closed, "wait", wait)
    transport._discover_peer("100.64.0.2")
    assert (
        len(calls) == 2
    )  # Initial boot and later disconnect; connected cycle skipped.
    assert calls[0][0][0] == [
        "/bin/tailscale",
        "ping",
        "--c",
        "1",
        "--timeout",
        "3s",
        "100.64.0.2",
    ]
    assert calls[0][1]["timeout"] == 5
    assert waits == [10, 10, 10]


def test_discovery_timeout_does_not_stop_retries(monkeypatch):
    import subprocess

    transport = Transport()
    monkeypatch.setattr(
        "xangi_stopwatch.transport.shutil.which", lambda _: "/bin/tailscale"
    )
    calls = []

    def run(*args, **kwargs):
        calls.append(args)
        if len(calls) == 1:
            raise subprocess.TimeoutExpired(args[0], 5)
        transport.closed.set()

    monkeypatch.setattr("xangi_stopwatch.transport.subprocess.run", run)
    monkeypatch.setattr(transport.closed, "wait", lambda _: None)
    transport._discover_peer("100.64.0.2")
    assert len(calls) == 2


def test_discovery_missing_cli_warns_without_crash(monkeypatch, caplog):
    monkeypatch.setattr("xangi_stopwatch.transport.shutil.which", lambda _: None)
    Transport()._discover_peer("100.64.0.2")
    assert "automatic peer discovery is unavailable" in caplog.text


@pytest.mark.parametrize("enabled", [False, True])
def test_tcp_discovery_is_explicit_opt_in(monkeypatch, enabled):
    monkeypatch.delenv("XANGI_STOPWATCH_PEER_DISCOVERY", raising=False)
    if enabled:
        monkeypatch.setenv("XANGI_STOPWATCH_PEER_DISCOVERY", "1")
    calls = []

    class Thread:
        def __init__(self, *, target, args=(), daemon=False):
            calls.append(target)

        def start(self):
            pass

    monkeypatch.setattr("xangi_stopwatch.transport.threading.Thread", Thread)
    transport = Transport()
    try:
        transport.start_tcp("127.0.0.1", 0, "127.0.0.2")
        assert (transport._discover_peer in calls) is enabled
    finally:
        transport.close()


def test_conversation_stop_event_survives_audio_flag_reset():
    transport = Transport()
    host, peer = socket.socketpair()
    transport._attach(host)
    try:
        peer.sendall(b'{"event":"conversation_stop"}\n')
        assert transport.conversation_stop.wait(1)
        transport.user_stopped = False  # Output cleanup must not lose cancellation.
        assert transport.conversation_stop.is_set()
        assert not transport.character_next.is_set()
        assert transport.responses.empty()
    finally:
        peer.close()
        transport.close()
