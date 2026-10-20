import base64
import io
import time
import uuid
import wave

import pytest
from PIL import Image

from xangi_stopwatch.output import Output


class Device:
    generation = 1
    is_connected = True
    user_stopped = False

    def __init__(self):
        self.commands = []
        self.status = dict(device="stopwatch", playing=False, queued=0)
        self.fail = None

    def request(self, command, data=None):
        self.commands.append((command, data))
        if command == self.fail:
            raise RuntimeError("disconnected")
        if command == "STATUS":
            return dict(self.status)
        return dict(status="ok", audio_stopped=True)


def image(size=(466, 466)):
    buf = io.BytesIO()
    Image.new("RGB", size).save(buf, format="JPEG")
    return base64.b64encode(buf.getvalue()).decode()


def wav(rate=8000, channels=1):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as f:
        f.setnchannels(channels)
        f.setsampwidth(2)
        f.setframerate(rate)
        f.writeframes(b"\0" * 1600 * channels)
    return base64.b64encode(buf.getvalue()).decode()


@pytest.fixture
def setup():
    device = Device()
    output = Output(device)
    owner = str(uuid.uuid4())

    def call(action, **payload):
        return output.request(action, dict(owner=owner, **payload))

    yield device, output, owner, call
    output.close()


def frames(call):
    call("images", closed=image(), open=image())


def test_profile_and_exclusive_owner(setup):
    device, output, owner, call = setup
    assert call("acquire")["device"] == "stopwatch"
    assert call("acquire")["width"] == 466
    with pytest.raises(RuntimeError, match="another conversation"):
        output.request("acquire", {"owner": str(uuid.uuid4())})
    call("release")
    assert output.owner is None
    with pytest.raises(RuntimeError, match="expired"):
        call("renew")


def test_reject_other_device_before_stopping_it(setup):
    device, output, _, call = setup
    device.status["device"] = "cores3"
    with pytest.raises(RuntimeError, match="firmware required"):
        call("acquire")
    assert output.owner is None
    assert [c for c, _ in device.commands] == ["STATUS"]


def test_queue_completion_requires_duration_and_empty_device(setup):
    device, output, _, call = setup
    call("acquire")
    frames(call)
    first = call("enqueue", wav=wav())
    second = call("enqueue", wav=wav())
    with pytest.raises(RuntimeError, match="queue is full"):
        call("enqueue", wav=wav())
    output._poll()
    assert call("status", jobId=first["id"])["job"]["state"] == "playing"
    for item in output.pending:
        item["end"] = time.monotonic() - 1
    device.status.update(playing=True, queued=0)
    output._poll()
    assert call("status", jobId=first["id"])["job"]["state"] == "done"
    assert call("status", jobId=second["id"])["job"]["state"] == "playing"
    device.status["playing"] = False
    output._poll()
    assert call("status", jobId=second["id"])["job"]["state"] == "done"


def test_button_stop_cancels_and_blocks_next_upload_until_explicit_stop(setup):
    device, output, _, call = setup
    call("acquire")
    frames(call)
    job = call("enqueue", wav=wav())
    device.user_stopped = True
    output._poll()
    assert call("status", jobId=job["id"])["job"]["state"] == "cancelled"
    with pytest.raises(RuntimeError, match="stopped"):
        call("enqueue", wav=wav())
    call("stop")
    assert call("enqueue", wav=wav())["state"] == "playing"


def test_expired_owner_stopped_and_reconnect_requires_acquire(setup):
    device, output, _, call = setup
    call("acquire")
    frames(call)
    call("enqueue", wav=wav())
    output.deadline = 0
    with pytest.raises(RuntimeError, match="expired"):
        call("renew")
    assert not output.pending and output.owner is None
    assert any(c == "AUDIO_STOP" for c, _ in device.commands)
    call("acquire")
    before = len(device.commands)
    device.generation += 1
    with pytest.raises(RuntimeError, match="expired"):
        call("status")
    assert len(device.commands) == before, "old session must not stop new device"


def test_watcher_expires_idle_session(setup):
    _, output, _, call = setup
    call("acquire")
    output.deadline = 0
    output.start()
    until = time.monotonic() + 2
    while output.owner and time.monotonic() < until:
        time.sleep(0.01)
    assert output.owner is None


@pytest.mark.parametrize(
    "value",
    ["", "%%%", base64.b64encode(b"bad wav").decode(), wav(rate=4000), wav(channels=2)],
)
def test_invalid_audio_rejected_before_transfer(setup, value):
    device, _, _, call = setup
    call("acquire")
    frames(call)
    before = len(device.commands)
    with pytest.raises(ValueError):
        call("enqueue", wav=value)
    assert len(device.commands) == before


def test_wrong_size_image_and_active_image_replacement_rejected(setup):
    _, _, _, call = setup
    call("acquire")
    with pytest.raises(ValueError, match="466x466"):
        call("images", closed=image((320, 240)), open=image())
    frames(call)
    call("enqueue", wav=wav())
    with pytest.raises(RuntimeError, match="stop playback"):
        frames(call)


def test_release_clears_owner_even_when_device_fails(setup):
    device, output, _, call = setup
    call("acquire")
    frames(call)
    call("enqueue", wav=wav())
    device.fail = "AUDIO_STOP"
    with pytest.raises(RuntimeError):
        call("release")
    assert output.owner is None and not output.pending


@pytest.mark.parametrize("payload", [None, [], {}, {"owner": []}, {"owner": "invalid"}])
def test_invalid_payload(setup, payload):
    _, output, _, _ = setup
    with pytest.raises(ValueError):
        output.request("acquire", payload)
