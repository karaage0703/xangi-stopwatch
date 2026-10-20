import json
import os
import subprocess
import sys
import urllib.request


def test_managed_ready_health_and_stdin_shutdown(tmp_path):
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "xangi_stopwatch.extension",
            "serve",
            "--workspace",
            str(tmp_path),
            "--config",
            str(tmp_path / "absent.json"),
        ],
        env={**os.environ, "XANGI_EXTENSION_AUTH_TOKEN": "test-token"},
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        ready = json.loads(process.stdout.readline())
        assert ready["event"] == "ready" and ready["id"] == "xangi-stopwatch"
        request = urllib.request.Request(
            ready["baseUrl"] + "/api/health",
            headers={"Authorization": "Bearer test-token"},
        )
        with urllib.request.urlopen(request, timeout=3) as response:
            health = json.load(response)
        assert health["configuration"] == "unconfigured"
        assert health["connected"] is False
        _, error = process.communicate(timeout=5)
        assert process.returncode == 0, error
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
