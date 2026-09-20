"""docs_llm: fact sheet -> LLM-written document with enforced facts. Zero-API by default (stub client);
one live test guarded by EVAL_DOCS_LIVE=1 that spends real money (< $0.20)."""
import json
import os
import sys
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from gen import docs_llm  # noqa: E402

W, C = "stub/writer", "stub/checker"
CHECK_OK = '{"missing": [], "contradictions": [], "invented_specifics": []}'


class Stub:
    """Callable (model, messages, temperature, max_tokens) -> str. Queues per model; the last item repeats."""

    def __init__(self, writer=(), checker=(CHECK_OK,), cost=None):
        self.writer, self.checker, self.cost, self.calls = list(writer), list(checker), cost, []

    def __call__(self, model, messages, temperature, max_tokens):
        self.calls.append({"model": model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens})
        q = self.checker if model == C else self.writer
        assert q, f"stub has no output queued for {model}"
        out = q.pop(0) if len(q) > 1 else q[0]
        return (out, {"cost": self.cost}) if self.cost is not None else out

    def n(self, model):
        return sum(1 for c in self.calls if c["model"] == model)


FC01 = "all the rooms were closed and nobody went near room E after that"
FC07 = "I checked room E again at 06:22 on my way out and the door was shut"
GOOD = ("On the night of 23 May 2026 I came on shift at 21:48 as usual and the temp was on with me. I did my walk-through at 00:18 and "
        f"{FC01}; the corridor was quiet. The compressor on VX05 has been noisy for weeks and I said so in the handover. "
        f"{FC07}.")
NO_FC01 = GOOD.replace(FC01, "all the rooms were closed as usual")
WEDGE = GOOD + " I never saw the wedge."
FALLBACK = f"# Statement — Lena Okafor (night shift lead)\nTaken 2026-05-28\n\nI came on at 21:48. I did my walk-through at 00:18 and {FC01}. {FC07}.\n"


def statement_sheet():
    return {
        "doc_id": "doc:night_lead_statement", "path": "people/statements/night_lead_l.okafor.md", "kind": "statement",
        "author": {"name": "Lena Okafor", "handle": "l.okafor", "role": "night shift lead", "persona": "defensive, terse", "tz": "Europe/Oslo"},
        "audience": "internal investigation", "length_words": [40, 120],
        "header": "# Statement — Lena Okafor (night shift lead)\nTaken 2026-05-28",
        "must_include": [{"fact_id": "E17", "text": "came on shift at 21:48 on 23 May 2026"}, {"fact_id": "E19", "text": "walk-through of the rooms at 00:18"}],
        "verbatim": [{"claim_id": "fc01", "text": FC01}, {"claim_id": "fc07", "text": FC07}],
        "may_mention": ["the corridor being quiet"], "must_not_mention": ["the wedge"], "forbidden_strings": ["truth", "simulat"],
        "allowed_entities": ["VX05"], "style_notes": "first person, no headings, 24-hour clock", "fallback": FALLBACK,
    }


BOT = {"ts": "2026-05-23T17:26:00Z", "channel": "#alerts-coldchain", "user": "alerting-bot", "text": "[CRITICAL] zone D high temp: 9.3 C (limits 0.5..8.5)"}
REQ = "VX05 compressor is clicking on and off again"


def chat_sheet():
    return {
        "doc_id": "doc:chat_2026-05-23", "path": "people/chat_export.json", "kind": "chat_day", "date": "2026-05-23",
        "allowed_users": ["l.okafor", "l.rivera", "s.larsen"], "channels": ["#ops-floor", "#alerts-coldchain"], "n_messages": [3, 40],
        "personas": {"l.okafor": "terse night lead", "s.larsen": "warehouse manager, chatty"},
        "messages_seed": [
            {"t_iso": "2026-05-23T22:04:00Z", "user": "l.okafor", "channel": "#ops-floor", "gist": "night shift starting"},
            {"t_iso": "2026-05-23T23:30:00Z", "user": "l.okafor", "channel": "#ops-floor", "required_text": REQ, "claim_id": "fc09", "gist": "compressor complaint"},
        ],
        "bot_posts": [BOT], "must_not_mention": ["wedge"], "forbidden_strings": ["truth"],
        "fallback": [{"ts": "2026-05-23T22:05:00Z", "channel": "#ops-floor", "user": "l.okafor", "text": "night shift on"},
                     {"ts": "2026-05-23T23:31:00Z", "channel": "#ops-floor", "user": "l.okafor", "text": REQ + ", told Sam"}],
    }


