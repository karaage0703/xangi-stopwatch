"""Read-only Monitor projection for the watch; no changes to xangi's backend."""

import json
import math
import os
import threading
import time
import urllib.request

PROVIDERS = {"codex", "claude-code", "github-copilot", "antigravity"}
DEFAULT_DISPLAY = {"mode": "single", "backend": "default"}
MAX_ROWS = 60


def number(value):
    return type(value) in (int, float) and math.isfinite(value)


def usage_pace(window, now):
    """Same formula/seconds epoch as Monitor.tsx usagePacePercent."""
    reset, minutes = window.get("resetsAt"), window.get("windowDurationMins")
    if not number(reset) or not reset or not number(minutes) or minutes <= 0:
        return None
    return min(100, max(0, (now - (reset - minutes * 60)) / (minutes * 60) * 100))


def text(value, limit=32):
    return " ".join(str(value or "").split())[:limit]


def usage_rows(data, backend, now):
    rows = []
    for provider in data.get("providers", []):
        if (isinstance(backend, list) and provider.get("id") not in backend) or (
            isinstance(backend, str)
            and backend != "all"
            and provider.get("id") != backend
        ):
            continue
        for group in provider.get("groups", []):
            if group.get("id") == "codex_bengalfox":
                continue
            for window in group.get("windows", []):
                used = window.get("usedPercent")
                if not number(used):
                    continue
                reset = window.get("resetsAt")
                rows.append(
                    {
                        "name": text(provider.get("label", provider.get("id")), 24),
                        "detail": text(
                            f"{group.get('label', '')} {window.get('label', '')}", 32
                        ),
                        "used": min(100, max(0, used)),
                        "pace": usage_pace(window, now),
                        "reset": max(0, math.ceil((reset - now) / 60))
                        if number(reset)
                        else -1,
                        "stale": bool(
                            data.get("stale")
                            or provider.get("sourceType") == "snapshot"
                        ),
                    }
                )
    return rows


def session_rows(sessions):
    working, running = [], []
    for session in sessions:
        active = session.get("isActive") is True or (
            session.get("scope") == "scheduler" and session.get("lifecycle") == "open"
        )
        if session.get("lifecycle") != "open" or (
            session.get("scope") != "scheduler"
            and not active
            and session.get("sessionMode") == "stateless"
        ):
            continue
        activity = session.get("activity") or {}
        state = activity.get("state")
        status = (
            {"tool": "tool実行中", "streaming": "応答中", "thinking": "考え中"}.get(
                state, "実行中"
            )
            if active
            else {"succeeded": "結果確認待ち", "failed": "失敗・確認待ち"}.get(
                session.get("agentRunStatus"),
                {"error": "エラー", "aborted": "中断"}.get(state, "入力待ち"),
            )
        )
        step = next(
            (
                p.get("step")
                for p in (session.get("progressCard") or {}).get("plan", [])
                if p.get("status") == "in_progress"
            ),
            "",
        )
        elapsed = activity.get("elapsedSec")
        row = {
            "name": text(
                session.get("title") or activity.get("threadLabel") or "無題の会話", 32
            ),
            "detail": text(activity.get("summary") or step or status, 40),
            "state": status,
            "active": active,
            "seconds": int(elapsed)
            if number(elapsed) and elapsed >= 0 and active
            else -1,
        }
        working.append(row)
        if active:
            running.append(row)
    working.sort(key=lambda row: not row["active"])
    return working, running


