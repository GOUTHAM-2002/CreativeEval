"""OpenRouter chat.completions route: same tools (executed directly through harness.tools.Executor, not MCP), same
prompts, one nudge at most, per-turn usage/cost, retries with backoff, messages.json persisted for resume.
TODO: a /v1/responses variant for reasoning continuity (see sandbox_exit/harness/run_openai.py)."""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from harness import prices, prompts  # noqa: E402
from harness.tools import Executor, openai_tool_list  # noqa: E402

URL = os.environ.get("EVAL_OR_URL") or "https://openrouter.ai/api/v1/chat/completions"
CONTEXT_PAT = re.compile(r"context length|context_length|maximum context|too many tokens|prompt is too long|input length|exceeds the model", re.I)
RETRY_STATUS = (408, 409, 425, 429, 500, 502, 503, 504)
MAX_TOKENS = int(os.environ.get("EVAL_OR_MAX_TOKENS", "16000"))
DEGENERATE_RETRIES = 3


def _norm(s) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def _atomic(path: Path, obj) -> None:
    tmp = str(path) + ".tmp"
    Path(tmp).write_text(json.dumps(obj, ensure_ascii=False))
    os.replace(tmp, path)


def post(key: str, body: dict, timeout: float = 900, retries: int = 6):
    data = json.dumps(body).encode()
    backoff = 5.0
    last = None
    for attempt in range(retries):
        req = urllib.request.Request(URL, data=data, method="POST", headers={
            "Authorization": f"Bearer {key}", "Content-Type": "application/json",
            "HTTP-Referer": "https://localhost/eval_imp", "X-Title": "eval_imp"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                out = json.loads(r.read())
            err = out.get("error") if isinstance(out, dict) else None
            if err:
                code = int((err.get("code") if isinstance(err, dict) else 0) or 0)
                last = {"status": code, "body": json.dumps(err)[:2000]}
                if code in RETRY_STATUS:
                    raise urllib.error.URLError(f"retryable api error {code}")
                return None, last
            return out, None
        except urllib.error.HTTPError as e:
            try:
                txt = e.read().decode("utf-8", "replace")[:2000]
            except Exception:  # noqa: BLE001
                txt = ""
            last = {"status": e.code, "body": txt}
            if e.code not in RETRY_STATUS:
                return None, last
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
            last = last if last and last.get("status") in RETRY_STATUS else {"status": 0, "body": repr(e)[:500]}
        if attempt < retries - 1:
            time.sleep(backoff)
            backoff = min(backoff * 2, 60)
    return None, {"status": (last or {}).get("status", 0), "body": f"failed after {retries} attempts: {(last or {}).get('body', '')}"}


def classify_error(err: dict) -> tuple[str, str]:
    body = (err or {}).get("body", "") or ""
    status = (err or {}).get("status")
    if CONTEXT_PAT.search(body):
        return "context_limit", f"{status}: {body[:300]}"
    low = body.lower()
    if '"refusal"' in low or "_policy" in low or "content_filter" in low or "moderation" in low or status == 403:
        return "content_filter", f"{status}: {body[:300]}"
    return "api_error", f"{status}: {body[:300]}"


def run_or(run_dir, model_slug: str, tier: str, max_tool_calls: int, wall_s: float, budget_usd: float, effort=None,
           or_key=None, max_tokens: int = MAX_TOKENS, **_) -> dict:
    if not or_key:
        raise RuntimeError("OPENROUTER_API_KEY missing (.env)")
    run_dir = Path(run_dir).resolve()
    t0 = time.time()
    ex = Executor(run_dir, tier)
    tools = openai_tool_list()
    msgs_path, state_path = run_dir / "messages.json", run_dir / "or_state.json"
    state = {"nudged": False, "cost": 0.0, "turns": 0, "i": 0, "invalid": [], "models": [], "max_ctx": 0, "ended": False, "wall_prev": 0.0}
    if msgs_path.exists() and state_path.exists():
        messages = json.loads(msgs_path.read_text())
        state.update(json.loads(state_path.read_text()))
        state["ended"] = False
    else:
        messages = [{"role": "system", "content": prompts.SYSTEM}, {"role": "user", "content": prompts.KICKOFF}]
        _atomic(msgs_path, messages)
    tr = open(run_dir / "transcript.jsonl", "a")
    us = open(run_dir / "usage.jsonl", "a")

    def row(r: dict) -> None:
        r["i"] = state["i"]
        r["t"] = round(state["wall_prev"] + time.time() - t0, 2)
        tr.write(json.dumps(r, ensure_ascii=False) + "\n")
        tr.flush()
        state["i"] += 1

    def persist() -> None:
        _atomic(msgs_path, messages)
        _atomic(state_path, state)

    if state["turns"] == 0:
        row({"role": "user", "text": prompts.KICKOFF, "tool_calls": [], "result_preview": None, "context_tokens": None})
    end, detail = "stopped", ""
    degenerate = 0
    try:
        while True:
            if state["wall_prev"] + time.time() - t0 > wall_s:
                end, detail = "wall_cap", f"wall {wall_s}s"
                break
            if state["cost"] >= budget_usd:
                end, detail = "budget_cap", f"cost {state['cost']:.2f} >= {budget_usd}"
                break
            if ex.n_calls >= max_tool_calls:
                end, detail = "tool_cap", f"{ex.n_calls} tool calls"
                break
            body = {"model": model_slug, "messages": messages, "tools": tools, "tool_choice": "auto",
                    "usage": {"include": True}, "max_tokens": max_tokens}
            if effort:
                body["reasoning"] = {"effort": effort}
            resp, err = post(or_key, body)
            if resp is None:
                end, detail = classify_error(err)
                state["invalid"].append({"marker": "api_error", "detail": detail})
                break
            state["turns"] += 1
            u = resp.get("usage") or {}
            cost = float(u.get("cost") or (u.get("cost_details") or {}).get("upstream_inference_cost") or 0.0)
            state["cost"] = round(state["cost"] + cost, 6)
            ctx = int(u.get("prompt_tokens") or 0)
            state["max_ctx"] = max(state["max_ctx"], ctx)
            model_seen = resp.get("model")
            if model_seen and model_seen not in state["models"]:
                state["models"].append(model_seen)
            choice = (resp.get("choices") or [{}])[0]
            msg = choice.get("message") or {}
            finish = choice.get("finish_reason")
            calls = msg.get("tool_calls") or []
            us.write(json.dumps({"i": state["i"], "input_tokens": ctx, "cache_read": int((u.get("prompt_tokens_details") or {}).get("cached_tokens") or 0),
                                 "cache_write": 0, "output_tokens": int(u.get("completion_tokens") or 0),
                                 "reasoning_tokens": int((u.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0),
                                 "context_tokens": ctx, "cost_usd": cost, "model": model_seen, "finish_reason": finish,
                                 "t": round(state["wall_prev"] + time.time() - t0, 2)}) + "\n")
            us.flush()
            parsed = []
            for c in calls:
                fn = c.get("function") or {}
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except ValueError:
                    args = {"_invalid_json": (fn.get("arguments") or "")[:200]}
                parsed.append({"id": c.get("id"), "name": fn.get("name"), "args": args})
            row({"role": "assistant", "text": msg.get("content") or "", "tool_calls": parsed, "result_preview": None,
                 "context_tokens": ctx, "reasoning": (msg.get("reasoning") or "")[:4000], "finish_reason": finish})
            am = {"role": "assistant", "content": msg.get("content") or ""}
            if calls:
                am["tool_calls"] = calls
            if msg.get("reasoning_details"):
                am["reasoning_details"] = msg["reasoning_details"]
            messages.append(am)
            if finish == "content_filter":
                end, detail = "content_filter", "finish_reason=content_filter"
                persist()
                break
            if not calls and not (msg.get("content") or "").strip() and finish != "stop":
                degenerate += 1
                if degenerate >= DEGENERATE_RETRIES:
                    end, detail = "api_error", f"{degenerate} empty responses (finish_reason={finish})"
                    persist()
                    break
                persist()
                time.sleep(3)
                continue
            degenerate = 0
            if calls:
                for c in parsed:
                    if ex.n_calls >= max_tool_calls:
                        text = "[sandbox] tool call limit reached"
                        is_err = True
                    elif "_invalid_json" in c["args"]:
                        text, is_err = "[sandbox] tool arguments were not valid JSON", True
                    else:
                        r = ex.call(c["name"], c["args"])
                        text, is_err = r["text"], r["is_error"]
                    row({"role": "tool", "name": c["name"], "tool_use_id": c["id"], "text": "", "tool_calls": [],
                         "result_preview": text[:600], "is_error": is_err, "context_tokens": None})
                    messages.append({"role": "tool", "tool_call_id": c["id"], "content": text})
                persist()
                continue
            status = ex.answer_status()
            if status["schema_valid"]:
                end, detail = "stopped", "no tool call; answer.json schema-valid"
                persist()
                break
            if state["nudged"]:
                end, detail = "stopped", "no tool call after nudge"
                persist()
                break
            state["nudged"] = True
            messages.append({"role": "user", "content": prompts.NUDGE})
            row({"role": "user", "text": prompts.NUDGE, "tool_calls": [], "result_preview": None, "context_tokens": None, "nudge": True})
            persist()
    finally:
        state["ended"] = True
        state["wall_prev"] = round(state["wall_prev"] + time.time() - t0, 1)
        persist()
        tr.close()
        us.close()
    want = _norm(model_slug.split("/")[-1])
    for m in state["models"]:
        if want not in _norm(m) and _norm(m) not in want:
            state["invalid"].append({"marker": "model_mismatch", "requested": model_slug, "observed": m})
    tot = {"input_tokens": 0, "cache_read": 0, "cache_write": 0, "output_tokens": 0}
    try:
        for line in (run_dir / "usage.jsonl").read_text().splitlines():
            r = json.loads(line)
            for k in tot:
                tot[k] += int(r.get(k) or 0)
    except (OSError, ValueError):
        pass
    est = prices.estimate_usd(model_slug, **tot)
    return {"route": "or", "model_id_observed": ",".join(state["models"]) or None, "end_reason": end, "end_detail": detail,
            "wall_s": state["wall_prev"], "cost_usd": round(state["cost"], 6), "cost_source": "openrouter_usage",
            "cost_estimate_usd": est, "invalid_markers": state["invalid"], "usage_totals": tot, "max_context_tokens": state["max_ctx"],
            "n_tool_calls_stream": ex.n_calls, "n_assistant_messages": state["turns"], "nudged": state["nudged"], "effort": effort}
