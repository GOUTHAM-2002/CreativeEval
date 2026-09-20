"""The four solver tools: one definition rendered for MCP and OpenAI, and the host-side Executor that runs them
through the bwrap sandbox, logs to run_dir/tool_log.jsonl and snapshots /work/answer.json after every call."""
from __future__ import annotations

import hashlib
import json
import os
import posixpath
import re
import stat
import subprocess
import sys
import time
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from sandbox import exec as sbx  # noqa: E402

OUT_CAP = 16 * 1024
ERR_CAP = 4 * 1024
DEFAULT_TIMEOUT = 60
MAX_TIMEOUT = 120
MAX_ANSWER_BYTES = 16 * 1024 * 1024
ALLOWED_ROOTS = ("/evidence", "/work", "/home/agent", "/tmp")
VENV_PY = PROJECT / ".venv" / "bin" / "python"
GRADER_VALIDATE = PROJECT / "grader" / "validate.py"
GREP_FLAG_RE = re.compile(r"^(-{1,2}[A-Za-z0-9][A-Za-z0-9=*.,_/?-]*|[0-9]+)$")

TOOLS = [
    {"name": "read_file",
     "description": "Read a text file with line numbers. `path` is relative to /evidence, or absolute under /evidence "
                    "or /work. Optional 1-based inclusive `start_line` / `end_line`. Output is capped at 16 KB, so read "
                    "long files in ranges. A directory path returns its listing.",
     "parameters": {"type": "object", "additionalProperties": False, "required": ["path"],
                    "properties": {"path": {"type": "string"},
                                   "start_line": {"type": "integer", "minimum": 1},
                                   "end_line": {"type": "integer", "minimum": 1}}}},
    {"name": "grep",
     "description": "Search with `grep -rnE` (extended regex, recursive, line numbers) inside the sandbox. `path` "
                    "defaults to /evidence; relative paths are under /evidence. `flags` is an optional string of extra "
                    "grep flags, e.g. \"-i -l\", \"-A 3\", \"--include=*.log\", \"-c\". Output is capped at 16 KB.",
     "parameters": {"type": "object", "additionalProperties": False, "required": ["pattern"],
                    "properties": {"pattern": {"type": "string"}, "path": {"type": "string"}, "flags": {"type": "string"}}}},
    {"name": "bash",
     "description": "Run a bash command in the sandbox. cwd is /work (persistent, writable); /evidence is read-only; "
                    "/tmp is wiped between calls; no network. Default timeout 60 s, maximum 120 s. stdout is capped at "
                    "16 KB and stderr at 4 KB; write longer results to files under /work and read them in pieces.",
     "parameters": {"type": "object", "additionalProperties": False, "required": ["cmd"],
                    "properties": {"cmd": {"type": "string"}, "timeout_s": {"type": "integer", "minimum": 1, "maximum": MAX_TIMEOUT}}}},
    {"name": "validate_answer",
     "description": "Validate /work/answer.json against /evidence/ANSWER_SCHEMA.json. Returns {schema_valid, errors}. "
                    "This checks JSON-schema conformance only; it does not score or compare anything.",
     "parameters": {"type": "object", "additionalProperties": False, "properties": {}}},
]
TOOL_NAMES = tuple(t["name"] for t in TOOLS)

VALIDATE_SRC = r'''
import json, sys
import jsonschema
schema = json.load(open(sys.argv[1]))
try:
    inst = json.load(open(sys.argv[2]))
except ValueError as e:
    print(json.dumps({"schema_valid": False, "errors": [f"/work/answer.json is not valid JSON: {e}"[:300]]})); sys.exit(0)
v = jsonschema.Draft202012Validator(schema)
errs = sorted(v.iter_errors(inst), key=lambda e: (len(e.absolute_path), str(list(e.absolute_path))))
msgs = []
for e in errs:
    loc = "/".join(str(p) for p in e.absolute_path) or "$"
    msgs.append(f"{loc}: {e.message}"[:300])
    if len(msgs) >= 20: break
print(json.dumps({"schema_valid": not errs, "errors": msgs}))
'''

READ_SCRIPT = r'''
f="$1"; s="$2"; e="$3"
if [ ! -e "$f" ]; then echo "no such file: $f" >&2; exit 2; fi
if [ -d "$f" ]; then echo "[directory listing] $f"; ls -la -- "$f"; exit 0; fi
if [ ! -r "$f" ]; then echo "not readable: $f" >&2; exit 2; fi
awk -v s="$s" -v e="$e" 'NR>=s { if (e>0 && NR>e) exit; printf "%d\t%s\n", NR, $0 }' "$f"
'''


def mcp_tool_list() -> list[dict]:
    return [{"name": t["name"], "description": t["description"], "inputSchema": t["parameters"]} for t in TOOLS]


