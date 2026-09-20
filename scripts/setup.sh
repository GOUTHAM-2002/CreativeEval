#!/usr/bin/env bash
# One-time setup: Python venv, deps, libfaketime (built from source, no root needed).
set -euo pipefail
cd "$(dirname "$0")/.."
command -v bwrap >/dev/null || { echo "bubblewrap (bwrap) is required: apt install bubblewrap"; exit 1; }
command -v gcc >/dev/null || { echo "gcc/make are required to build libfaketime"; exit 1; }
if command -v uv >/dev/null; then uv venv -q .venv --python 3.12 2>/dev/null || uv venv -q .venv; uv pip install -q --python .venv/bin/python -r requirements.txt
else python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt; fi
if [ ! -f tools/faketime/lib/libfaketimeMT.so.1 ]; then
  mkdir -p tools/faketime && git clone -q --depth 1 https://github.com/wolfcw/libfaketime.git tools/faketime/src
  make -s -C tools/faketime/src/src >/dev/null
  mkdir -p tools/faketime/lib && cp tools/faketime/src/src/libfaketime.so.1 tools/faketime/src/src/libfaketimeMT.so.1 tools/faketime/lib/
fi
[ -f .env ] || cp .env.example .env
echo "ok: .venv, tools/faketime/lib, .env (add OPENROUTER_API_KEY to .env for LLM-written documents, model runs and judging)"
