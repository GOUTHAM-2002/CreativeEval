# harness / sandbox / dashboard

Solver runs in a bwrap sandbox with four tools (`read_file`, `grep`, `bash`, `validate_answer`) defined once in
`harness/tools.py` and rendered for MCP (`claude -p` route) and OpenAI-style tool calling (OpenRouter route).
Every tool call goes through one `bwrap` exec (`sandbox/exec.py`), is logged host-side to `tool_log.jsonl`, and is
followed by a snapshot of `/work/answer.json` into `answer_history/NNNN.json` if its sha256 changed.
Layout and file formats: `contract/INTERFACE.md` §7 and §8.

## Run

```
# $0: scripted agent end to end (stub instance) -> runs/test/fake/stub_instance/
.venv/bin/python harness/run.py --fake --instance contract/stub_instance --tag test

# containment self-test on an existing run dir (both tiers; --quick is what run.py does before every launch)
.venv/bin/python sandbox/selftest.py --run-dir runs/test/fake/stub_instance --tier default
.venv/bin/python sandbox/selftest.py --run-dir runs/test/fake/stub_instance --tier no_compute

# cheap paid smoke: Haiku 4.5 via claude -p over OpenRouter, 60 tool calls, $5 backstop
.venv/bin/python harness/run.py --model haiku4.5 --instance instances/s0001_xxxxxxxx --tag smoke --max-tool-calls 60 --budget-usd 5

# matrix: instance-major round robin, N parallel, hard tag cap in runs/<tag>/ledger.json
.venv/bin/python harness/run_matrix.py --tag pilot --models fable5.1,opus5,astra --instances 'instances/s000*' \
    --par 4 --cap-usd 600 --max-tool-calls 600 --wall-s 18000 --budget-usd 150 --effort high
.venv/bin/python harness/run_matrix.py --tag pilot ... --retry-errors     # re-run api_error/harness_error cells (old dir kept as *.failedN)

# dashboard (read-only) on :8895
.venv/bin/python dashboard/server.py --port 8895

# tests ($0)
.venv/bin/python -m pytest validation/test_sandbox.py validation/test_smoke_fake.py -q
```

Model keys (`harness/prices.py`): `fable5.1 fable5 opus5 sonnet5 haiku4.5` -> `claude -p` route (OpenRouter slugs
`anthropic/claude-*`); `astra sol` -> OpenRouter chat.completions (`openai/gpt-6-astra`, `openai/gpt-5.6-sol`); `fake`.
`--via openrouter` (default) funds `claude -p` through OpenRouter (`ANTHROPIC_BASE_URL`/`ANTHROPIC_AUTH_TOKEN`);
`--via api` uses `ANTHROPIC_API_KEY` and the Anthropic model id; `--via subscription` drops `--bare` (OAuth is not
read under `--bare`) and is best-effort only.

## Env vars

| var | where | meaning |
|---|---|---|
| `OPENROUTER_API_KEY`, `ANTHROPIC_API_KEY` | `.env` (see `.env.example`) | read by `run.py`, passed only to the model process; never to the sandbox |
| `EVAL_STORE` | host | neutral staging root for bind sources (default `/var/tmp/.sbx`); tests point it at a tmp dir |
| `EVAL_GLOBAL_CAP`, `EVAL_GLOBAL_LEDGER` | host | project-wide odometer cap (default $2000) and file (`runs/global_spend.json`) |
| `EVAL_CLAUDE_BIN` | host | claude binary (default `~/.local/bin/claude`) |
| `EVAL_OR_URL`, `EVAL_OR_MAX_TOKENS` | host | OpenRouter endpoint override (tests) and `max_tokens` (16000) |
| `EVAL_RUN_DIR`, `EVAL_TIER`, `EVAL_PROJECT` | MCP server | set by `cc_route.py` in the mcp config; read once, then the server scrubs `KEY|TOKEN|SECRET|ANTHROPIC|OPENROUTER|OPENAI|AWS` from its env |

