#!/usr/bin/env python3
"""Read-only dashboard for runs/<tag>/<model>/<inst>: cell grid (pending/running/done), transcript, tool log,
answer_history diffs, score.json. stdlib http.server only; never writes.

  .venv/bin/python dashboard/server.py --port 8895"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
RUNS = PROJECT / "runs"
INDEX = HERE / "index.html"
NAME_RE = re.compile(r"^[A-Za-z0-9._+@-]+$")
RUNNING_WINDOW_S = 900
MAX_ROWS = 5000


def _load(path: Path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _jsonl(path: Path, limit: int = MAX_ROWS) -> list:
    out = []
    try:
        with open(path) as f:
            for line in f:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
                if len(out) >= limit:
                    break
    except OSError:
        pass
    return out


def _ok(name: str) -> bool:
    return bool(name) and NAME_RE.match(name) is not None


def tags() -> list:
    out = []
    if not RUNS.exists():
        return out
    for t in sorted(RUNS.iterdir()):
        if t.is_dir() and _ok(t.name):
            n = sum(1 for m in t.iterdir() if m.is_dir() for c in m.iterdir() if c.is_dir())
            out.append({"name": t.name, "n_cells": n, "ledger": _load(t / "ledger.json")})
    return out


def cell_summary(tag: str, model: str, c: Path) -> dict:
    ep = _load(c / "episode.json")
    meta = _load(c / "run_meta.json") or {}
    log = c / "tool_log.jsonl"
    last = 0.0
    for p in (log, c / "run_meta.json", c / "transcript.jsonl"):
        try:
            last = max(last, p.stat().st_mtime)
        except OSError:
            pass
    age = round(time.time() - last) if last else None
    if ep:
        status = "done"
    elif last and age is not None and age < RUNNING_WINDOW_S:
        status = "running"
    elif last:
        status = "stale"
    else:
        status = "pending"
    n_calls = ep.get("n_tool_calls") if ep else sum(1 for r in _jsonl(log) if r.get("tool") != "snapshot")
    score = _load(c / "score.json") or {}
    measured = score.get("measured") if isinstance(score.get("measured"), dict) else {}
    return {"tag": tag, "model": model, "inst": c.name, "tier": (ep or meta).get("tier"), "status": status, "age_s": age,
            "end_reason": (ep or {}).get("end_reason"), "n_tool_calls": n_calls, "n_validate": (ep or {}).get("n_validate_calls"),
            "cost_usd": (ep or {}).get("cost_usd"), "wall_s": (ep or {}).get("wall_s"), "answer": (ep or {}).get("answer_present"),
            "n_snapshots": len(list((c / "answer_history").glob("*.json"))) if (c / "answer_history").exists() else 0,
            "invalid": len((ep or {}).get("invalid_markers") or []), "aggregate": measured.get("aggregate", score.get("aggregate")),
            "solved": measured.get("solved_all", score.get("solved")), "submission": score.get("submission_status"),
            "started": (ep or meta).get("started")}


def cells(tag: str) -> list:
    root = RUNS / tag
    out = []
    if not root.is_dir():
        return out
    for m in sorted(root.iterdir()):
        if not m.is_dir() or not _ok(m.name):
            continue
        for c in sorted(m.iterdir()):
            if c.is_dir() and _ok(c.name):
                out.append(cell_summary(tag, m.name, c))
    return out


def snapshots(c: Path) -> list:
    hist = c / "answer_history"
    out, prev = [], []
    for p in sorted(hist.glob("[0-9][0-9][0-9][0-9].json")) if hist.exists() else []:
        try:
            raw = p.read_text(errors="replace")
        except OSError:
            continue
        try:
            json.loads(raw)
            valid = True
        except ValueError:
            valid = False
        cur = raw.splitlines()
        diff = "\n".join(difflib.unified_diff(prev, cur, fromfile="previous", tofile=p.name, lineterm="", n=2))
        out.append({"name": p.name, "bytes": len(raw), "valid_json": valid, "diff": diff[:200000], "n_lines": len(cur)})
        prev = cur
    return out


def cell_detail(tag: str, model: str, inst: str) -> dict:
    c = RUNS / tag / model / inst
    if not c.is_dir():
        return {"error": "no such cell"}
    usage = _jsonl(c / "usage.jsonl")
    return {"summary": cell_summary(tag, model, c), "episode": _load(c / "episode.json"), "meta": _load(c / "run_meta.json"),
            "transcript": _jsonl(c / "transcript.jsonl"), "tool_log": _jsonl(c / "tool_log.jsonl"), "snapshots": snapshots(c),
            "score": _load(c / "score.json"), "selftest": (c / "selftest.txt").read_text()[-4000:] if (c / "selftest.txt").exists() else None,
            "usage": {"n": len(usage), "max_context": max([int(u.get("context_tokens") or 0) for u in usage] + [0]),
                      "output_tokens": sum(int(u.get("output_tokens") or 0) for u in usage),
                      "cost_usd": round(sum(float(u.get("cost_usd") or 0) for u in usage), 4), "series": [int(u.get("context_tokens") or 0) for u in usage]},
            "answer": (c / "answer.json").read_text(errors="replace")[:200000] if (c / "answer.json").exists() else None}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _json(self, obj):
        self._send(200, json.dumps(obj, ensure_ascii=False, default=str), "application/json")

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            if u.path in ("/", "/index.html"):
                self._send(200, INDEX.read_text(), "text/html; charset=utf-8")
            elif u.path == "/api/tags":
                self._json({"tags": tags()})
            elif u.path == "/api/cells":
                tag = q.get("tag", "")
                self._json({"cells": cells(tag) if _ok(tag) else [], "t": time.time()})
            elif u.path == "/api/cell":
                tag, model, inst = q.get("tag", ""), q.get("model", ""), q.get("inst", "")
                if not (_ok(tag) and _ok(model) and _ok(inst)):
                    self._send(400, "bad name", "text/plain")
                    return
                self._json(cell_detail(tag, model, inst))
            else:
                self._send(404, "not found", "text/plain")
        except Exception as exc:  # noqa: BLE001
            self._send(500, json.dumps({"error": f"{type(exc).__name__}: {exc}"}), "application/json")


def main():
    global RUNS
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8895)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--runs-root", default=str(RUNS))
    a = ap.parse_args()
    RUNS = Path(a.runs_root).resolve()
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    print(f"eval_imp dashboard on http://{a.host}:{a.port}  runs={RUNS}  (Ctrl-C to stop)", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
