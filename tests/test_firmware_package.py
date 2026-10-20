import importlib.util
import json
import zipfile
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "package_firmware", Path(__file__).parents[1] / "scripts/package_firmware.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


@pytest.fixture
def source(tmp_path, monkeypatch):
    names = [
        "LICENSE",
        "firmware/platformio.ini",
        "firmware/README.md",
        "firmware/examples/stopwatch/main/main.cpp",
        "firmware/examples/stopwatch/main/tailnet_secrets.example.h",
    ]
    for name in names:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("sample source")
    for name in MODULE.LICENSES.values():
        path = tmp_path / "firmware/.deps/microlink" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("original license text")

    def git(args, **kwargs):
        return (
            MODULE.MICROLINK_COMMIT
            if "rev-parse" in args
            else ("\0".join(names) + "\0").encode()
        )

    monkeypatch.setattr(MODULE.subprocess, "check_output", git)
    return tmp_path, names


def test_sources_licenses_and_manifest_without_untracked_credentials(source):
    root, _ = source
    (root / "firmware/examples/stopwatch/main/tailnet_secrets.h").write_text("secret")
    archive_path = MODULE.package(root, root / "release.zip")
    with zipfile.ZipFile(archive_path) as archive:
        assert len([n for n in archive.namelist() if n.startswith("licenses/")]) == 4
        assert not any(n.endswith("tailnet_secrets.h") for n in archive.namelist())
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["kind"] == "firmware-source"
        assert "LICENSE" in manifest["sha256"]


@pytest.mark.parametrize(
    "name",
    ["firmware/examples/stopwatch/main/tailnet_secrets.h", "firmware/firmware.bin"],
)
def test_reject_tracked_secrets_or_binaries(source, name):
    root, names = source
    names.append(name)
    with pytest.raises(ValueError, match="Unexpected"):
        MODULE.package(root, root / "release.zip")
    assert not (root / "release.zip").exists()


def test_missing_license_does_not_replace_existing_output(source):
    root, _ = source
    (root / "firmware/.deps/microlink/LICENSE").unlink()
    output = root / "release.zip"
    output.write_bytes(b"previous archive")
    with pytest.raises(FileNotFoundError):
        MODULE.package(root, output)
    assert output.read_bytes() == b"previous archive"
