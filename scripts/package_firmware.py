"""Package firmware sources and upstream license texts; never include local credentials."""

import argparse
import hashlib
import json
import subprocess
import tempfile
import zipfile
from pathlib import Path

MICROLINK_COMMIT = "216da3300f0493b0860247d43f7af5ce29df63a5"
LICENSES = {
    "MicroLink/LICENSE": "LICENSE",
    "MicroLink/x25519-license.txt": "x25519-license.txt",
    "wireguard_lwip/LICENSE": "components/microlink/components/wireguard_lwip/LICENSE",
    "wireguard_lwip/x25519-license.txt": "components/microlink/components/wireguard_lwip/src/crypto/refc/x25519-license.txt",
}


def package(root, destination):
    root = Path(root).resolve()
    destination = Path(destination).resolve()
    dependency = root / "firmware/.deps/microlink"
    revision = subprocess.check_output(
        ["git", "-C", str(dependency), "rev-parse", "HEAD"], text=True
    ).strip()
    if revision != MICROLINK_COMMIT:
        raise ValueError(
            "MicroLink revision differs; run firmware/scripts/setup_microlink.sh"
        )
    paths = (
        subprocess.check_output(
            ["git", "-C", str(root), "ls-files", "-z", "firmware", "LICENSE"]
        )
        .decode()
        .split("\0")
    )
    files = {}
    for name in filter(None, paths):
        path = Path(name)
        if (
            path.name == "tailnet_secrets.h"
            or path.suffix in {".bin", ".elf", ".o", ".a"}
            or any(part.startswith(".") for part in path.parts)
        ):
            raise ValueError(f"Unexpected file in firmware sources: {name}")
        source = root / name
        if source.is_symlink():
            raise ValueError(f"Symlink cannot be packaged: {name}")
        files[name] = source.read_bytes()
    for required in [
        "LICENSE",
        "firmware/platformio.ini",
        "firmware/examples/stopwatch/main/main.cpp",
        "firmware/examples/stopwatch/main/tailnet_secrets.example.h",
        "firmware/README.md",
    ]:
        if not files.get(required):
            raise ValueError(f"Missing required source: {required}")
    for name, upstream in LICENSES.items():
        data = (dependency / upstream).read_bytes()
        if not data.strip():
            raise ValueError(f"Empty license: {upstream}")
        files[f"licenses/{name}"] = data
    files["scripts/package_firmware.py"] = Path(__file__).read_bytes()
    files["manifest.json"] = (
        json.dumps(
            {
                "kind": "firmware-source",
                "microlink_commit": revision,
                "sha256": {
                    name: hashlib.sha256(data).hexdigest()
                    for name, data in files.items()
                },
            },
            indent=2,
        ).encode()
        + b"\n"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=destination.parent, suffix=".zip", delete=False
    ) as temp:
        temporary = Path(temp.name)
    try:
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, data in sorted(files.items()):
                info = zipfile.ZipInfo(name)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = (
                    0o100755 if name.endswith(".sh") else 0o100644
                ) << 16
                archive.writestr(info, data)
        with zipfile.ZipFile(temporary) as archive:
            if archive.testzip() is not None:
                raise ValueError("Archive verification failed")
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=Path("dist/xangi-stopwatch-firmware-source.zip")
    )
    args = parser.parse_args()
    print(package(Path(__file__).resolve().parents[1], args.output))


if __name__ == "__main__":
    main()
