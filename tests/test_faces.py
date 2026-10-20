import base64
import io
import json
from unittest.mock import Mock

import pytest
from PIL import Image

from xangi_stopwatch.faces import load_faces, workspace_image


def test_workspace_image_converts_for_device(tmp_path):
    Image.new("RGB", (100, 200), "red").save(tmp_path / "face.png")
    data = workspace_image(tmp_path, "face.png")
    with Image.open(io.BytesIO(base64.b64decode(data))) as image:
        assert image.size == (466, 466)
        assert image.format == "JPEG"


def test_workspace_escape_and_fake_image_rejected(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    Image.new("RGB", (20, 20)).save(tmp_path / "outside.png")
    (root / "link.png").symlink_to(tmp_path / "outside.png")
    (root / "fake.png").write_text("not an image")
    for path in (
        "../outside.png",
        "link.png",
        "fake.png",
        "missing.png",
        str(tmp_path / "outside.png"),
    ):
        with pytest.raises(ValueError):
            workspace_image(root, path)


def test_faces_resolve_selected_agent_workspace(tmp_path):
    (tmp_path / "assets/xangi-avatar").mkdir(parents=True)
    Image.new("RGB", (20, 20)).save(tmp_path / "custom-closed.png")
    Image.new("RGB", (20, 20)).save(tmp_path / "custom-open.png")

    def request(url, body):
        value = (
            {"agents": [{"id": "chosen", "workspaceId": "other"}]}
            if url.endswith("/agents")
            else {
                "workspaces": [
                    {"id": "default", "path": "/missing"},
                    {"id": "other", "path": str(tmp_path)},
                ]
            }
        )
        return io.BytesIO(json.dumps(value).encode())

    service = Mock(host_url="http://localhost", request=request)
    result = load_faces(
        service,
        {
            "agent_id": "chosen",
            "image_closed": "custom-closed.png",
            "image_open": "custom-open.png",
        },
    )
    assert result["closed"] == workspace_image(tmp_path, "custom-closed.png")
    assert set(result) == {"open", "closed"}
    assert (
        load_faces(
            service,
            {
                "agent_id": "chosen",
                "image_closed": "custom-closed.png",
                "image_open": "custom-open.png",
            },
            include_status=True,
        )["fallback"]
        is False
    )


@pytest.mark.parametrize("available", [(), ("closed",), ("closed", "open")])
def test_missing_or_corrupt_avatar_uses_bundled_pair(tmp_path, available):
    from xangi_stopwatch.faces import default_faces

    folder = tmp_path / "assets/xangi-avatar"
    folder.mkdir(parents=True)
    for name in available:
        Image.new("RGB", (20, 20), "red").save(folder / f"{name}.png")
    if len(available) == 2:
        (folder / "open.png").write_text("broken image")

    def request(url, body):
        value = (
            {"agents": [{"id": "chosen", "workspaceId": "workspace"}]}
            if url.endswith("/agents")
            else {"workspaces": [{"id": "workspace", "path": str(tmp_path)}]}
        )
        return io.BytesIO(json.dumps(value).encode())

    result = load_faces(
        Mock(host_url="http://localhost", request=request), {"agent_id": "chosen"}
    )
    assert result == default_faces()
    assert (
        load_faces(
            Mock(host_url="http://localhost", request=request),
            {"agent_id": "chosen"},
            include_status=True,
        )["fallback"]
        is True
    )
    assert result["closed"] != result["open"]
    for data in result.values():
        raw = base64.b64decode(data)
        assert len(raw) < 100_000
        with Image.open(io.BytesIO(raw)) as image:
            assert image.size == (466, 466)
            assert image.format == "JPEG"


def test_missing_agent_is_not_hidden_by_avatar_fallback():
    service = Mock(
        host_url="http://localhost", request=lambda *args: io.BytesIO(b'{"agents":[]}')
    )
    with pytest.raises(ValueError, match="Agent"):
        load_faces(service, {"agent_id": "missing"})