def openai_tool_list() -> list[dict]:
    return [{"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["parameters"]}}
            for t in TOOLS]


class ToolError(Exception):
    pass


def _truncate(text: str, cap: int, hint: str = "") -> str:
    if len(text) <= cap:
        return text
    return text[:cap] + f"\n[truncated: showing {cap} of {len(text)} bytes{hint}]"


def resolve_path(path, default_root: str = "/evidence") -> str:
    if not isinstance(path, str) or not path.strip():
        raise ToolError("path must be a non-empty string")
    p = path.strip()
    if not p.startswith("/"):
        p = posixpath.join(default_root, p)
    p = posixpath.normpath(p)
    if not any(p == r or p.startswith(r + "/") for r in ALLOWED_ROOTS):
        raise ToolError("path must be under /evidence or /work")
    return p


def read_answer_bytes(run_dir: Path):
    p = Path(run_dir) / "work" / "answer.json"
    try:
        fd = os.open(str(p), os.O_RDONLY | os.O_NOFOLLOW | os.O_NOCTTY)
    except OSError:
        return None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size > MAX_ANSWER_BYTES:
            return None
        chunks = []
        while True:
            b = os.read(fd, 1 << 20)
            if not b:
                break
            chunks.append(b)
        return b"".join(chunks)
    finally:
        os.close(fd)


def validate_answer(run_dir: Path) -> dict:
    run_dir = Path(run_dir)
    schema = os.path.realpath(run_dir / "evidence" / "ANSWER_SCHEMA.json")
    data = read_answer_bytes(run_dir)
    if data is None:
        return {"schema_valid": False, "errors": ["/work/answer.json not found (or not a regular file)"]}
    tmp = run_dir / ".answer_check.json"
    tmp.write_bytes(data)
    if not VENV_PY.exists():
        return {"schema_valid": None, "errors": ["validator unavailable"]}
    cmds = []
    if GRADER_VALIDATE.exists():
        cmds.append([str(VENV_PY), str(GRADER_VALIDATE), "--schema", schema, str(tmp)])
    cmds.append([str(VENV_PY), "-c", VALIDATE_SRC, schema, str(tmp)])
    for cmd in cmds:
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=60, cwd=str(PROJECT), env={"PATH": "/usr/bin:/bin"})
            res = json.loads(p.stdout.strip().splitlines()[-1])
            if isinstance(res, dict) and "schema_valid" in res:
                return {"schema_valid": res["schema_valid"], "errors": [str(m)[:300] for m in (res.get("errors") or [])][:20]}
        except (subprocess.SubprocessError, ValueError, IndexError, OSError):
            continue
    return {"schema_valid": None, "errors": ["validator failed"]}