def chat_json(user2="s.larsen", req_ts="2026-05-23T23:35:00Z"):
    return json.dumps([BOT,
                       {"ts": "2026-05-23T22:06:00Z", "channel": "#ops-floor", "user": "l.okafor", "text": "night shift on, all quiet"},
                       {"ts": req_ts, "channel": "#ops-floor", "user": "l.okafor", "text": REQ + " tonight, sounds rough"},
                       {"ts": "2026-05-23T23:40:00Z", "channel": "#ops-floor", "user": user2, "text": "noted, will ring the vendor"}])


def R(sheet, stub, **kw):
    kw.setdefault("budget", docs_llm.Budget(cap_usd=100.0))
    return docs_llm.render(sheet, client=stub, writer_model=W, checker_model=C, **kw)


# ---------------------------------------------------------------- verbatim enforcement
def test_verbatim_missing_then_included_is_two_attempts_llm(tmp_path):
    stub = Stub(writer=[NO_FC01, GOOD])
    res = R(statement_sheet(), stub, log_path=tmp_path / "log.jsonl")
    assert res["rendered_by"] == "llm" and len(res["attempts"]) == 2
    assert res["attempts"][0]["ok"] is False and res["attempts"][1]["ok"] is True
    assert any(FC01 in f and "0 times" in f for f in res["attempts"][0]["failures"])
    assert stub.n(W) == 2 and stub.n(C) == 1, "checker is skipped when mechanical checks fail"
    # the correction round-trip: previous draft + corrections appended to the conversation
    msgs = stub.calls[1]["messages"]
    assert msgs[-2]["role"] == "assistant" and msgs[-2]["content"] == NO_FC01
    assert msgs[-1]["role"] == "user" and FC01 in msgs[-1]["content"]
    assert stub.calls[0]["temperature"] == 0.7 and stub.calls[0]["max_tokens"] == 2500
    checker_call = [c for c in stub.calls if c["model"] == C][0]
    assert checker_call["temperature"] == 0 and "E17" in checker_call["messages"][1]["content"]
    assert res["text"].startswith("# Statement — Lena Okafor") and res["text"].endswith(FC07 + ".\n")
    assert res["verification"]["ok"] and res["verification"]["checker"]["missing"] == []
    events = [json.loads(l)["event"] for l in (tmp_path / "log.jsonl").read_text().splitlines()]
    assert events == ["writer_call", "verification", "writer_call", "checker_call", "verification", "result"]


def test_verbatim_twice_is_a_failure():
    stub = Stub(writer=[GOOD + " " + FC07 + ".", GOOD])
    res = R(statement_sheet(), stub)
    assert len(res["attempts"]) == 2 and "2 times" in res["attempts"][0]["failures"][0]


# ---------------------------------------------------------------- must_not_mention -> retry -> template
def test_must_not_mention_retries_then_template():
    sheet = statement_sheet()
    stub = Stub(writer=[WEDGE])
    res = R(sheet, stub)
    assert res["rendered_by"] == "template" and res["fallback_reason"] == "verification_failed"
    assert len(res["attempts"]) == 3 and stub.n(W) == 3 and stub.n(C) == 0
    assert all("the wedge" in " ".join(a["failures"]) for a in res["attempts"])
    assert res["text"] == FALLBACK
    assert res["verification"]["ok"] and res["verification"]["checker"] is None
    assert res["spans"]["fc01"] == [FALLBACK.index(FC01), FALLBACK.index(FC01) + len(FC01)]


def test_forbidden_strings_case_insensitive():
    sheet = statement_sheet()
    sheet["forbidden_strings"] = ["SIMULAT"]
    v = docs_llm.verify(sheet, "we simulated it. " + GOOD, run_checker=False)
    assert v["forbidden"] == ["SIMULAT"] and not v["ok"]


# ---------------------------------------------------------------- spans
def test_spans_offsets_in_final_text_including_header():
    stub = Stub(writer=[GOOD])
    res = R(statement_sheet(), stub)
    t = res["text"]
    for cid, vt in (("fc01", FC01), ("fc07", FC07)):
        s, e = res["spans"][cid]
        assert t[s:e] == vt and t.count(vt) == 1
    assert res["spans"]["fc01"][0] > len("# Statement — Lena Okafor (night shift lead)\nTaken 2026-05-28\n\n") - 1


def test_spans_none_when_fallback_lacks_the_sentence():
    sheet = statement_sheet()
    sheet["fallback"] = "nothing here\n"
    res = R(sheet, Stub(writer=[WEDGE]))
    assert res["rendered_by"] == "template" and res["spans"] == {"fc01": None, "fc07": None}