class Dashboard:
    def __init__(self, output, store):
        self.output, self.store = output, store
        self.closed = threading.Event()
        self.wake = threading.Event()
        self.thread = None
        self.snapshot = {
            "usage": [],
            "working": [],
            "running": [],
            "usageError": True,
            "tasksError": True,
        }
        self.error = None
        self.usage = {}
        self.default_backend = ""
        self.usage_at = 0
        self.generation = -1
        self.supported = False

    def start(self):
        self.thread = threading.Thread(
            target=self._run, daemon=True, name="watch-dashboard"
        )
        self.thread.start()

    def get_json(self, path):
        if self.closed.is_set():
            raise OSError("dashboard closed")
        headers = {}
        token = os.environ.get("XANGI_TOKEN", "")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = urllib.request.Request(
            self.store.host_url.rstrip("/") + path, headers=headers
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            raw = response.read(4_000_001)
        if len(raw) > 4_000_000:
            raise ValueError("dashboard response too large")
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("invalid dashboard response")
        return data

    def collect(self, now):
        errors = []
        usage_error = self.snapshot.get("usageError", True)
        if now - self.usage_at >= 30:
            self.usage_at = now
            try:
                runtime = self.get_json("/api/runtime-settings")
                self.default_backend = runtime["backend"]["value"]["backend"]
                self.usage = self.get_json("/api/usage")
                usage_error = False
            except (OSError, ValueError, KeyError, TypeError) as exc:
                usage_error = True
                errors.append(type(exc).__name__ + ": usage unavailable")
        options = self.store.display_get()
        backend = options["backend"]
        if backend == "default":
            backend = self.default_backend
        rows = usage_rows(
            self.usage,
            options.get("backends", sorted(PROVIDERS))
            if options["mode"] == "multiple" or backend == "selected"
            else backend,
            now,
        )
        tasks_error = False
        try:
            sessions, offset = [], 0
            for _ in range(100):
                data = self.get_json(
                    f"/api/sessions?lifecycle=open&limit=100&offset={offset}"
                )
                sessions.extend(data.get("sessions", []))
                meta = data.get("meta") or {}
                if not meta.get("hasMore"):
                    break
                following = meta.get("nextOffset")
                if type(following) is not int or following <= offset:
                    raise ValueError("invalid sessions cursor")
                offset = following
            else:
                raise ValueError("sessions pagination limit reached")
            working, running = session_rows(sessions)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            tasks_error = True
            errors.append(type(exc).__name__ + ": tasks unavailable")
            working, running = [], []
        self.error = "; ".join(errors) or ("usage unavailable" if usage_error else None)
        self.snapshot = {
            "backend": text(
                "選択したバックエンド"
                if backend == "selected"
                else backend or "未取得",
                24,
            ),
            "multiple": options["mode"] == "multiple",
            "usage": rows[:MAX_ROWS],
            "usageTotal": len(rows),
            "working": working[:MAX_ROWS],
            "workingTotal": len(working),
            "running": running[:MAX_ROWS],
            "runningTotal": len(running),
            "usageError": usage_error,
            "tasksError": tasks_error,
        }
        while (
            len(
                json.dumps(
                    self.snapshot, ensure_ascii=False, separators=(",", ":")
                ).encode()
            )
            > 49152
        ):
            longest = max(
                ("usage", "working", "running"), key=lambda key: len(self.snapshot[key])
            )
            self.snapshot[longest].pop()
        return self.snapshot

    def push(self):
        transport = self.output.transport
        with self.output.lock:
            if not transport.is_connected:
                return
            if self.generation != transport.generation:
                status = transport.request("STATUS")
                self.supported = status.get("dashboard") is True
                self.generation = transport.generation
            if not self.supported:
                return
            payload = json.dumps(
                self.snapshot, ensure_ascii=False, separators=(",", ":")
            ).encode()
            if len(payload) > 49152:
                raise ValueError("dashboard packet too large")
            transport.request(f"DASH:{len(payload)}", payload)

    def _run(self):
        while not self.closed.is_set():
            try:
                if self.output.transport.is_connected:
                    self.collect(time.time())
                    if not self.closed.is_set():
                        self.push()
            except Exception as exc:
                self.error = type(exc).__name__ + ": dashboard unavailable"
            self.wake.wait(5)
            self.wake.clear()

    def close(self):
        self.closed.set()
        self.wake.set()
        if self.thread:
            self.thread.join(timeout=0.5)
