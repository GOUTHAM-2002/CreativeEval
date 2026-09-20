"""LLM writer for human documents (INTERFACE_v2 §5).

Turns a per-document FACT SHEET into a realistic document written by a writer model, then verifies the factual
content mechanically (verbatim sentences exactly once, no forbidden strings, length) and with a checker model
(missing / contradicted facts, invented graded specifics). Up to MAX_ATTEMPTS writer calls with the failures fed
back as corrections; then the sheet's ``fallback`` template is used and ``rendered_by`` is ``template``.

Only the standard library is used. The OpenRouter client is a callable ``(model, messages, temperature, max_tokens)``
returning ``(text, usage)``; tests inject a stub returning a plain ``str``.

Sheet keys (see ``REQUIRED_KEYS`` / ``OPTIONAL_KEYS`` for the exact list the code reads).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROMPTS = ROOT / "gen" / "prompts"
OR_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_WRITER = "anthropic/claude-sonnet-5"
DEFAULT_CHECKER = "anthropic/claude-haiku-4.5"
DEFAULT_CAP_USD = 8.0
MAX_ATTEMPTS = 3
MAX_TOKENS = 2500
WRITER_TEMPERATURE = 0.7
CHECKER_TEMPERATURE = 0.0
LENGTH_SLACK = 0.40                     # ±40% of the sheet's word range
CHAT_WINDOW_MIN = 20                    # required_text must land within ±20 min of the seed time
CHAT_COUNT_DEFAULT = (8, 40)
GRADED_KINDS = {"time", "date", "zone", "lot", "name"}   # invented specifics of these kinds fail verification
TEXT_KINDS = ("statement", "ticket", "email", "report", "memo")

# Keys the code reads. Text kinds: everything under "text"; chat days: everything under "chat".
REQUIRED_KEYS = {
    "text": ["doc_id", "path", "kind", "author", "length_words", "must_include", "verbatim", "must_not_mention",
             "forbidden_strings", "style_notes", "fallback"],
    "chat": ["doc_id", "kind", "date", "messages_seed", "bot_posts", "allowed_users", "must_not_mention",
             "forbidden_strings", "fallback"],
}
OPTIONAL_KEYS = {
    "text": ["audience", "may_mention", "allowed_entities", "header"],
    "chat": ["path", "channels", "n_messages", "verbatim", "personas", "window", "must_include", "may_mention",
             "allowed_entities", "style_notes"],
}

_LOG_LOCK = threading.Lock()
_ENV_CACHE: dict | None = None


# ---------------------------------------------------------------- env / logging
def load_env(path: Path | None = None) -> dict:
    """Tiny .env loader (KEY=VALUE lines, '#' comments, optional quotes). Does not touch os.environ."""
    global _ENV_CACHE
    p = Path(path) if path else ROOT / ".env"
    if path is None and _ENV_CACHE is not None:
        return _ENV_CACHE
    vals = {}
    if p.exists():
        for line in p.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            if k.startswith("export "):
                k = k[7:].strip()
            vals[k] = v.strip().strip('"').strip("'")
    if path is None:
        _ENV_CACHE = vals
    return vals


def _env(key: str, default=None):
    v = os.environ.get(key)
    if v is None or v == "":
        v = load_env().get(key)
    return v if v not in (None, "") else default


def _log(log_path, record: dict):
    if not log_path:
        return
    record = dict(record)
    record.setdefault("t", dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"))
    line = json.dumps(record, ensure_ascii=False, default=str)
    with _LOG_LOCK:
        p = Path(log_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(line + "\n")


# ---------------------------------------------------------------- cost budget
class Budget:
    """Thread-safe cost accumulator with a hard cap (USD). ``exhausted`` once spent >= cap."""

    def __init__(self, cap_usd: float | None = None):
        self.cap = float(cap_usd if cap_usd is not None else _env("EVAL_DOCS_CAP_USD", DEFAULT_CAP_USD))
        self.spent = 0.0
        self.calls = 0
        self._lock = threading.Lock()

    def add(self, cost) -> None:
        with self._lock:
            self.spent += float(cost or 0.0)
            self.calls += 1

    @property
    def exhausted(self) -> bool:
        return self.spent >= self.cap

    def snapshot(self) -> dict:
        return {"spent_usd": round(self.spent, 6), "cap_usd": self.cap, "calls": self.calls}


# ---------------------------------------------------------------- OpenRouter client (urllib only)
class OpenRouterClient:
    """Callable ``(model, messages, temperature, max_tokens) -> (text, usage)``; retries with backoff on 429/5xx."""

    def __init__(self, api_key: str | None = None, url: str = OR_URL, timeout: int = 180, max_retries: int = 5,
                 backoff_s: float = 2.0, referer: str = "https://eval-imp.example", title: str = "eval_imp docs_llm"):
        self.api_key = api_key or _env("OPENROUTER_API_KEY")
        if not self.api_key:
            raise RuntimeError("OPENROUTER_API_KEY not set (environment or .env)")
        self.url, self.timeout, self.max_retries, self.backoff_s = url, timeout, max_retries, backoff_s
        self.headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json",
                        "HTTP-Referer": referer, "X-Title": title}

    def __call__(self, model, messages, temperature, max_tokens):
        body = {"model": model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens,
                "usage": {"include": True}}
        data = json.dumps(body).encode()
        last = None
        for attempt in range(self.max_retries):
            if attempt:
                time.sleep(self.backoff_s * (2 ** (attempt - 1)))
            req = urllib.request.Request(self.url, data=data, headers=self.headers)
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    resp = json.load(r)
            except urllib.error.HTTPError as e:
                detail = ""
                try:
                    detail = e.read().decode("utf-8", "replace")[:300]
                except Exception:
                    pass
                if e.code == 429 or e.code >= 500:
                    last = f"HTTP {e.code}: {detail}"
                    continue
                raise RuntimeError(f"OpenRouter HTTP {e.code}: {detail}")
            except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
                last = repr(e)[:300]
                continue
            if not resp.get("choices"):
                last = f"response without choices: {json.dumps(resp)[:300]}"
                continue
            choice = resp["choices"][0]
            msg = choice.get("message") or {}
            text = msg.get("content") or ""
            if isinstance(text, list):
                text = "".join(part.get("text", "") for part in text if isinstance(part, dict))
            u = resp.get("usage") or {}
            usage = {"cost": float(u.get("cost") or 0.0), "prompt_tokens": u.get("prompt_tokens"),
                     "completion_tokens": u.get("completion_tokens"), "model": resp.get("model"),
                     "finish_reason": choice.get("finish_reason"), "id": resp.get("id")}
            return text, usage
        raise RuntimeError(f"OpenRouter call failed after {self.max_retries} tries: {last}")


def _invoke(client, model, messages, temperature, max_tokens):
    """Normalise a client result to (text, usage)."""
    r = client(model, messages, temperature, max_tokens)
    if isinstance(r, tuple):
        text, usage = r[0], (r[1] or {})
    else:
        text, usage = r, {}
    return (text or ""), dict(usage)


# ---------------------------------------------------------------- helpers
def _word_count(text: str) -> int:
    return len(re.findall(r"\S+", text or ""))


def _clean_output(text: str) -> str:
    t = (text or "").strip()
    if t.startswith("```"):
        lines = t.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        t = "\n".join(lines).strip()
    return t


def _extract_json(text: str, opener: str):
    """Parse the first JSON value of the given opener ('{' or '[') found in text (tolerates fences / prose)."""
    closer = "}" if opener == "{" else "]"
    t = _clean_output(text)
    try:
        return json.loads(t)
    except Exception:
        pass
    i, j = t.find(opener), t.rfind(closer)
    if i < 0 or j <= i:
        raise ValueError("no JSON value found in output")
    return json.loads(t[i:j + 1])


def _parse_iso(s: str) -> dt.datetime:
    d = dt.datetime.fromisoformat(str(s).strip().replace("Z", "+00:00"))
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone.utc)
    return d


def _prompt_for(kind: str) -> str:
    p = PROMPTS / f"writer_{kind}.txt"
    if not p.exists():
        p = PROMPTS / "writer_generic.txt"
    return p.read_text(encoding="utf-8")


def _with_header(header, body: str) -> str:
    body = (body or "").strip()
    if header:
        return header.rstrip("\n") + "\n\n" + body + "\n"
    return body + "\n"


def _spans(sheet: dict, text: str) -> dict:
    out = {}
    for v in sheet.get("verbatim") or []:
        vt = v["text"]
        i = text.find(vt)
        out[v["claim_id"]] = [i, i + len(vt)] if i >= 0 else None
    return out


def _forbidden_hits(sheet: dict, text: str) -> list:
    low = (text or "").lower()
    hits = []
    for item in list(sheet.get("must_not_mention") or []) + list(sheet.get("forbidden_strings") or []):
        if item and item.lower() in low:
            hits.append(item)
    return hits


def _chat_claims(sheet: dict) -> list:
    """Graded verbatim claims of a chat day: sheet-level ``verbatim`` plus seeds carrying claim_id + required_text."""
    seen, out = set(), []
    for v in sheet.get("verbatim") or []:
        if v.get("claim_id") and v.get("text") and v["claim_id"] not in seen:
            seen.add(v["claim_id"])
            out.append({"claim_id": v["claim_id"], "text": v["text"]})
    for s in sheet.get("messages_seed") or []:
        if s.get("claim_id") and s.get("required_text") and s["claim_id"] not in seen:
            seen.add(s["claim_id"])
            out.append({"claim_id": s["claim_id"], "text": s["required_text"]})
    return out


# ---------------------------------------------------------------- briefs (user messages)
def _brief_text(sheet: dict) -> str:
    a = sheet.get("author") or {}
    lo, hi = sheet.get("length_words") or [150, 400]
    L = [f"KIND: {sheet.get('kind', 'document')}",
         f"AUTHOR: {a.get('name', '?')} (handle {a.get('handle', '?')}); role: {a.get('role', '?')}; timezone: {a.get('tz', '?')}"]
    if a.get("persona"):
        L.append(f"PERSONA: {a['persona']}")
    if sheet.get("audience"):
        L.append(f"AUDIENCE: {sheet['audience']}")
    L.append(f"LENGTH: {lo}-{hi} words")
    L.append(f"STYLE: {sheet.get('style_notes') or 'natural, in the author’s own voice'}")
    if sheet.get("header"):
        L.append("HEADER (added separately by the editor; do not write it yourself):\n" + sheet["header"].rstrip())
    L += ["", "FACTS TO INCLUDE (every one; paraphrase allowed, values exact):"]
    for f in sheet.get("must_include") or []:
        L.append(f"- [{f.get('fact_id', '?')}] {f['text']}")
    L += ["", "SENTENCES TO INCLUDE VERBATIM (each exactly once, character for character):"]
    for v in sheet.get("verbatim") or []:
        L.append(f"- {v['text']}")
    if not sheet.get("verbatim"):
        L.append("- (none)")
    if sheet.get("may_mention"):
        L += ["", "MAY MENTION (optional colour; use some if it feels natural):"]
        L += [f"- {m}" for m in sheet["may_mention"]]
    if sheet.get("allowed_entities"):
        L += ["", "KNOWN NAMES AND IDS you may use besides those in the facts: " + ", ".join(sheet["allowed_entities"])]
    if sheet.get("must_not_mention"):
        L += ["", "NEVER MENTION (not even indirectly):"]
        L += [f"- {m}" for m in sheet["must_not_mention"]]
    if sheet.get("forbidden_strings"):
        L += ["", "FORBIDDEN STRINGS (never use, not even inside another word): " + ", ".join(f'"{s}"' for s in sheet["forbidden_strings"])]
    L += ["", "Write the document now. Output only the document text."]
    return "\n".join(L)


def _brief_chat(sheet: dict) -> str:
    seeds = sheet.get("messages_seed") or []
    bots = sheet.get("bot_posts") or []
    users = _chat_allowed_users(sheet)
    bot_users = {b.get("user") or "alerting-bot" for b in bots}
    personas = sheet.get("personas") or {}
    nmin, nmax = sheet.get("n_messages") or CHAT_COUNT_DEFAULT
    L = [f"DATE: {sheet.get('date', '?')}"]
    if sheet.get("window"):
        L.append(f"WINDOW: {sheet['window'][0]} to {sheet['window'][1]}")
    if sheet.get("style_notes"):
        L.append(f"STYLE: {sheet['style_notes']}")
    L += ["", "PARTICIPANTS (handle: persona):"]
    for u in sorted(users - bot_users):
        L.append(f"- {u}: {personas.get(u, 'staff member')}")
    for u in sorted(bot_users):
        L.append(f"- {u}: automated alerting bot (only the BOT POSTS below; do not write new bot messages)")
    L += ["", "CHANNELS: " + ", ".join(sorted(_chat_allowed_channels(sheet)))]
    L.append(f"MESSAGE COUNT: {nmin}-{nmax} messages in total (including bot posts)")
    L += ["", "EVENTS (one message each, from that user in that channel, within 20 minutes of the time):"]
    for s in seeds:
        line = f"- {s.get('t_iso')} | {s.get('user')} | {s.get('channel')} | gist: {s.get('gist', '')}"
        if s.get("required_text"):
            line += f"\n  REQUIRED TEXT (exact, once): {s['required_text']}"
        L.append(line)
    if not seeds:
        L.append("- (none: an ordinary quiet day)")
    L += ["", "BOT POSTS (reproduce exactly, unchanged):"]
    for b in bots:
        L.append(json.dumps({"ts": b.get("ts"), "channel": b.get("channel"), "user": b.get("user") or "alerting-bot", "text": b.get("text")}, ensure_ascii=False))
    if not bots:
        L.append("- (none)")
    if sheet.get("verbatim"):
        L += ["", "SENTENCES THAT MUST APPEAR VERBATIM in exactly one message (character for character):"]
        L += [f"- {v['text']}" for v in sheet["verbatim"]]
    if sheet.get("may_mention"):
        L += ["", "MAY MENTION (optional colour):"] + [f"- {m}" for m in sheet["may_mention"]]
    if sheet.get("must_not_mention"):
        L += ["", "NEVER MENTION (not even indirectly):"] + [f"- {m}" for m in sheet["must_not_mention"]]
    if sheet.get("forbidden_strings"):
        L += ["", "FORBIDDEN STRINGS (never use): " + ", ".join(f'"{s}"' for s in sheet["forbidden_strings"])]
    L += ["", "Write the day's messages now. Output only the JSON array."]
    return "\n".join(L)


# ---------------------------------------------------------------- checker
CHECKER_SYSTEM = """You are a meticulous fact checker for a synthetic document corpus. You receive a FACT SHEET (facts a document must contain, plus the names, identifiers and phrases it is allowed to use) and the DOCUMENT. Compare them and answer in JSON only.