# ---------------------------------------------------------------- length
def test_length_outside_40pct_fails_then_template():
    sheet = statement_sheet()
    sheet["length_words"] = [300, 400]          # GOOD is ~70 words -> below 180
    res = R(sheet, Stub(writer=[GOOD]))
    assert res["rendered_by"] == "template" and "words" in res["attempts"][0]["failures"][0]


# ---------------------------------------------------------------- checker feedback
def test_checker_missing_fact_fed_back_then_pass():
    stub = Stub(writer=[GOOD], checker=['{"missing": ["E17"], "contradictions": [], "invented_specifics": []}', CHECK_OK])
    res = R(statement_sheet(), stub)
    assert res["rendered_by"] == "llm" and len(res["attempts"]) == 2
    assert "Missing fact [E17]" in res["attempts"][0]["failures"][0]
    assert "E17" in stub.calls[2]["messages"][-1]["content"] and stub.n(C) == 2


def test_checker_contradiction_fails():
    stub = Stub(writer=[GOOD], checker=['{"missing": [], "contradictions": [{"fact_id": "E19", "quote": "walk-through at 01:18"}], "invented_specifics": []}'])
    res = R(statement_sheet(), stub)
    assert res["rendered_by"] == "template" and "Contradiction" in res["attempts"][0]["failures"][0]


def test_checker_invented_graded_kinds_only():
    inv_number = '{"missing": [], "contradictions": [], "invented_specifics": [{"quote": "forty minutes", "kind": "number", "why": "not in sheet"}]}'
    res = R(statement_sheet(), Stub(writer=[GOOD], checker=[inv_number]))
    assert res["rendered_by"] == "llm" and res["verification"]["checker"]["graded_invented"] == []
    inv_zone = '{"missing": [], "contradictions": [], "invented_specifics": [{"quote": "room F", "kind": "zone", "why": "not in sheet"}]}'
    res = R(statement_sheet(), Stub(writer=[GOOD], checker=[inv_zone]))
    assert res["rendered_by"] == "template" and "Invented zone" in res["attempts"][0]["failures"][0]
    inv_nokind = '{"missing": [], "contradictions": [], "invented_specifics": [{"quote": "lot LN-12345", "why": "x"}]}'
    res = R(statement_sheet(), Stub(writer=[GOOD], checker=[inv_nokind]))
    assert res["rendered_by"] == "template" and res["attempts"][0]["failures"][0].startswith("Invented lot")


def test_checker_garbage_is_non_fatal_and_retried_once():
    stub = Stub(writer=[GOOD], checker=["not json at all"])
    res = R(statement_sheet(), stub)
    assert res["rendered_by"] == "llm" and stub.n(C) == 2 and res["verification"]["checker"]["error"]


def test_writer_code_fence_stripped():
    res = R(statement_sheet(), Stub(writer=["```markdown\n" + GOOD + "\n```"]))
    assert res["rendered_by"] == "llm" and "```" not in res["text"]


# ---------------------------------------------------------------- chat days
def test_chat_day_good_json_parsed_and_validated():
    stub = Stub(writer=[chat_json()])
    res = R(chat_sheet(), stub)
    assert res["rendered_by"] == "llm" and len(res["messages"]) == 4 and stub.n(C) == 0
    assert [m["ts"] for m in res["messages"]] == sorted(m["ts"] for m in res["messages"])
    assert set(res["messages"][0]) == {"ts", "channel", "user", "text"}
    assert any(REQ in m["text"] and m["user"] == "l.okafor" for m in res["messages"])
    brief = stub.calls[0]["messages"][1]["content"]
    assert "REQUIRED TEXT (exact, once): " + REQ in brief and BOT["text"] in brief and "l.rivera" in brief


def test_chat_day_bad_user_fails_then_fallback():
    stub = Stub(writer=[chat_json(user2="z.unknown")])
    res = R(chat_sheet(), stub)
    assert res["rendered_by"] == "template" and len(res["attempts"]) == 3
    assert any("Unknown user(s) z.unknown" in f for f in res["attempts"][0]["failures"])
    # fallback = sheet fallback messages + the bot posts, sorted by ts
    assert [m["ts"] for m in res["messages"]] == ["2026-05-23T17:26:00Z", "2026-05-23T22:05:00Z", "2026-05-23T23:31:00Z"]
    assert res["messages"][0]["text"] == BOT["text"] and res["verification"]["ok"]


def test_chat_day_required_text_outside_window_fails():
    res = R(chat_sheet(), Stub(writer=[chat_json(req_ts="2026-05-23T23:55:00Z")]))    # 25 min after the seed
    assert res["rendered_by"] == "template"
    assert any("within 20 minutes of 2026-05-23T23:30:00Z" in f for f in res["attempts"][0]["failures"])