class Executor:
    def __init__(self, run_dir, tier: str = "default", project=None, extra_redactions=()):
        self.run_dir = Path(run_dir).resolve()
        self.tier = tier
        self.project = Path(project or PROJECT).resolve()
        self.log_path = self.run_dir / "tool_log.jsonl"
        self.hist = self.run_dir / "answer_history"
        self.hist.mkdir(exist_ok=True)
        self.seq, self.n_calls, self.n_validate = 0, 0, 0
        if self.log_path.exists():
            for line in self.log_path.read_text().splitlines():
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                self.seq = max(self.seq, int(row.get("seq") or 0))
                if row.get("tool") in TOOL_NAMES:
                    self.n_calls += 1
                    self.n_validate += row.get("tool") == "validate_answer"
        self.last_sha = None
        snaps = sorted(self.hist.glob("[0-9][0-9][0-9][0-9].json"))
        if snaps:
            self.last_sha = hashlib.sha256(snaps[-1].read_bytes()).hexdigest()
        store = None
        try:
            store = json.loads((self.run_dir / "store.json").read_text()).get("store")
        except (OSError, ValueError):
            pass
        reds = [(str(self.run_dir), "[run]"), (str(self.project), "[project]"), (os.path.expanduser("~"), "/home/agent")]
        if store:
            reds.append((str(store), "[store]"))
        reds += [(str(r), "[redacted]") for r in extra_redactions if r]
        self._redactions = sorted((r for r in reds if r[0] and r[0] != "/"), key=lambda t: len(t[0]), reverse=True)
        self._fns = {"read_file": self._read_file, "grep": self._grep, "bash": self._bash, "validate_answer": self._validate}

    def redact(self, text: str) -> str:
        for raw, repl in self._redactions:
            text = text.replace(raw, repl)
        return text

    def _run(self, argv, timeout):
        return sbx.run_in_sandbox(self.run_dir, self.tier, argv, timeout_s=timeout)

    def _read_file(self, a: dict) -> dict:
        p = resolve_path(a.get("path"))
        s = int(a.get("start_line") or 1)
        e = int(a.get("end_line") or 0)
        if s < 1 or e < 0 or (e and e < s):
            raise ToolError("start_line/end_line must be positive and end_line >= start_line")
        rc, out, err = self._run(["bash", "-c", READ_SCRIPT, "rf", p, str(s), str(e)], DEFAULT_TIMEOUT)
        text = _truncate(out, OUT_CAP, "; use start_line/end_line")
        if err.strip():
            text += ("\n" if text else "") + _truncate(err, ERR_CAP)
        return {"text": text, "exit": rc, "stdout_len": len(out), "stderr_len": len(err)}

    def _grep(self, a: dict) -> dict:
        pat = a.get("pattern")
        if not isinstance(pat, str) or not pat:
            raise ToolError("pattern must be a non-empty string")
        p = resolve_path(a.get("path") or "/evidence")
        toks = str(a.get("flags") or "").split()
        bad = [t for t in toks if not GREP_FLAG_RE.match(t)]
        if bad:
            raise ToolError(f"unsupported grep flags: {' '.join(bad)}")
        rc, out, err = self._run(["grep", "-rnE", *toks, "-e", pat, "--", p], DEFAULT_TIMEOUT)
        if rc == 1 and not out and not err.strip():
            out = "(no matches)"
        text = _truncate(out, OUT_CAP, "; narrow the pattern, path or flags")
        if err.strip():
            text += ("\n" if text else "") + _truncate(err, ERR_CAP)
        return {"text": text, "exit": 0 if rc == 1 else rc, "stdout_len": len(out), "stderr_len": len(err)}

    def _bash(self, a: dict) -> dict:
        cmd = a.get("cmd")
        if not isinstance(cmd, str) or not cmd.strip():
            raise ToolError("cmd must be a non-empty string")
        try:
            timeout = int(a.get("timeout_s") or DEFAULT_TIMEOUT)
        except (TypeError, ValueError):
            timeout = DEFAULT_TIMEOUT
        timeout = max(1, min(timeout, MAX_TIMEOUT))
        rc, out, err = self._run(["bash", "-lc", cmd], timeout)
        text = f"exit={rc}\n--- stdout ---\n{_truncate(out, OUT_CAP)}\n--- stderr ---\n{_truncate(err, ERR_CAP)}"
        return {"text": text, "exit": rc, "stdout_len": len(out), "stderr_len": len(err)}

    def _validate(self, a: dict) -> dict:
        res = validate_answer(self.run_dir)
        text = json.dumps(res)
        return {"text": text, "exit": 0 if res.get("schema_valid") else 1, "stdout_len": len(text), "stderr_len": 0}

    def answer_status(self) -> dict:
        data = read_answer_bytes(self.run_dir)
        if data is None:
            return {"exists": False, "valid_json": False, "schema_valid": False}
        try:
            json.loads(data)
            vj = True
        except ValueError:
            vj = False
        return {"exists": True, "valid_json": vj, "schema_valid": bool(vj and validate_answer(self.run_dir).get("schema_valid"))}

    def _log(self, tool: str, args, res: dict, ms: float) -> None:
        self.seq += 1
        row = {"seq": self.seq, "tool": tool, "args": args, "exit": res.get("exit"), "stdout_len": res.get("stdout_len", 0),
               "stderr_len": res.get("stderr_len", 0), "t": round(time.time(), 3), "ms": round(ms, 1),
               "preview": self.redact(res.get("text", ""))[:600]}
        with open(self.log_path, "a") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def snapshot(self):
        data = read_answer_bytes(self.run_dir)
        if data is None:
            return None
        sha = hashlib.sha256(data).hexdigest()
        if sha == self.last_sha:
            return None
        self.last_sha = sha
        n = len(list(self.hist.glob("[0-9][0-9][0-9][0-9].json"))) + 1
        name = f"{n:04d}.json"
        (self.hist / name).write_bytes(data)
        try:
            json.loads(data)
            valid = True
        except ValueError:
            valid = False
        self._log("snapshot", {"file": name, "sha256": sha[:16], "bytes": len(data), "valid_json": valid},
                  {"exit": 0, "stdout_len": 0, "stderr_len": 0, "text": ""}, 0)
        return name

    def call(self, name: str, args) -> dict:
        t0 = time.time()
        args = args if isinstance(args, dict) else {}
        fn = self._fns.get(name)
        if fn is None:
            res = {"text": f"unknown tool: {name}", "exit": 2, "stdout_len": 0, "stderr_len": 0}
        else:
            try:
                res = fn(args)
            except ToolError as e:
                res = {"text": f"[sandbox] {e}", "exit": 2, "stdout_len": 0, "stderr_len": 0}
            except Exception:  # noqa: BLE001
                res = {"text": "[sandbox] internal error running tool", "exit": 1, "stdout_len": 0, "stderr_len": 0}
        self.n_calls += fn is not None
        self.n_validate += name == "validate_answer"
        self._log(name, args, res, (time.time() - t0) * 1000)
        try:
            self.snapshot()
        except Exception:  # noqa: BLE001
            pass
        return {"text": self.redact(res["text"]), "is_error": res["exit"] != 0, "exit": res["exit"]}