`claude -p` guards set by `cc_route.py`: `DISABLE_COMPACT=1 DISABLE_AUTO_COMPACT=1 CLAUDE_CODE_NO_MODEL_FALLBACK=true
CLAUDE_CODE_MAX_CONTEXT_TOKENS=1000000 MAX_MCP_OUTPUT_TOKENS=200000 ENABLE_MCP_LARGE_OUTPUT_FILES=false
ENABLE_PROMPT_CACHING_1H=1 MCP_TOOL_TIMEOUT=600000 DISABLE_TELEMETRY=1 CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`;
`CLAUDECODE`, `CLAUDE_CODE_ENTRYPOINT` and any inherited Anthropic credential are popped. Flags: `--bare --tools ""
--strict-mcp-config --mcp-config <run_dir>/mcp_config.json --allowedTools mcp__sandbox --permission-mode
bypassPermissions --output-format stream-json --verbose --max-turns 2*max_tool_calls --max-budget-usd <budget>
--append-system-prompt <prompts.SYSTEM> --session-id <uuid> [--effort]`. claude itself runs inside a mount
namespace whose cwd is `/work` (an empty dir), so no host path appears in its own system prompt; that namespace keeps
the network. The `system/init` event must list the `sandbox` server as connected and exactly the four
`mcp__sandbox__*` tools, else `end_reason=harness_error`; any other tool name is recorded in `invalid_markers`.

## Caps and end reasons

Per episode (identical across models): `--max-tool-calls 600`, `--wall-s 18000`, `--budget-usd 150`. Per tool call:
60 s default / 120 s max, stdout 16 KB, stderr 4 KB. Inside the sandbox: `ulimit -t 120 -v 4194304 -u 128 -f 2097152`.
`end_reason` in {`stopped`, `tool_cap`, `wall_cap`, `budget_cap`, `context_limit`, `content_filter`, `api_error`,
`harness_error`}; `end_detail` carries the specifics. Both routes stop when the model stops calling tools; the
OpenRouter route sends one nudge (`prompts.NUDGE`) if that happens while `answer.json` is missing or schema-invalid,
the claude route cannot (claude -p ends the process). `cost_usd` is the reported figure (`result.total_cost_usd`,
`usage.cost`), `cost_estimate_usd` comes from `prices.py` (UNVERIFIED placeholders); the matrix ledger charges the
larger of the two.

## Sandbox

Tier `default`: `/usr` read-only (python3 stdlib available). Tier `no_compute`: `--tmpfs /usr/bin` plus a read-only
bind of each name in `sandbox/toolbox.txt` (missing on this box and skipped: `jq`, `node`), tmpfs over
`/usr/lib/python3*`, `/usr/sbin`, `/usr/libexec`, `/usr/local`, perl/ruby/node lib dirs; all remounted read-only.
Both tiers: `--clearenv --unshare-user --unshare-pid --unshare-net --unshare-uts --unshare-ipc`, uid 1000 `agent`,
synthetic `/etc/{passwd,group,hostname,hosts}`, `/evidence` ro, `/work` rw (cwd), `/home/agent` rw, `/tmp` tmpfs
(wiped per call), `--die-with-parent --new-session`, env = HOME USER LOGNAME PATH LANG TERM TZ=UTC only.

Bind sources are staged, not bound from the run dir: `/proc/*/mountinfo` inside bwrap shows the host path of every
bind source (superblock-relative, so symlinks and outer namespaces do not hide it). `sandbox/exec.prepare_run_dir`
therefore creates `EVAL_STORE/<random16>/{evidence,work,home,etc}` (evidence as a `cp -al` hardlink tree, falling
back to a copy across filesystems; mtimes preserved) and symlinks `run_dir/{evidence,work,home,etc}` to it.
`run_dir/store.json` records the store; `python sandbox/exec.py purge <run_dir>` deletes it. What remains visible
in mountinfo is the numeric host uid in the tmpfs options and `/usr`, `/etc/*` paths.

## Run directory

`runs/<tag>/<model_key>/<inst_id>/` (`<inst_id>+<tier>` for non-default tiers): `episode.json`, `transcript.jsonl`,
`tool_log.jsonl` (+ `snapshot` rows), `usage.jsonl`, `answer_history/`, `answer.json` (last valid-JSON snapshot),
`score.json` (grader), plus host-only extras: `run_meta.json`, `store.json`, `selftest.txt`, `mcp_config.json`,
`cc_stream.jsonl`, `cc_stderr.txt`, `mcp_server.log`, `messages.json` / `or_state.json` (OpenRouter resume),
`harness_error.txt`. A cell with `episode.json` is skipped by `run.py` and `run_matrix.py`. An OpenRouter cell
interrupted before `episode.json` resumes from `messages.json` when `run.py` is invoked again on it.