def test_chat_day_bot_post_altered_and_wrong_date_fail():
    msgs = json.loads(chat_json())
    msgs[0]["text"] = msgs[0]["text"].replace("9.3", "9.4")
    msgs[1]["ts"] = "2026-05-24T22:06:00Z"
    v = docs_llm.verify_chat(chat_sheet(), msgs)
    assert not v["ok"] and any("Bot post missing or altered" in f for f in v["failures"]) and any("not dated 2026-05-23" in f for f in v["failures"])


def test_chat_day_invalid_json_then_ok():
    stub = Stub(writer=["Here you go:\nnot json", chat_json()])
    res = R(chat_sheet(), stub)
    assert res["rendered_by"] == "llm" and len(res["attempts"]) == 2 and "valid JSON array" in res["attempts"][0]["failures"][0]


# ---------------------------------------------------------------- cost cap
def test_cost_cap_exhausted_means_template_without_calls():
    stub = Stub(writer=[GOOD])
    res = R(statement_sheet(), stub, budget=docs_llm.Budget(cap_usd=0.0))
    assert res["rendered_by"] == "template" and res["fallback_reason"] == "cost_cap" and res["attempts"] == [] and stub.calls == []


def test_cost_accumulates_from_usage_and_caps_mid_batch(tmp_path):
    sheets = tmp_path / "sheets"
    sheets.mkdir()
    s1, s2 = statement_sheet(), statement_sheet()
    s2["doc_id"], s2["path"] = "doc:second", "people/statements/second.md"
    (sheets / "a.json").write_text(json.dumps(s1))
    (sheets / "b.json").write_text(json.dumps(s2))
    (sheets / "c.json").write_text(json.dumps(chat_sheet()))
    stub = Stub(writer=[GOOD], cost=0.06)          # every call (writer or checker) costs 0.06
    budget = docs_llm.Budget(cap_usd=0.10)
    out = tmp_path / "evidence"
    summ = docs_llm.render_all(sheets, out, tmp_path / "log.jsonl", workers=1, client=stub, budget=budget, writer_model=W, checker_model=C)
    assert summ["n"] == 3 and summ["llm"] == 1 and summ["template"] == 2 and summ["cap_hit"]
    assert abs(summ["cost_usd"] - 0.12) < 1e-9 and stub.n(W) == 1 and stub.n(C) == 1
    by = {d["doc_id"]: d for d in summ["docs"]}
    assert by["doc:night_lead_statement"]["rendered_by"] == "llm" and by["doc:second"]["fallback_reason"] == "cost_cap"
    assert by["doc:chat_2026-05-23"]["fallback_reason"] == "cost_cap"
    assert (out / "people/statements/second.md").read_text() == FALLBACK
    chat = json.loads((out / "people/chat_export.json").read_text())
    assert [m["id"] for m in chat] == ["m0001", "m0002", "m0003"] and chat[0]["user"] == "alerting-bot"
    s, e = summ["chat"]["spans"]["fc09"]
    assert (out / "people/chat_export.json").read_text()[s:e] == REQ and summ["chat"]["claims"]["fc09"]["count"] == 1
    events = [json.loads(l)["event"] for l in (tmp_path / "log.jsonl").read_text().splitlines()]
    assert events[0] == "batch_start" and events[-1] == "batch_end" and "checker_call" in events


def test_render_all_parallel_writes_everything(tmp_path):
    sheets = tmp_path / "sheets"
    sheets.mkdir()
    for i in range(4):
        s = statement_sheet()
        s["doc_id"], s["path"] = f"doc:s{i}", f"people/statements/s{i}.md"
        (sheets / f"s{i}.json").write_text(json.dumps(s))
    (sheets / "chat.json").write_text(json.dumps(chat_sheet()))
    # the stub's writer queue serves GOOD to statements; chat needs JSON -> give it a client that branches on the brief
    class Branch(Stub):
        def __call__(self, model, messages, temperature, max_tokens):
            if model == W and "MESSAGE COUNT" in messages[1]["content"]:
                self.calls.append({"model": model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens})
                return chat_json(), {"cost": self.cost}
            return super().__call__(model, messages, temperature, max_tokens)
    stub = Branch(writer=[GOOD], cost=0.001)
    summ = docs_llm.render_all(sheets, tmp_path / "ev", tmp_path / "log.jsonl", workers=4, client=stub, budget=docs_llm.Budget(cap_usd=5.0), writer_model=W, checker_model=C)
    assert summ["llm"] == 5 and summ["template"] == 0 and not summ["cap_hit"]
    assert all((tmp_path / "ev" / f"people/statements/s{i}.md").read_text().startswith("# Statement") for i in range(4))
    assert summ["chat"]["n_messages"] == 4 and summ["chat"]["llm_days"] == 1
    assert abs(summ["cost_usd"] - 0.009) < 1e-9        # 4 x (writer + checker) + 1 chat writer