Definitions:
- "missing": a fact from FACTS whose information is absent from the document. Paraphrase is fine; report a fact as missing only when the document does not convey it. Equivalent formats are the same value: "21:50", "9:50 pm", "ten to ten at night" all count as 21:50; "23 May", "May 23", "2026-05-23" and "the 23rd" are the same date; "room E" and "the E room" are the same room; "VX05" and "unit VX05" are the same unit.
- "contradictions": a place where the document states something that conflicts with a fact in FACTS: a different time, date, room/zone letter, id, name or number, or a claim that reverses the fact. Quote the offending passage. Do not report sentences listed under VERBATIM as contradictions even if they conflict with a fact; they are intentional.
- "invented_specifics": concrete identifiers in the document that appear nowhere in the FACT SHEET (FACTS, VERBATIM, MAY MENTION, KNOWN ENTITIES, AUTHOR, HEADER, STYLE) and cannot be derived from them: a clock time, a calendar date, a room/zone letter, a lot id, a ticket or unit id, a person's name, or a numeric quantity. For each give the quote, the kind (exactly one of: time, date, zone, lot, ticket, unit, name, number, other) and a short reason. Do not report generic words, relative time ("later", "that night", "for weeks", "the next morning", "around midnight" when a time near midnight is in the facts), the author's own name, or values clearly implied by the facts.

