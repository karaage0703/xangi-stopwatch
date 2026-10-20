import json
from unittest.mock import Mock

import pytest

from xangi_stopwatch.dashboard import (
    PROVIDERS,
    Dashboard,
    session_rows,
    usage_pace,
    usage_rows,
)
from xangi_stopwatch.settings import Settings


def test_pace_matches_monitor_and_clamps():
    window = {"resetsAt": 18000, "windowDurationMins": 300}
    assert usage_pace(window, 9000) == 50
    assert usage_pace(window, -10) == 0
    assert usage_pace(window, 19000) == 100
    for bad in ({}, {"resetsAt": 18000}, {"resetsAt": 18000, "windowDurationMins": 0}):
        assert usage_pace(bad, 9000) is None


def usage():
    return {
        "providers": [
            {
                "id": "codex",
                "label": "Codex",
                "groups": [
                    {
                        "id": "codex",
                        "label": "共通枠",
                        "windows": [
                            {
                                "label": "5時間",
                                "usedPercent": 42,
                                "resetsAt": 18000,
                                "windowDurationMins": 300,
                            }
                        ],
                    },
                    {"id": "codex_bengalfox", "windows": [{"usedPercent": 90}]},
                ],
            }
        ]
    }


def test_usage_filters_shared_hidden_group_and_unknown_backend():
    rows = usage_rows(usage(), "codex", 9000)
    assert len(rows) == 1
    assert rows[0]["pace"] == 50 and rows[0]["used"] == 42
    assert rows[0]["reset"] == 150
    assert usage_rows(usage(), "local-llm", 9000) == []
    assert usage_rows(usage(), "all", 9000) == rows
    data = usage()
    data["stale"] = True
    assert usage_rows(data, "all", 9000)[0]["stale"]


def test_monitor_classification_matches_open_and_stateless_rules():
    sessions = [
        {"title": "wait", "lifecycle": "open"},
        {
            "title": "run",
            "lifecycle": "open",
            "isActive": True,
            "activity": {"state": "tool", "elapsedSec": 42},
        },
        {"title": "timer", "lifecycle": "open", "scope": "scheduler"},
        {"title": "hidden", "lifecycle": "open", "sessionMode": "stateless"},
        {"title": "closed", "lifecycle": "closed", "isActive": True},
        {"title": "review", "lifecycle": "open", "agentRunStatus": "failed"},
    ]
    working, running = session_rows(sessions)
    assert [r["name"] for r in working] == ["run", "timer", "wait", "review"]
    assert [r["name"] for r in running] == ["run", "timer"]
    assert running[0]["seconds"] == 42 and running[0]["state"] == "tool実行中"
    assert working[-1]["state"] == "失敗・確認待ち"


def test_collect_paginates_and_tracks_default_without_mutating_backend():
    store = Mock(host_url="http://localhost")
    store.display_get.return_value = {"mode": "single", "backend": "default"}
    dash = Dashboard(Mock(), store)
    calls = []

    def fetch(path):
        calls.append(path)
        if path == "/api/runtime-settings":
            return {"backend": {"value": {"backend": "codex"}}}
        if path == "/api/usage":
            return usage()
        if "offset=0" in path:
            return {
                "sessions": [{"title": "first", "lifecycle": "open"}],
                "meta": {"hasMore": True, "nextOffset": 1},
            }
        return {
            "sessions": [{"title": "second", "lifecycle": "open", "isActive": True}]
        }

    dash.get_json = fetch
    result = dash.collect(9000)
    assert result["backend"] == "codex" and result["usage"][0]["pace"] == 50
    assert result["workingTotal"] == 2 and result["runningTotal"] == 1
    assert not result["tasksError"] and not result["usageError"]
    assert all(path.startswith("/api/") for path in calls)
    dash.get_json = Mock(side_effect=OSError("unavailable"))
    failed = dash.collect(9040)
    assert failed["usageError"] and failed["tasksError"]
    assert failed["usage"][0]["used"] == 42
    assert failed["working"] == []


def test_old_firmware_is_not_sent_new_commands_and_reconnect_rechecks():
    output = Mock()
    output.transport.is_connected = True
    output.transport.generation = 1
    import threading

    output.lock = threading.RLock()
    output.transport.request.return_value = {"device": "stopwatch"}
    dash = Dashboard(output, Mock())
    dash.push()
    dash.push()
    output.transport.request.assert_called_once_with("STATUS")
    output.transport.generation = 2
    output.transport.request.return_value = {"dashboard": True}
    dash.push()
    command, raw = output.transport.request.call_args.args
    assert command == f"DASH:{len(raw)}"
    assert json.loads(raw)["usageError"]


