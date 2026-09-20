"""claude -p route: Claude Code with --bare, no built-in tools and only the `sandbox` MCP server, launched inside a
mount namespace whose cwd is /work (no host path in its own system prompt; network kept). Parses stream-json into
transcript.jsonl / usage.jsonl, enforces the tool-call and wall caps by killing the process, records invalid markers."""
from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from harness import prices, prompts  # noqa: E402

CLI = os.environ.get("EVAL_CLAUDE_BIN") or shutil.which("claude") or str(Path.home() / ".local/bin/claude")
MCP_SERVER = PROJECT / "harness" / "mcp_sandbox.py"
INVALID_SUBTYPES = ("compact_boundary", "model_fallback", "model_refusal_fallback")
CONTEXT_PAT = re.compile(r"prompt is too long|context_window_exceeded|context window|maximum context|input length.*exceeds", re.I)
CONTENT_FILTER_MARKERS = ("triggered restrictions on violative", "blocked under Anthropic's Usage Policy")
EXPECTED_TOOLS = ("mcp__sandbox__read_file", "mcp__sandbox__grep", "mcp__sandbox__bash", "mcp__sandbox__validate_answer")
GUARD_ENV = {"MAX_MCP_OUTPUT_TOKENS": "200000", "ENABLE_MCP_LARGE_OUTPUT_FILES": "false", "DISABLE_COMPACT": "1",
             "DISABLE_AUTO_COMPACT": "1", "CLAUDE_CODE_MAX_CONTEXT_TOKENS": "1000000", "CLAUDE_CODE_NO_MODEL_FALLBACK": "true",
             "ENABLE_PROMPT_CACHING_1H": "1", "MCP_TOOL_TIMEOUT": "600000", "MCP_TIMEOUT": "120000", "DISABLE_TELEMETRY": "1",
             "DISABLE_ERROR_REPORTING": "1", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"}
POP_ENV = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY", "CLAUDE_CODE_EFFORT_LEVEL")


def _norm(s) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def cc_root_argv(cc_cwd: Path) -> list[str]:
    return ["bwrap", "--die-with-parent",
            "--bind", "/usr", "/usr", "--symlink", "usr/bin", "/bin", "--symlink", "usr/lib", "/lib",
            "--symlink", "usr/lib64", "/lib64", "--symlink", "usr/sbin", "/sbin",
            "--bind", "/etc", "/etc", "--bind", "/home", "/home", "--bind", "/tmp", "/tmp", "--bind", "/var", "/var",
            "--bind", "/run", "/run", "--ro-bind-try", "/opt", "/opt", "--ro-bind-try", "/snap", "/snap",
            "--ro-bind-try", "/sys", "/sys", "--proc", "/proc", "--dev-bind", "/dev", "/dev",
            "--bind", str(cc_cwd), "/work", "--chdir", "/work", "--"]


def build_env(via: str, or_key=None, api_key=None, effort=None) -> dict:
    env = dict(os.environ)
    inherited_api_key = env.get("ANTHROPIC_API_KEY")
    for k in POP_ENV:
        env.pop(k, None)
    env.update(GUARD_ENV)
    if via == "openrouter":
        if not or_key:
            raise RuntimeError("OPENROUTER_API_KEY missing (.env)")
        env["ANTHROPIC_BASE_URL"] = "https://openrouter.ai/api"
        env["ANTHROPIC_AUTH_TOKEN"] = or_key
    elif via == "api":
        key = api_key or inherited_api_key
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY missing (.env)")
        env["ANTHROPIC_API_KEY"] = key
    if effort:
        env["CLAUDE_CODE_EFFORT_LEVEL"] = effort
    return env


def build_cmd(cfg: Path, model_slug: str, max_tool_calls: int, budget_usd: float, via: str, effort, session_id: str) -> list[str]:
    cmd = [CLI, "-p", prompts.KICKOFF, "--model", model_slug]
    if via != "subscription":
        cmd.append("--bare")
    cmd += ["--tools", "", "--strict-mcp-config", "--mcp-config", str(cfg), "--allowedTools", "mcp__sandbox",
            "--permission-mode", "bypassPermissions", "--output-format", "stream-json", "--verbose",
            "--max-turns", str(2 * max_tool_calls), "--max-budget-usd", f"{budget_usd:.2f}",
            "--append-system-prompt", prompts.SYSTEM, "--session-id", session_id]
    if via == "subscription":
        cmd += ["--setting-sources", "", "--disable-slash-commands"]
    if effort:
        cmd += ["--effort", effort]
    return cmd


def _kill_group(proc: subprocess.Popen) -> None:
    for sig, wait in ((signal.SIGTERM, 8), (signal.SIGKILL, 5)):
        if proc.poll() is not None:
            return
        try:
            os.killpg(proc.pid, sig)
        except ProcessLookupError:
            return
        try:
            proc.wait(timeout=wait)
        except subprocess.TimeoutExpired:
            pass


def _blocks_text(c) -> str:
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return "".join(x.get("text", "") if isinstance(x, dict) else str(x) for x in c)
    return "" if c is None else str(c)


def run_cc(run_dir, model_slug: str, tier: str, max_tool_calls: int, wall_s: float, budget_usd: float, via: str = "openrouter",
           effort=None, or_key=None, api_key=None, cmd_override=None) -> dict:
    run_dir = Path(run_dir).resolve()
    t0 = time.time()
    cfg = run_dir / "mcp_config.json"
    cfg.write_text(json.dumps({"mcpServers": {"sandbox": {"type": "stdio", "command": sys.executable, "args": [str(MCP_SERVER)],
                               "env": {"EVAL_RUN_DIR": str(run_dir), "EVAL_TIER": tier, "EVAL_PROJECT": str(PROJECT),
                                       "PYTHONUNBUFFERED": "1", "PATH": "/usr/bin:/bin"}}}}))
    cc_cwd = run_dir / "cc_cwd"
    cc_cwd.mkdir(exist_ok=True)
    session_id = str(uuid.uuid4())
    cmd = cmd_override or (cc_root_argv(cc_cwd) + build_cmd(cfg, model_slug, max_tool_calls, budget_usd, via, effort, session_id))
    env = build_env(via, or_key, api_key, effort) if not cmd_override else {**os.environ, **GUARD_ENV}
    (run_dir / "cc_cmd.json").write_text(json.dumps({"cmd": cmd, "session_id": session_id}, indent=1))
    raw = open(run_dir / "cc_stream.jsonl", "a")
    tr = open(run_dir / "transcript.jsonl", "a")
    stderr_f = open(run_dir / "cc_stderr.txt", "a")
    st = {"i": 0, "n_tool_use": 0, "n_tool_result": 0, "usage": {}, "models": set(), "invalid": [], "result": None,
          "init": None, "last_text": "", "pending": {}, "seen_use": set(), "seen_res": set(), "max_ctx": 0, "harness_fail": None}
    killed = {"reason": None, "detail": ""}
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=stderr_f, text=True, env=env, cwd=str(cc_cwd), start_new_session=True)

    def kill(reason: str, detail: str = "") -> None:
        if killed["reason"] is None:
            killed["reason"], killed["detail"] = reason, detail
        _kill_group(proc)

    def watchdog() -> None:
        while proc.poll() is None:
            if time.time() - t0 > wall_s:
                kill("wall_cap", f"wall {wall_s}s")
                return
            time.sleep(2)
    threading.Thread(target=watchdog, daemon=True).start()

    held = {"row": None}

    def row(r: dict) -> None:
        r["i"] = st["i"]
        r["t"] = round(time.time() - t0, 2)
        tr.write(json.dumps(r, ensure_ascii=False) + "\n")
        tr.flush()
        st["i"] += 1

    def flush_held() -> None:
        if held["row"] is not None:
            row(held["row"])
            held["row"] = None

    row({"role": "user", "text": prompts.KICKOFF, "tool_calls": [], "result_preview": None, "context_tokens": None})
    try:
        for line in proc.stdout:
            raw.write(line)
            raw.flush()
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            typ, sub = ev.get("type"), ev.get("subtype")
            if typ == "system":
                if sub == "init" and st["init"] is None:
                    st["init"] = {k: ev.get(k) for k in ("tools", "mcp_servers", "model", "permissionMode", "claude_code_version", "cwd")}
                    bad = [m for m in (ev.get("mcp_servers") or []) if m.get("status") != "connected"]
                    tools_seen = ev.get("tools") or []
                    missing = [t for t in EXPECTED_TOOLS if t not in tools_seen]
                    extra = [t for t in tools_seen if not t.startswith("mcp__sandbox__")]
                    if bad or missing:
                        st["harness_fail"] = f"mcp not connected: bad={bad} missing={missing}"
                        kill("harness_error", st["harness_fail"])
                        break
                    if extra:
                        st["invalid"].append({"marker": "extra_tools", "tools": extra})
                elif sub in INVALID_SUBTYPES or "fallback" in str(sub) or "compact" in str(sub):
                    st["invalid"].append({"marker": sub, "t": round(time.time() - t0, 1),
                                          "detail": {k: v for k, v in ev.items() if k not in ("type", "subtype")}})
            elif typ == "assistant":
                msg = ev.get("message") or {}
                mid = msg.get("id") or f"noid-{st['i']}"
                if msg.get("model"):
                    st["models"].add(msg["model"])
                u = msg.get("usage") or {}
                if u:
                    cr, cw = int(u.get("cache_read_input_tokens") or 0), int(u.get("cache_creation_input_tokens") or 0)
                    ctx = int(u.get("input_tokens") or 0) + cr + cw
                    st["max_ctx"] = max(st["max_ctx"], ctx)
                    prev = st["usage"].get(mid, {})
                    st["usage"][mid] = {"msg_id": mid, "model": msg.get("model"), "input_tokens": int(u.get("input_tokens") or 0),
                                        "cache_read": cr, "cache_write": cw,
                                        "output_tokens": max(int(u.get("output_tokens") or 0), int(prev.get("output_tokens") or 0)),
                                        "context_tokens": ctx, "t": round(time.time() - t0, 2)}
                texts, calls = [], []
                for b in msg.get("content") or []:
                    if b.get("type") == "text":
                        texts.append(b.get("text", ""))
                    elif b.get("type") == "tool_use":
                        bid = b.get("id")
                        short = (b.get("name") or "").replace("mcp__sandbox__", "")
                        st["pending"][bid] = short
                        calls.append({"id": bid, "name": short, "args": b.get("input") or {}})
                        if bid not in st["seen_use"]:
                            st["seen_use"].add(bid)
                            st["n_tool_use"] += 1
                ctx_now = st["usage"].get(mid, {}).get("context_tokens")
                h = held["row"]
                if h is not None and h.get("msg_id") == mid:
                    h["text"] = "\n".join(t for t in [h["text"], *texts] if t)
                    h["tool_calls"] += calls
                    h["context_tokens"] = ctx_now
                    h["stop_reason"] = msg.get("stop_reason") or h.get("stop_reason")
                else:
                    flush_held()
                    held["row"] = {"role": "assistant", "msg_id": mid, "text": "\n".join(t for t in texts if t), "tool_calls": calls,
                                   "result_preview": None, "context_tokens": ctx_now, "stop_reason": msg.get("stop_reason")}
                if texts:
                    st["last_text"] = "\n".join(texts)
                if st["n_tool_use"] > max_tool_calls:
                    kill("tool_cap", f"{st['n_tool_use']} tool_use blocks > {max_tool_calls}")
                    break
            elif typ == "user":
                flush_held()
                for b in ((ev.get("message") or {}).get("content") or []):
                    if not isinstance(b, dict) or b.get("type") != "tool_result":
                        continue
                    tid = b.get("tool_use_id")
                    text = _blocks_text(b.get("content"))
                    row({"role": "tool", "name": st["pending"].get(tid, "tool"), "tool_use_id": tid, "text": "", "tool_calls": [],
                         "result_preview": text[:600], "is_error": bool(b.get("is_error")), "context_tokens": None})
                    if tid not in st["seen_res"]:
                        st["seen_res"].add(tid)
                        st["n_tool_result"] += 1
                if st["n_tool_result"] >= max_tool_calls:
                    kill("tool_cap", f"{st['n_tool_result']} tool results reached cap {max_tool_calls}")
                    break
            elif typ == "result":
                flush_held()
                st["result"] = {k: ev.get(k) for k in ("subtype", "is_error", "num_turns", "total_cost_usd", "duration_ms", "session_id",
                                                       "usage", "modelUsage", "stop_reason", "permission_denials")}
                st["result"]["result_text"] = (ev.get("result") or "")[:4000]
                st["result"]["errors"] = ev.get("errors")
        try:
            proc.wait(timeout=60)
        except subprocess.TimeoutExpired:
            kill("harness_error", "process did not exit after stream end")
    finally:
        _kill_group(proc)
        flush_held()
        raw.close()
        tr.close()
        stderr_f.close()
    with open(run_dir / "usage.jsonl", "w") as f:
        for n, u in enumerate(st["usage"].values()):
            u["i"] = n
            u["cost_usd"] = prices.estimate_usd(model_slug, u["input_tokens"], u["cache_read"], u["cache_write"], u["output_tokens"])
            f.write(json.dumps(u) + "\n")
    stderr_tail = ""
    try:
        stderr_tail = (run_dir / "cc_stderr.txt").read_text()[-4000:]
    except OSError:
        pass
    res = st["result"] or {}
    text_all = " ".join([res.get("result_text") or "", json.dumps(res.get("errors") or ""), stderr_tail, st["last_text"]])
    filtered = any(m in st["last_text"] for m in CONTENT_FILTER_MARKERS)
    if killed["reason"]:
        end, detail = killed["reason"], killed["detail"]
    elif st["harness_fail"]:
        end, detail = "harness_error", st["harness_fail"]
    elif not res:
        end = "context_limit" if CONTEXT_PAT.search(text_all) else ("content_filter" if filtered else "api_error")
        detail = f"no result event; rc={proc.returncode}; stderr: {stderr_tail[-300:]}"
    else:
        sub = str(res.get("subtype") or "")
        if sub == "success" and not res.get("is_error"):
            end, detail = ("content_filter", "filter marker in final text") if filtered else ("stopped", "model ended its turn")
        elif sub == "error_max_turns":
            end, detail = "tool_cap", f"claude --max-turns backstop ({2 * max_tool_calls})"
        elif "budget" in sub:
            end, detail = "budget_cap", f"claude --max-budget-usd {budget_usd}"
        elif CONTEXT_PAT.search(text_all):
            end, detail = "context_limit", sub
        elif filtered:
            end, detail = "content_filter", sub
        else:
            end, detail = "api_error", f"{sub}: {(res.get('result_text') or '')[:300]}"
    want = _norm(model_slug.split("/")[-1])
    for m in sorted(st["models"]):
        if want not in _norm(m) and _norm(m) not in want:
            st["invalid"].append({"marker": "model_mismatch", "requested": model_slug, "observed": m})
    tot = {k: sum(int(u.get(k) or 0) for u in st["usage"].values()) for k in ("input_tokens", "cache_read", "cache_write", "output_tokens")}
    est = prices.estimate_usd(model_slug, **tot)
    reported = res.get("total_cost_usd")
    return {"route": "cc", "model_id_observed": ",".join(sorted(st["models"])) or None, "end_reason": end, "end_detail": detail,
            "wall_s": round(time.time() - t0, 1), "cost_usd": round(float(reported), 6) if reported is not None else est,
            "cost_source": "claude_result" if reported is not None else "prices_estimate", "cost_estimate_usd": est,
            "invalid_markers": st["invalid"], "session_id": session_id, "system_init": st["init"], "result": res,
            "usage_totals": tot, "max_context_tokens": st["max_ctx"], "n_tool_calls_stream": st["n_tool_result"],
            "n_assistant_messages": len(st["usage"]), "rc": proc.returncode, "via": via, "effort": effort,
            "cc_flags": [c for c in cmd if c.startswith("--")]}