Output exactly one JSON object and nothing else:
{"missing": ["<fact_id>", ...], "contradictions": [{"fact_id": "<id>", "quote": "<passage>"}], "invented_specifics": [{"quote": "<text>", "kind": "<kind>", "why": "<reason>"}]}"""


def _checker_user(sheet: dict, text: str) -> str:
    a = sheet.get("author") or {}
    L = ["FACT SHEET", "", "FACTS:"]
    for f in sheet.get("must_include") or []:
        L.append(f"- [{f.get('fact_id', '?')}] {f['text']}")
    L += ["", "VERBATIM (intentional sentences, already present):"]
    L += [f"- {v['text']}" for v in sheet.get("verbatim") or []] or ["- (none)"]
    L += ["", "MAY MENTION:"] + ([f"- {m}" for m in sheet.get("may_mention") or []] or ["- (none)"])
    L += ["", "KNOWN ENTITIES: " + (", ".join(sheet.get("allowed_entities") or []) or "(none)")]
    L += ["", f"AUTHOR: {a.get('name', '?')} (handle {a.get('handle', '?')}), {a.get('role', '?')}, timezone {a.get('tz', '?')}"]
    if sheet.get("header"):
        L += ["", "HEADER: " + sheet["header"].replace("\n", " / ")]
    L += ["", "STYLE: " + str(sheet.get("style_notes") or "")]
    L += ["", "DOCUMENT", "<<<", text.rstrip(), ">>>", "", "Answer with the JSON object only."]
    return "\n".join(L)


_ZONE_RE = re.compile(r"\b(?:room|zone)\s+[A-Z]\b", re.I)
_LOT_RE = re.compile(r"\bLN-\d+\b", re.I)
_TIME_RE = re.compile(r"\b\d{1,2}:\d{2}\b|\b\d{1,2}\s?(?:am|pm)\b", re.I)
_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\b", re.I)


def _infer_kind(quote: str) -> str:
    if _LOT_RE.search(quote):
        return "lot"
    if _ZONE_RE.search(quote):
        return "zone"
    if _DATE_RE.search(quote):
        return "date"
    if _TIME_RE.search(quote):
        return "time"
    return "other"


def _run_checker(sheet: dict, text: str, *, client, checker_model, budget, log_path) -> dict:
    """One checker call. Returns {missing, contradictions, invented_specifics, graded_invented, cost, error, ...}."""
    res = {"model": checker_model, "missing": [], "contradictions": [], "invented_specifics": [], "graded_invented": [],
           "cost": 0.0, "error": None}
    messages = [{"role": "system", "content": CHECKER_SYSTEM}, {"role": "user", "content": _checker_user(sheet, text)}]
    known = {f.get("fact_id") for f in sheet.get("must_include") or []}
    raw, usage, parsed = "", {}, None
    for k in range(2):                              # one retry on transport/parse trouble
        if budget is not None and budget.exhausted:
            res["error"] = "cost_cap"
            break
        try:
            raw, usage = _invoke(client, checker_model, messages, CHECKER_TEMPERATURE, MAX_TOKENS)
            if budget is not None:
                budget.add(usage.get("cost"))
            res["cost"] += float(usage.get("cost") or 0.0)
            parsed = _extract_json(raw, "{")
            if not isinstance(parsed, dict):
                raise ValueError("checker JSON is not an object")
            res["error"] = None
            break
        except Exception as e:
            res["error"] = repr(e)[:300]
            parsed = None
    _log(log_path, {"event": "checker_call", "doc_id": sheet.get("doc_id"), "model": checker_model, "messages": messages,
                    "output": raw, "usage": usage, "error": res["error"]})
    if parsed is None:
        return res
    miss = [m for m in (parsed.get("missing") or []) if isinstance(m, str)]
    res["missing"] = [m for m in miss if m in known] if known else []
    res["missing_unknown_ids"] = [m for m in miss if m not in known]
    res["contradictions"] = [c for c in (parsed.get("contradictions") or []) if isinstance(c, dict)]
    inv = []
    for x in parsed.get("invented_specifics") or []:
        if not isinstance(x, dict):
            continue
        q = str(x.get("quote") or "")
        kind = str(x.get("kind") or "").strip().lower() or _infer_kind(q)
        inv.append({"quote": q, "kind": kind, "why": str(x.get("why") or "")})
    res["invented_specifics"] = inv
    res["graded_invented"] = [x for x in inv if x["kind"] in GRADED_KINDS]
    return res


# ---------------------------------------------------------------- verification (text kinds)
def verify(sheet: dict, text: str, *, client=None, checker_model: str | None = None, budget=None, log_path=None,
           run_checker: bool = True) -> dict:
    """Mechanical checks + (when the mechanical ones pass and a client is given) the checker model."""
    failures = []
    vb = []
    for v in sheet.get("verbatim") or []:
        n = text.count(v["text"])
        vb.append({"claim_id": v["claim_id"], "count": n, "ok": n == 1})
        if n != 1:
            failures.append(f"This sentence must appear EXACTLY once, character for character (it appeared {n} times): «{v['text']}»")
    hits = _forbidden_hits(sheet, text)
    for h in hits:
        failures.append(f"Remove every mention of «{h}» (it must not appear at all, not even inside another word).")
    lo, hi = sheet.get("length_words") or [150, 400]
    words = _word_count(text)
    lmin, lmax = int(lo * (1 - LENGTH_SLACK)), int(round(hi * (1 + LENGTH_SLACK)))
    length_ok = lmin <= words <= lmax
    if not length_ok:
        failures.append(f"The document is {words} words; write between {lo} and {hi} words.")
    mech_ok = all(x["ok"] for x in vb) and not hits
    checker = None
    checker_cost = 0.0
    if run_checker and client is not None and mech_ok and (sheet.get("must_include") or []):
        checker = _run_checker(sheet, text, client=client, checker_model=checker_model or _env("EVAL_CHECKER_MODEL", DEFAULT_CHECKER),
                               budget=budget, log_path=log_path)
        checker_cost = checker.get("cost", 0.0)
        by_id = {f.get("fact_id"): f["text"] for f in sheet.get("must_include") or []}
        for m in checker["missing"]:
            failures.append(f"Missing fact [{m}]: {by_id.get(m, '')}")
        for c in checker["contradictions"]:
            fid = c.get("fact_id")
            failures.append(f"Contradiction with fact [{fid}] ({by_id.get(fid, '')}) in: «{c.get('quote', '')}»")
        for x in checker["graded_invented"]:
            failures.append(f"Invented {x['kind']} not in the brief; remove or replace it: «{x['quote']}» ({x['why']})")
    elif run_checker and client is not None and not mech_ok:
        checker = {"skipped": "mechanical_failure"}
    ok = mech_ok and length_ok and not (checker and (checker.get("missing") or checker.get("contradictions") or checker.get("graded_invented")))
    return {"ok": ok, "verbatim": vb, "forbidden": hits, "length": {"words": words, "range": [lo, hi], "min": lmin, "max": lmax, "ok": length_ok},
            "checker": checker, "checker_cost": checker_cost, "failures": failures}


# ---------------------------------------------------------------- verification (chat days)
def _chat_allowed_users(sheet: dict) -> set:
    users = set(sheet.get("allowed_users") or sheet.get("handles") or [])
    users |= {s.get("user") for s in sheet.get("messages_seed") or [] if s.get("user")}
    users |= {b.get("user") or "alerting-bot" for b in sheet.get("bot_posts") or []}
    return users


def _chat_allowed_channels(sheet: dict) -> set:
    ch = set(sheet.get("channels") or [])
    ch |= {s.get("channel") for s in sheet.get("messages_seed") or [] if s.get("channel")}
    ch |= {b.get("channel") for b in sheet.get("bot_posts") or [] if b.get("channel")}
    return ch


def _norm_msg(m: dict) -> dict:
    return {"ts": str(m.get("ts", "")).strip(), "channel": str(m.get("channel", "")).strip(), "user": str(m.get("user", "")).strip(),
            "text": str(m.get("text", ""))}


def verify_chat(sheet: dict, msgs) -> dict:
    failures = []
    if not isinstance(msgs, list) or not all(isinstance(m, dict) for m in msgs):
        return {"ok": False, "failures": ["Output must be a JSON array of objects with keys ts, channel, user, text."], "n_messages": 0}
    msgs = [_norm_msg(m) for m in msgs]
    bad = [m for m in msgs if not (m["ts"] and m["channel"] and m["user"] and m["text"])]
    if bad:
        failures.append(f"{len(bad)} message(s) lack one of ts/channel/user/text.")
    nmin, nmax = sheet.get("n_messages") or CHAT_COUNT_DEFAULT
    if not (nmin <= len(msgs) <= nmax):
        failures.append(f"The day has {len(msgs)} messages; produce between {nmin} and {nmax} (including bot posts).")
    users, channels = _chat_allowed_users(sheet), _chat_allowed_channels(sheet)
    bot_users = {b.get("user") or "alerting-bot" for b in sheet.get("bot_posts") or []}
    unknown_u = sorted({m["user"] for m in msgs if m["user"] and m["user"] not in users})
    if unknown_u:
        failures.append("Unknown user(s) " + ", ".join(unknown_u) + "; use only: " + ", ".join(sorted(users)))
    unknown_c = sorted({m["channel"] for m in msgs if m["channel"] and m["channel"] not in channels})
    if unknown_c:
        failures.append("Unknown channel(s) " + ", ".join(unknown_c) + "; use only: " + ", ".join(sorted(channels)))
    # timestamps
    parsed = []
    for m in msgs:
        try:
            parsed.append(_parse_iso(m["ts"]))
        except Exception:
            parsed.append(None)
    n_badts = sum(1 for p in parsed if p is None)
    if n_badts:
        failures.append(f"{n_badts} message(s) have a timestamp that is not ISO 8601 (use the same format as the brief).")
    if sheet.get("window"):
        try:
            w0, w1 = _parse_iso(sheet["window"][0]), _parse_iso(sheet["window"][1])
            out = sum(1 for p in parsed if p is not None and not (w0 <= p <= w1))
            if out:
                failures.append(f"{out} message(s) fall outside the window {sheet['window'][0]}..{sheet['window'][1]}.")
        except Exception:
            pass
    elif sheet.get("date"):
        out = sum(1 for m in msgs if m["ts"] and m["ts"][:10] != str(sheet["date"]))
        if out:
            failures.append(f"{out} message(s) are not dated {sheet['date']}; every timestamp must be on that date.")
    # seeds
    for s in sheet.get("messages_seed") or []:
        try:
            t0 = _parse_iso(s["t_iso"])
        except Exception:
            continue
        near = [i for i, p in enumerate(parsed) if p is not None and msgs[i]["user"] == s.get("user")
                and (not s.get("channel") or msgs[i]["channel"] == s["channel"]) and abs((p - t0).total_seconds()) <= CHAT_WINDOW_MIN * 60]
        rt = s.get("required_text")
        if rt:
            total = sum(m["text"].count(rt) for m in msgs)
            if total != 1:
                failures.append(f"The text «{rt}» must appear exactly once (it appeared {total} times), in a message by {s.get('user')} in {s.get('channel')} within 20 minutes of {s['t_iso']}.")
            elif not any(rt in msgs[i]["text"] for i in near):
                failures.append(f"The text «{rt}» must be in a message by {s.get('user')} in {s.get('channel')} timestamped within 20 minutes of {s['t_iso']}.")
        elif not near:
            failures.append(f"Missing event: a message by {s.get('user')} in {s.get('channel')} within 20 minutes of {s['t_iso']} ({s.get('gist', '')}).")
    # bot posts
    for b in sheet.get("bot_posts") or []:
        bu = b.get("user") or "alerting-bot"
        if not any(m["ts"] == str(b.get("ts")) and m["text"] == b.get("text") and m["channel"] == b.get("channel") and m["user"] == bu for m in msgs):
            failures.append("Bot post missing or altered; reproduce exactly: " + json.dumps({"ts": b.get("ts"), "channel": b.get("channel"), "user": bu, "text": b.get("text")}, ensure_ascii=False))
    # sheet-level verbatim
    vb = []
    for v in sheet.get("verbatim") or []:
        n = sum(m["text"].count(v["text"]) for m in msgs)
        vb.append({"claim_id": v["claim_id"], "count": n, "ok": n == 1})
        if n != 1:
            failures.append(f"This sentence must appear in exactly one message, character for character (found {n}): «{v['text']}»")
    # forbidden strings over human messages
    human_text = "\n".join(m["text"] for m in msgs if m["user"] not in bot_users)
    hits = _forbidden_hits(sheet, human_text)
    for h in hits:
        failures.append(f"Remove every mention of «{h}» from the messages.")
    return {"ok": not failures, "failures": failures, "n_messages": len(msgs), "verbatim": vb, "forbidden": hits,
            "unknown_users": unknown_u, "unknown_channels": unknown_c}


# ---------------------------------------------------------------- rendering
def _corrections(failures: list, chat: bool = False) -> str:
    what = "the complete JSON array for the day" if chat else "the COMPLETE document"
    tail = "Output only the JSON array." if chat else "Output only the document text."
    return ("Your previous draft was rejected by the checks below. Rewrite " + what +
            " from scratch, fixing every point and keeping everything that was already correct. " + tail + "\n\n" +
            "\n".join(f"- {f}" for f in failures))


def _fallback_reason(attempts: list, budget) -> str:
    if budget is not None and budget.exhausted and (not attempts or attempts[-1].get("ok") is not True):
        if not attempts or not attempts[-1].get("failures"):
            return "cost_cap"
    if attempts and all(a.get("error") for a in attempts):
        return "client_error"
    if not attempts:
        return "cost_cap" if (budget is not None and budget.exhausted) else "no_client"
    return "verification_failed"


def _render_text(sheet: dict, *, client, log_path, budget, writer_model, checker_model, max_attempts) -> dict:
    kind = sheet.get("kind") or "document"
    system = _prompt_for(kind)
    messages = [{"role": "system", "content": system}, {"role": "user", "content": _brief_text(sheet)}]
    attempts, cost = [], 0.0
    header = sheet.get("header")
    for n in range(1, max_attempts + 1):
        if client is None or budget.exhausted:
            break
        try:
            out, usage = _invoke(client, writer_model, messages, WRITER_TEMPERATURE, MAX_TOKENS)
        except Exception as e:
            attempts.append({"n": n, "model": writer_model, "error": repr(e)[:300], "ok": False, "failures": [], "cost": 0.0})
            _log(log_path, {"event": "writer_call", "doc_id": sheet.get("doc_id"), "attempt": n, "model": writer_model, "messages": messages, "error": attempts[-1]["error"]})
            continue
        budget.add(usage.get("cost"))
        cost += float(usage.get("cost") or 0.0)
        _log(log_path, {"event": "writer_call", "doc_id": sheet.get("doc_id"), "attempt": n, "model": writer_model, "messages": messages, "output": out, "usage": usage})
        text = _with_header(header, _clean_output(out))
        ver = verify(sheet, text, client=client, checker_model=checker_model, budget=budget, log_path=log_path)
        cost += ver.get("checker_cost", 0.0)
        attempts.append({"n": n, "model": writer_model, "ok": ver["ok"], "failures": ver["failures"], "words": ver["length"]["words"],
                         "cost": round(float(usage.get("cost") or 0.0) + ver.get("checker_cost", 0.0), 6), "error": None})
        _log(log_path, {"event": "verification", "doc_id": sheet.get("doc_id"), "attempt": n, "verification": ver})
        if ver["ok"]:
            res = {"doc_id": sheet.get("doc_id"), "path": sheet.get("path"), "kind": kind, "text": text, "rendered_by": "llm", "attempts": attempts,
                   "verification": ver, "spans": _spans(sheet, text), "cost_usd": round(cost, 6), "fallback_reason": None}
            _log(log_path, {"event": "result", "doc_id": sheet.get("doc_id"), "rendered_by": "llm", "attempts": len(attempts), "cost_usd": res["cost_usd"], "spans": res["spans"]})
            return res
        messages = messages + [{"role": "assistant", "content": out}, {"role": "user", "content": _corrections(ver["failures"])}]
    text = sheet["fallback"] if isinstance(sheet.get("fallback"), str) else str(sheet.get("fallback") or "")
    ver = verify(sheet, text, client=None, run_checker=False)
    reason = _fallback_reason(attempts, budget if client is not None else None)
    res = {"doc_id": sheet.get("doc_id"), "path": sheet.get("path"), "kind": kind, "text": text, "rendered_by": "template", "attempts": attempts,
           "verification": ver, "spans": _spans(sheet, text), "cost_usd": round(cost, 6), "fallback_reason": reason}
    _log(log_path, {"event": "result", "doc_id": sheet.get("doc_id"), "rendered_by": "template", "reason": reason, "attempts": len(attempts), "cost_usd": res["cost_usd"], "spans": res["spans"]})
    return res


def _chat_fallback(sheet: dict) -> list:
    msgs = [_norm_msg(m) for m in (sheet.get("fallback") or []) if isinstance(m, dict)]
    seen = {(m["ts"], m["channel"], m["user"], m["text"]) for m in msgs}
    for b in sheet.get("bot_posts") or []:
        m = _norm_msg({"ts": b.get("ts"), "channel": b.get("channel"), "user": b.get("user") or "alerting-bot", "text": b.get("text")})
        key = (m["ts"], m["channel"], m["user"], m["text"])
        if key not in seen:
            seen.add(key)
            msgs.append(m)
    return _sort_msgs(msgs)


def _sort_msgs(msgs: list) -> list:
    def key(m):
        try:
            return (0, _parse_iso(m["ts"]).timestamp(), m["channel"], m["user"])
        except Exception:
            return (1, 0.0, m["channel"], m["user"])
    return sorted(msgs, key=key)


def _render_chat(sheet: dict, *, client, log_path, budget, writer_model, checker_model, max_attempts) -> dict:
    system = _prompt_for("chat_day")
    messages = [{"role": "system", "content": system}, {"role": "user", "content": _brief_chat(sheet)}]
    attempts, cost = [], 0.0
    for n in range(1, max_attempts + 1):
        if client is None or budget.exhausted:
            break
        try:
            out, usage = _invoke(client, writer_model, messages, WRITER_TEMPERATURE, MAX_TOKENS)
        except Exception as e:
            attempts.append({"n": n, "model": writer_model, "error": repr(e)[:300], "ok": False, "failures": [], "cost": 0.0})
            _log(log_path, {"event": "writer_call", "doc_id": sheet.get("doc_id"), "attempt": n, "model": writer_model, "messages": messages, "error": attempts[-1]["error"]})
            continue
        budget.add(usage.get("cost"))
        cost += float(usage.get("cost") or 0.0)
        _log(log_path, {"event": "writer_call", "doc_id": sheet.get("doc_id"), "attempt": n, "model": writer_model, "messages": messages, "output": out, "usage": usage})
        try:
            msgs = _extract_json(out, "[")
            ver = verify_chat(sheet, msgs)
        except Exception as e:
            msgs = None
            ver = {"ok": False, "failures": [f"Output was not a valid JSON array: {repr(e)[:120]}. Output only the JSON array, no code fence, no prose."], "n_messages": 0}
        checker = None
        if ver["ok"] and (sheet.get("must_include") or []):
            flat = "\n".join(f"[{m.get('ts')}] {m.get('user')} in {m.get('channel')}: {m.get('text')}" for m in msgs)
            checker = _run_checker(sheet, flat, client=client, checker_model=checker_model, budget=budget, log_path=log_path)
            cost += checker.get("cost", 0.0)
            by_id = {f.get("fact_id"): f["text"] for f in sheet["must_include"]}
            for m in checker["missing"]:
                ver["failures"].append(f"Missing fact [{m}]: {by_id.get(m, '')}")
            for c in checker["contradictions"]:
                ver["failures"].append(f"Contradiction with fact [{c.get('fact_id')}] in: «{c.get('quote', '')}»")
            for x in checker["graded_invented"]:
                ver["failures"].append(f"Invented {x['kind']} not in the brief; remove or replace it: «{x['quote']}» ({x['why']})")
            ver["ok"] = not ver["failures"]
        ver["checker"] = checker
        attempts.append({"n": n, "model": writer_model, "ok": ver["ok"], "failures": ver["failures"], "n_messages": ver.get("n_messages", 0),
                         "cost": round(float(usage.get("cost") or 0.0) + (checker or {}).get("cost", 0.0), 6), "error": None})
        _log(log_path, {"event": "verification", "doc_id": sheet.get("doc_id"), "attempt": n, "verification": ver})
        if ver["ok"]:
            final = _sort_msgs([_norm_msg(m) for m in msgs])
            res = {"doc_id": sheet.get("doc_id"), "path": sheet.get("path"), "kind": "chat_day", "messages": final, "rendered_by": "llm", "attempts": attempts,
                   "verification": ver, "spans": {}, "cost_usd": round(cost, 6), "fallback_reason": None}
            _log(log_path, {"event": "result", "doc_id": sheet.get("doc_id"), "rendered_by": "llm", "attempts": len(attempts), "cost_usd": res["cost_usd"], "n_messages": len(final)})
            return res
        messages = messages + [{"role": "assistant", "content": out}, {"role": "user", "content": _corrections(ver["failures"], chat=True)}]
    final = _chat_fallback(sheet)
    ver = verify_chat(sheet, final)
    reason = _fallback_reason(attempts, budget if client is not None else None)
    res = {"doc_id": sheet.get("doc_id"), "path": sheet.get("path"), "kind": "chat_day", "messages": final, "rendered_by": "template", "attempts": attempts,
           "verification": ver, "spans": {}, "cost_usd": round(cost, 6), "fallback_reason": reason}
    _log(log_path, {"event": "result", "doc_id": sheet.get("doc_id"), "rendered_by": "template", "reason": reason, "attempts": len(attempts), "cost_usd": res["cost_usd"], "n_messages": len(final)})
    return res


def render(sheet: dict, *, client=None, log_path=None, budget: Budget | None = None, writer_model: str | None = None,
           checker_model: str | None = None, max_attempts: int = MAX_ATTEMPTS) -> dict:
    """Render one fact sheet.

    Returns ``{"text" | "messages", "rendered_by": "llm|template", "attempts": [...], "verification": {...},
    "spans": {claim_id: [start, end] | None}, "cost_usd", "fallback_reason", "doc_id", "path", "kind"}``.
    ``client`` defaults to a real OpenRouter client (needs OPENROUTER_API_KEY); pass a stub in tests.
    """
    if client is None:
        try:
            client = OpenRouterClient()
        except RuntimeError:
            client = None                       # no key: template only
    budget = budget or Budget()
    writer_model = writer_model or _env("EVAL_WRITER_MODEL", DEFAULT_WRITER)
    checker_model = checker_model or _env("EVAL_CHECKER_MODEL", DEFAULT_CHECKER)
    kw = dict(client=client, log_path=log_path, budget=budget, writer_model=writer_model, checker_model=checker_model, max_attempts=max_attempts)
    if sheet.get("kind") == "chat_day":
        return _render_chat(sheet, **kw)
    return _render_text(sheet, **kw)


# ---------------------------------------------------------------- batch
def render_all(sheets_dir: Path, out_root: Path, log_path: Path, workers: int = 4, *, client=None, budget: Budget | None = None,
               writer_model: str | None = None, checker_model: str | None = None, max_attempts: int = MAX_ATTEMPTS) -> dict:
    """Render every ``*.json`` sheet in ``sheets_dir`` into ``out_root`` (text docs at ``sheet["path"]``, chat days merged
    into ``people/chat_export.json``). Returns ``{n, llm, template, cost_usd, cap_usd, docs: [...], chat: {...}}``."""
    sheets_dir, out_root = Path(sheets_dir), Path(out_root)
    sheets = []
    for p in sorted(sheets_dir.glob("*.json")):
        sheets.append(json.loads(p.read_text(encoding="utf-8")))
    budget = budget or Budget()
    if client is None:
        try:
            client = OpenRouterClient()
        except RuntimeError:
            client = None
    writer_model = writer_model or _env("EVAL_WRITER_MODEL", DEFAULT_WRITER)
    checker_model = checker_model or _env("EVAL_CHECKER_MODEL", DEFAULT_CHECKER)
    _log(log_path, {"event": "batch_start", "n": len(sheets), "writer_model": writer_model, "checker_model": checker_model, "cap_usd": budget.cap, "workers": workers})

    def one(s):
        return render(s, client=client, log_path=log_path, budget=budget, writer_model=writer_model, checker_model=checker_model, max_attempts=max_attempts)

    with ThreadPoolExecutor(max_workers=max(1, int(workers))) as ex:
        results = list(ex.map(one, sheets))
    docs, chat_msgs, chat_claims, chat_path, chat_docs = [], [], [], None, []
    for s, r in zip(sheets, results):
        rec = {"doc_id": s.get("doc_id"), "path": s.get("path"), "kind": s.get("kind"), "rendered_by": r["rendered_by"], "n_attempts": len(r["attempts"]),
               "fallback_reason": r.get("fallback_reason"), "cost_usd": r.get("cost_usd", 0.0), "spans": r.get("spans", {}),
               "verification_ok": bool(r.get("verification", {}).get("ok"))}
        if s.get("kind") == "chat_day":
            chat_msgs.extend(r["messages"])
            chat_claims.extend(_chat_claims(s))
            chat_path = chat_path or s.get("path")
            rec["n_messages"] = len(r["messages"])
            chat_docs.append(rec)
        else:
            p = out_root / s["path"]
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(r["text"], encoding="utf-8")
        docs.append(rec)
    chat = None
    if chat_docs:
        chat_path = chat_path or "people/chat_export.json"
        merged = _sort_msgs(chat_msgs)
        out = [{"id": f"m{i + 1:04d}", "channel": m["channel"], "ts": m["ts"], "user": m["user"], "text": m["text"]} for i, m in enumerate(merged)]
        body = json.dumps(out, indent=1, ensure_ascii=False) + "\n"
        p = out_root / chat_path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
        spans = {}
        for c in chat_claims:
            enc = json.dumps(c["text"], ensure_ascii=False)[1:-1]
            i = body.find(enc)
            spans[c["claim_id"]] = {"span": [i, i + len(enc)] if i >= 0 else None, "count": body.count(enc), "text": c["text"]}
        chat = {"path": chat_path, "n_messages": len(out), "days": len(chat_docs), "llm_days": sum(1 for d in chat_docs if d["rendered_by"] == "llm"),
                "spans": {k: v["span"] for k, v in spans.items()}, "claims": spans}
    summary = {"n": len(sheets), "llm": sum(1 for r in results if r["rendered_by"] == "llm"), "template": sum(1 for r in results if r["rendered_by"] == "template"),
               "cost_usd": round(budget.spent, 4), "cap_usd": budget.cap, "cap_hit": budget.exhausted, "writer_model": writer_model, "checker_model": checker_model,
               "docs": docs, "chat": chat}
    _log(log_path, {"event": "batch_end", **{k: v for k, v in summary.items() if k != "docs"}})
    return summary


if __name__ == "__main__":                     # python -m gen.docs_llm <sheets_dir> <out_root> [log_path]
    import sys
    a = sys.argv[1:]
    if len(a) < 2:
        print("usage: python -m gen.docs_llm <sheets_dir> <out_root> [log_path] [workers]")
        sys.exit(2)
    summ = render_all(Path(a[0]), Path(a[1]), Path(a[2]) if len(a) > 2 else Path(a[1]).parent / "docs_llm_log.jsonl", int(a[3]) if len(a) > 3 else 4)
    print(json.dumps({k: v for k, v in summ.items() if k != "docs"}, indent=1))
