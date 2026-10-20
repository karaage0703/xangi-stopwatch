"""Single-device USB or reverse TCP connection; commands and binary transfers are atomic."""

import json
import logging
import os
import queue
import shutil
import socket
import subprocess
import threading
import time

import serial

from . import constants


class Transport:
    def __init__(self):
        self.lock = threading.RLock()
        self.connection = None
        self.responses = queue.Queue()
        self.generation = 0
        self.user_stopped = False
        self.character_next = threading.Event()
        self.conversation_stop = threading.Event()
        self.closed = threading.Event()
        self.listener = None

    @property
    def is_connected(self):
        return self.connection is not None

    def _attach(self, connection):
        with self.lock:
            if self.closed.is_set() or self.connection is not None:
                connection.close()
                return
            self.responses = queue.Queue()
            self.connection = connection
            self.character_next.clear()
            self.conversation_stop.clear()
            self.generation += 1
            self.user_stopped = False
            threading.Thread(
                target=self._reader, args=(connection, self.responses), daemon=True
            ).start()

    def _drop(self, connection):
        # Reader must be able to wake a request holding self.lock.
        if self.connection is connection:
            self.connection = None
        try:
            connection.close()
        except OSError:
            pass

    def _reader(self, connection, responses):
        buffer = bytearray()
        try:
            while not self.closed.is_set():
                try:
                    data = (
                        connection.recv(constants.TCP_CHUNK_BYTES)
                        if isinstance(connection, socket.socket)
                        else connection.read(1)
                    )
                except socket.timeout:
                    continue
                if not data:
                    if isinstance(connection, socket.socket):
                        break
                    continue
                buffer.extend(data)
                if len(buffer) > constants.MAX_REPLY_BYTES:
                    raise OSError("device reply too large")
                while b"\n" in buffer:
                    line, _, rest = buffer.partition(b"\n")
                    buffer = bytearray(rest)
                    try:
                        result = json.loads(line)
                    except (ValueError, UnicodeError):
                        continue  # boot logs are not protocol replies
                    if not isinstance(result, dict):
                        continue
                    if "event" in result:
                        if result["event"] == "conversation_stop":
                            self.conversation_stop.set()
                            self.user_stopped = True
                        if result["event"] == "audio_stopped":
                            self.user_stopped = True
                        elif result["event"] == "character_next":
                            self.character_next.set()
                    else:
                        responses.put(result)
        except (OSError, serial.SerialException):
            pass
        finally:
            self._drop(connection)
            responses.put({"status": "error", "error": "device disconnected"})

    def start_usb(self, port):
        def loop():
            while not self.closed.is_set():
                if not self.is_connected:
                    try:
                        self._attach(
                            serial.Serial(
                                port,
                                constants.USB_BAUD_RATE,
                                timeout=constants.USB_READ_TIMEOUT_SECONDS,
                                write_timeout=constants.USB_WRITE_TIMEOUT_SECONDS,
                                exclusive=True,
                            )
                        )
                    except (OSError, serial.SerialException):
                        pass
                self.closed.wait(constants.USB_RECONNECT_SECONDS)

        threading.Thread(target=loop, daemon=True).start()

    def start_tcp(self, bind, port, peer):
        listener = socket.socket()
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((bind, port))
        listener.listen(2)
        listener.settimeout(constants.TCP_ACCEPT_TIMEOUT_SECONDS)
        self.listener = listener

        def loop():
            while not self.closed.is_set():
                try:
                    conn, addr = listener.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break
                if addr[0] != peer:
                    conn.close()
                    continue
                conn.settimeout(constants.TCP_READ_TIMEOUT_SECONDS)
                conn.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                self._attach(conn)

        threading.Thread(target=loop, daemon=True).start()
        if os.environ.get("XANGI_STOPWATCH_PEER_DISCOVERY") == "1":
            threading.Thread(
                target=self._discover_peer, args=(peer,), daemon=True
            ).start()

    def _discover_peer(self, peer):
        """Wake the peer's Tailscale path while reverse TCP is disconnected.

        MicroLink can wait for a peer-initiated handshake after a cold boot.
        Discovery runs separately from accept() and never substitutes for TCP
        or WireGuard authentication. No probes are sent while connected.
        """
        executable = shutil.which("tailscale")
        if executable is None:
            logging.getLogger(__name__).warning(
                "tailscale CLI missing; automatic peer discovery is unavailable"
            )
            return
        while not self.closed.is_set():
            if not self.is_connected:
                try:
                    subprocess.run(
                        [executable, "ping", "--c", "1", "--timeout", "3s", peer],
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=5,
                        check=False,
                    )
                except (OSError, subprocess.TimeoutExpired):
                    logging.getLogger(__name__).debug(
                        "Peer discovery failed", exc_info=True
                    )
            self.closed.wait(10)

    def _write(self, connection, data):
        if isinstance(connection, socket.socket):
            connection.sendall(data)
        else:
            if connection.write(data) != len(data):
                raise OSError("short USB write")

    def request(self, command, data=None):
        with self.lock:
            connection = self.connection
            if connection is None:
                raise RuntimeError("StopWatch not connected")
            while not self.responses.empty():
                self.responses.get_nowait()
            try:
                self._write(connection, (command + "\n").encode())
                result = self.responses.get(timeout=constants.COMMAND_TIMEOUT_SECONDS)
                if data is not None:
                    if result.get("status") != "ready":
                        raise RuntimeError(
                            result.get("error", "device did not accept transfer")
                        )
                    chunk_size = (
                        constants.TCP_CHUNK_BYTES
                        if isinstance(connection, socket.socket)
                        else constants.USB_CHUNK_BYTES
                    )
                    for offset in range(0, len(data), chunk_size):
                        self._write(connection, data[offset : offset + chunk_size])
                        if not isinstance(connection, socket.socket):
                            # USB CDC baud is advisory: pace bursts so the ESP32
                            # can drain its receive queue while running M5 tasks.
                            time.sleep(constants.USB_CHUNK_INTERVAL_SECONDS)
                    result = self.responses.get(
                        timeout=constants.COMMAND_TIMEOUT_SECONDS
                    )
                if "error" in result or (
                    command != "STATUS" and result.get("status") != "ok"
                ):
                    raise RuntimeError(result.get("error", "invalid device reply"))
                return result
            except (OSError, serial.SerialException, queue.Empty) as exc:
                self._drop(connection)
                raise RuntimeError("StopWatch communication failed; reconnect") from exc

    def close(self):
        self.closed.set()
        if self.listener:
            self.listener.close()
        if self.connection:
            self._drop(self.connection)
