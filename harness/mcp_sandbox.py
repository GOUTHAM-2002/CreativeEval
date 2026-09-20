#!/usr/bin/env python3
"""stdio MCP server `sandbox`: the solver's only channel. Reads EVAL_RUN_DIR / EVAL_TIER / EVAL_PROJECT once,
scrubs its environment, routes every call through harness.tools.Executor (bwrap, host-only log, answer snapshots,
path redaction) and never returns a traceback."""
from __future__ import annotations

import json
import os
import re
import sys
import time
import traceback
from pathlib import Path

RUN_DIR = Path(os.environ["EVAL_RUN_DIR"]).resolve()
TIER = os.environ.get("EVAL_TIER", "default")
PROJECT = Path(os.environ.get("EVAL_PROJECT") or Path(__file__).resolve().parents[1]).resolve()
for k in list(os.environ):
    if re.search(r"KEY|TOKEN|SECRET|ANTHROPIC|OPENROUTER|OPENAI|AWS|GCP|HF_|HUGGING", k, re.I):
        os.environ.pop(k, None)

sys.path.insert(0, str(PROJECT))
from harness import tools  # noqa: E402

SERVER_LOG = RUN_DIR / "mcp_server.log"
EXEC = tools.Executor(RUN_DIR, TIER, PROJECT)
TOOL_LIST = tools.mcp_tool_list()


def slog(msg: str) -> None:
    try:
        with open(SERVER_LOG, "a") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
    except OSError:
        pass


def send(obj) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def handle(msg: dict):
    mid = msg.get("id")
    method = msg.get("method")
    params = msg.get("params") or {}
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": params.get("protocolVersion", "2024-11-05"),
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "sandbox", "version": "1.0.0"}}}
    if method in ("notifications/initialized", "initialized", "notifications/cancelled"):
        return None
    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOL_LIST}}
    if method == "prompts/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"prompts": []}}
    if method == "resources/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"resources": []}}
    if method == "tools/call":
        name = params.get("name")
        if name not in tools.TOOL_NAMES:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": "unknown tool"}}
        try:
            res = EXEC.call(name, params.get("arguments") or {})
        except Exception:  # noqa: BLE001
            slog("tools/call failed:\n" + traceback.format_exc())
            res = {"text": "[sandbox] internal error running tool", "is_error": True}
        return {"jsonrpc": "2.0", "id": mid,
                "result": {"content": [{"type": "text", "text": res["text"]}], "isError": bool(res["is_error"])}}
    if mid is not None:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"method not found: {method}"}}
    return None


def main() -> None:
    slog(f"start tier={TIER} run_dir={RUN_DIR}")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        try:
            resp = handle(msg)
        except Exception:  # noqa: BLE001
            slog("handler failed:\n" + traceback.format_exc())
            resp = {"jsonrpc": "2.0", "id": msg.get("id"), "error": {"code": -32603, "message": "internal error"}}
        if resp is not None:
            send(resp)
    slog("stdin closed")


if __name__ == "__main__":
    main()