def test_client_error_is_retried_then_template():
    class Boom(Stub):
        def __call__(self, *a):
            self.calls.append(a)
            raise RuntimeError("OpenRouter HTTP 500")
    stub = Boom()
    res = R(statement_sheet(), stub)
    assert res["rendered_by"] == "template" and res["fallback_reason"] == "client_error" and len(stub.calls) == 3


def test_env_loader_and_prompt_files(tmp_path):
    p = tmp_path / ".env"
    p.write_text("# c\nexport A=1\nB='two'\nC=\"3\"\nbad\n")
    assert docs_llm.load_env(p) == {"A": "1", "B": "two", "C": "3"}
    for k in ("statement", "chat_day", "ticket", "email", "report", "memo", "generic"):
        assert (docs_llm.PROMPTS / f"writer_{k}.txt").exists()
    assert docs_llm._prompt_for("nonexistent_kind") == docs_llm._prompt_for("generic")


# ---------------------------------------------------------------- live (spends money; EVAL_DOCS_LIVE=1)
LIVE_SHEET = {
    "doc_id": "doc:night_lead_statement", "path": "people/statements/night_lead_l.okafor.md", "kind": "statement",
    "author": {"name": "Lena Okafor", "handle": "l.okafor", "role": "night shift lead",
               "persona": "defensive, terse, proud of her routine, blames the equipment rather than people", "tz": "Europe/Oslo"},
    "audience": "internal investigation", "length_words": [220, 380],
    "header": "# Statement — Lena Okafor (night shift lead)\nTaken 2026-05-28",
    "must_include": [
        {"fact_id": "E17", "text": "came on shift at about 21:48 on the night of 23 May 2026"},
        {"fact_id": "E18", "text": "the agency temp, Lena Rivera, was on the same shift"},
        {"fact_id": "E19", "text": "did the walk-through of all six cold rooms at 00:18"},
        {"fact_id": "E20", "text": "the compressor on controller VX05 (room E) has sounded rough for weeks and this was said in the shift handover more than once"},
        {"fact_id": "E21", "text": "first heard of any problem when the customer's stability lab e-mailed about a lot"},
    ],
    "verbatim": [{"claim_id": "fc01", "text": FC01}, {"claim_id": "fc07", "text": FC07}],
    "may_mention": ["the corridor being quiet at night", "the cold and the heavy doors", "the dashboard screen in the office"],
    "must_not_mention": ["the wedge", "the door being propped", "the photo"],
    "forbidden_strings": ["truth", "simulat", "generated", "fictional", "ledger.sql"],
    "allowed_entities": ["VX05", "room E", "Lena Rivera", "Lena Okafor"],
    "style_notes": "first person, no headings, one paragraph per topic, 24-hour clock times as she would write them on the shift log",
    "fallback": FALLBACK,
}


@pytest.mark.skipif(os.environ.get("EVAL_DOCS_LIVE") != "1", reason="set EVAL_DOCS_LIVE=1 to spend money on one live render")
def test_live_statement_render(tmp_path):
    budget = docs_llm.Budget(cap_usd=0.50)
    res = docs_llm.render(dict(LIVE_SHEET), log_path=tmp_path / "live_log.jsonl", budget=budget)
    out = {k: res[k] for k in ("rendered_by", "attempts", "verification", "spans", "cost_usd", "fallback_reason")}
    print("\n=== LIVE RENDER ===\n" + res["text"] + "\n=== RESULT ===\n" + json.dumps(out, indent=1, ensure_ascii=False))
    live_out = os.environ.get("EVAL_DOCS_LIVE_OUT")
    if live_out:
        Path(live_out).write_text(json.dumps({"text": res["text"], **out, "log": (tmp_path / "live_log.jsonl").read_text()}, indent=1, ensure_ascii=False))
    assert res["rendered_by"] == "llm", res["attempts"]
    assert res["verification"]["ok"] and res["verification"]["checker"]["missing"] == []
    assert res["cost_usd"] < 0.20 and budget.spent < 0.20
    for cid, vt in (("fc01", FC01), ("fc07", FC07)):
        s, e = res["spans"][cid]
        assert res["text"][s:e] == vt
