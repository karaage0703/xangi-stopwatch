"""Read images inside the selected Agent's workspace, without conversation."""

import base64
import io
import logging
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageOps

FACE_PATHS = {name: f"assets/xangi-avatar/{name}.png" for name in ("closed", "open")}

MAX_IMAGE_BYTES = 20 * 1024 * 1024
FORMATS = {
    ".png": "PNG",
    ".jpg": "JPEG",
    ".jpeg": "JPEG",
    ".webp": "WEBP",
    ".gif": "GIF",
}


def workspace_image(root, relative):
    if (
        not isinstance(relative, str)
        or not relative.strip()
        or Path(relative).is_absolute()
    ):
        raise ValueError("Agentのワークスペース相対パスを指定してください")
    root = Path(root).resolve(strict=True)
    try:
        path = (root / relative).resolve(strict=True)
    except OSError as exc:
        raise ValueError("画像が見つかりません: " + relative) from exc
    if not path.is_relative_to(root) or path == root:
        raise ValueError("ワークスペース外の画像は指定できません")
    if path.suffix.lower() not in FORMATS or not path.is_file():
        raise ValueError("PNG / JPEG / WebP / GIF画像を指定してください")
    with path.open("rb") as stream:
        data = stream.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError("画像は20MB以下にしてください")
    try:
        with Image.open(io.BytesIO(data)) as source:
            if (
                source.format != FORMATS[path.suffix.lower()]
                or source.width * source.height > 16_000_000
            ):
                raise ValueError("画像形式またはサイズが不正です")
            image = ImageOps.pad(
                source.convert("RGBA"), (466, 466), color=(0, 0, 0, 255)
            ).convert("RGB")
            output = io.BytesIO()
            image.save(output, "JPEG", quality=85)
    except (OSError, Image.DecompressionBombError) as exc:
        raise ValueError("画像を読み込めません") from exc
    return base64.b64encode(output.getvalue()).decode()


@lru_cache(maxsize=1)
def default_faces():
    root = Path(__file__).parent / "assets"
    return {
        name: workspace_image(root, f"avatar-{name}.png") for name in ("closed", "open")
    }


def load_faces(service, config, *, include_status=False):
    def get(path):
        import json

        with service.request(service.host_url + path, None) as response:
            return json.loads(response.read(4_000_000))

    agent = next(
        (
            a
            for a in get("/api/agents").get("agents", [])
            if a["id"] == config["agent_id"]
        ),
        None,
    )
    if agent is None:
        raise ValueError("選択したAgentが見つかりません")
    workspace_id = agent.get("workspaceId") or "default"
    workspace = next(
        (
            w
            for w in get("/api/workspaces").get("workspaces", [])
            if str(w["id"]) == workspace_id
        ),
        None,
    )
    if not workspace or not workspace.get("path"):
        raise ValueError("Agentのワークスペースが見つかりません")
    fallback = False
    try:
        images = {
            name: workspace_image(
                workspace["path"], config.get("image_" + name, FACE_PATHS[name])
            )
            for name in ("closed", "open")
        }
    except (ValueError, OSError):
        logging.getLogger(__name__).warning(
            "Agent avatar unavailable; using bundled xangi avatar"
        )
        # Keep both mouth states together rather than mixing two characters.
        images = dict(default_faces())
        fallback = True
    return {**images, "fallback": fallback} if include_status else images