def test_display_save_survives_reload_and_keeps_voice_and_connection(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(Settings, "_start", lambda self: None)
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"peer": "100.64.0.1", "conversation": {"speaker": 4}}))
    store = Settings(Mock(), path, "http://localhost")
    assert store.display_get() == {
        "mode": "single",
        "backend": "default",
        "backends": sorted(PROVIDERS),
    }
    store.display_save({"mode": "multiple", "backend": "codex"})
    reloaded = Settings(Mock(), path, "http://localhost")
    assert reloaded.display_get() == {
        "mode": "multiple",
        "backend": "codex",
        "backends": sorted(PROVIDERS),
    }
    assert reloaded.voice["speaker"] == 4 and reloaded.config["peer"] == "100.64.0.1"
    assert path.stat().st_mode & 0o777 == 0o600
    before = path.read_bytes()
    for bad in (
        {},
        {"mode": "wat", "backend": "codex"},
        {"mode": "single", "backend": "arbitrary"},
    ):
        with pytest.raises(ValueError):
            store.display_save(bad)
    assert path.read_bytes() == before


def test_large_snapshot_is_bounded_and_preserves_total_counts():
    store = Mock()
    store.display_get.return_value = {"mode": "multiple", "backend": "default"}
    dash = Dashboard(Mock(), store)
    many = usage()
    many["providers"][0]["groups"][0]["windows"] *= 100
    sessions = [
        {
            "title": "作業" * 40,
            "lifecycle": "open",
            "isActive": True,
            "activity": {"summary": "検証中" * 40},
        }
        for _ in range(100)
    ]

    def fetch(path):
        if path == "/api/runtime-settings":
            return {"backend": {"value": {"backend": "codex"}}}
        if path == "/api/usage":
            return many
        return {"sessions": sessions}

    dash.get_json = fetch
    snapshot = dash.collect(9000)
    assert (
        snapshot["workingTotal"]
        == snapshot["runningTotal"]
        == snapshot["usageTotal"]
        == 100
    )
    assert (
        len(json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")).encode())
        <= 49152
    )
    assert all(0 < len(snapshot[key]) <= 60 for key in ("usage", "working", "running"))


def test_selected_providers_only_and_copilot_missing_pace():
    data = usage()
    data["providers"].append(
        {
            "id": "github-copilot",
            "label": "GitHub Copilot",
            "groups": [
                {
                    "label": "Premium",
                    "windows": [{"usedPercent": 12, "resetsAt": 18000}],
                }
            ],
        }
    )
    rows = usage_rows(data, ["github-copilot"], 9000)
    assert len(rows) == 1 and rows[0]["name"] == "GitHub Copilot"
    assert rows[0]["pace"] is None
    assert len(usage_rows(data, ["codex", "github-copilot"], 9000)) == 2


def test_backend_multi_selection_persists_and_rejects_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(Settings, "_start", lambda self: None)
    path = tmp_path / "settings.json"
    store = Settings(Mock(), path, "http://localhost")
    selected = ["codex", "github-copilot"]
    store.display_save({"mode": "multiple", "backend": "default", "backends": selected})
    assert (
        Settings(Mock(), path, "http://localhost").display_get()["backends"] == selected
    )
    before = path.read_bytes()
    for bad in [[], ["unknown"], ["codex", "codex"], "codex", [None]]:
        with pytest.raises(ValueError):
            store.display_save(
                {"mode": "multiple", "backend": "default", "backends": bad}
            )
    assert path.read_bytes() == before
    store.display_save({"mode": "single", "backend": "codex"})
    assert store.display_get()["backends"] == selected


@pytest.mark.parametrize("mode", ["single", "multiple"])
def test_selected_backends_persist_in_both_modes(tmp_path, monkeypatch, mode):
    monkeypatch.setattr(Settings, "_start", lambda self: None)
    path = tmp_path / "settings.json"
    store = Settings(Mock(), path, "http://localhost")
    options = {
        "mode": mode,
        "backend": "selected",
        "backends": ["codex", "github-copilot"],
    }
    store.display_save(options)
    assert Settings(Mock(), path, "http://localhost").display_get() == options
    with pytest.raises(ValueError):
        store.display_save({**options, "backends": []})
    assert Settings(Mock(), path, "http://localhost").display_get() == options


def test_water_selection_includes_all_selected_windows_and_excludes_others():
    store = Mock(host_url="http://localhost")
    store.display_get.return_value = {
        "mode": "single",
        "backend": "selected",
        "backends": ["codex", "github-copilot"],
    }
    data = usage()
    for backend in ["github-copilot", "antigravity"]:
        data["providers"].append(
            {
                "id": backend,
                "label": backend,
                "groups": [
                    {
                        "label": "usage",
                        "windows": [{"label": "month", "usedPercent": 12}],
                    }
                ],
            }
        )
    dash = Dashboard(Mock(), store)
    dash.get_json = lambda path: (
        data
        if path == "/api/usage"
        else (
            {"backend": {"value": {"backend": "antigravity"}}}
            if path == "/api/runtime-settings"
            else {"sessions": []}
        )
    )
    result = dash.collect(9000)
    assert result["multiple"] is False
    assert result["usage"] == usage_rows(data, ["codex", "github-copilot"], 9000)
    assert len(result["usage"]) >= 2
    assert not result["usageError"]
