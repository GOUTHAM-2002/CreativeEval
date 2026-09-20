#!/usr/bin/env python3
"""Containment self-test: runs probe commands inside the sandbox from the host and asserts on what they see.
Works for both tiers (no interpreter is needed inside). Usage: selftest.py --run-dir <dir> --tier default|no_compute [--quick]"""
from __future__ import annotations

import argparse
import json
import os
import re
import socket
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from sandbox import exec as sbx  # noqa: E402

SECRET_RE = re.compile(r"KEY|TOKEN|SECRET|ANTHROPIC|OPENROUTER|OPENAI|AWS", re.I)
HOST_FILES = ["truth.json", "world.json", "build.log", "tool_log.jsonl", "episode.json", "transcript.jsonl", "store.json"]


def make_checks(run_dir: Path, tier: str, quick: bool):
    host_home = os.path.expanduser("~")
    store = json.loads((run_dir / "store.json").read_text())
    forbidden = [host_home, "eval_imp", "truth", str(run_dir), str(Path(store["evidence_src"]).parent), str(HERE.parent)]
    forbidden = [f for f in forbidden if f and f != "/"]

    def sh(cmd, timeout=20):
        return sbx.run_in_sandbox(run_dir, tier, ["bash", "-c", cmd], timeout_s=timeout)

    def none_of(text, needles):
        return [n for n in needles if n in text]

    checks = []

    def check(name, fn, quick_ok=True):
        checks.append((name, fn, quick_ok))

    def net_tcp():
        rc, out, err = sh("timeout 5 bash -c 'echo > /dev/tcp/1.1.1.1/80'", 10)
        return rc != 0 and "unreachable" in (out + err).lower(), (out + err)[-200:]
    check("no_network_tcp", net_tcp)

    if tier == "default":
        def net_py():
            rc, out, err = sh("python3 -c 'import socket,sys\ns=socket.socket();s.settimeout(3)\n"
                              "try:\n s.connect((\"1.1.1.1\",80));print(\"CONNECTED\")\nexcept OSError as e:\n print(\"fail\",e)'", 15)
            return "CONNECTED" not in out and "fail" in out, out[-200:]
        check("no_network_python", net_py, quick_ok=False)

        def py_stdlib():
            rc, out, err = sh("python3 -c 'import json,re,sqlite3,statistics,itertools; print(\"ok\")'", 15)
            return rc == 0 and out.strip() == "ok", (out + err)[-200:]
        check("python3_stdlib_available", py_stdlib, quick_ok=False)
    else:
        def no_interp():
            rc, out, err = sh("for x in python3 python perl ruby node; do command -v $x && echo FOUND:$x; which $x && echo FOUND:$x; done; "
                              "find /usr/lib/python3.10 /usr/local /usr/sbin -mindepth 1 2>/dev/null | wc -l")
            lines = out.strip().splitlines()
            return "FOUND" not in out and lines and lines[-1].strip() == "0", out[-300:]
        check("no_interpreters", no_interp)

        def toolbox_ok():
            rc, out, err = sh("ls /evidence | head -3 | grep -c . ; echo a | sed s/a/b/ | awk '{print $1}' | tr b c; git --version >/dev/null && echo git-ok")
            return rc == 0 and "c" in out and "git-ok" in out, (out + err)[-300:]
        check("toolbox_works", toolbox_ok)

    def ev_ro():
        rc, out, err = sh("touch /evidence/.w 2>&1; echo rc=$?; rm -f /evidence/TASK.md 2>&1; test -e /evidence/TASK.md && echo still-there")
        return "Read-only" in out and "still-there" in out, out[-200:]
    check("evidence_readonly", ev_ro)

    def ev_readable():
        rc, out, err = sh("head -c 200 /evidence/TASK.md")
        return rc == 0 and len(out) > 10, (out + err)[-200:]
    check("evidence_readable", ev_readable)

    def work_rw():
        rc, out, err = sh("echo x > /work/.selftest && cat /work/.selftest && rm /work/.selftest && pwd")
        return rc == 0 and out.strip().endswith("/work"), (out + err)[-200:]
    check("work_writable_cwd", work_rw)

    def tmp_home_rw():
        rc, out, err = sh("echo x > /tmp/.t && echo y > /home/agent/.t && rm /home/agent/.t && echo $HOME && ls /home")
        return rc == 0 and out.split() == ["/home/agent", "agent"], (out + err)[-200:]
    check("tmp_and_home_writable", tmp_home_rw)

    def mountinfo():
        rc, out, err = sh("cat /proc/self/mountinfo /proc/1/mountinfo /proc/mounts 2>/dev/null")
        hits = none_of(out, forbidden)
        return rc == 0 and not hits and " /evidence " in out, f"hits={hits}"
    check("no_host_paths_in_mountinfo", mountinfo)

    def env_clean():
        rc, out, err = sh("env")
        bad = [l for l in out.splitlines() if SECRET_RE.search(l.split("=", 1)[0])]
        hits = none_of(out, forbidden)
        return rc == 0 and not bad and not hits and "HOME=/home/agent" in out, f"bad={bad} hits={hits}"
    check("env_has_no_secrets_or_host_paths", env_clean)

    def no_host_files():
        names = " -o ".join(f"-name {n}" for n in HOST_FILES)
        rc, out, err = sh(f"find / -path /proc -prune -o -path /sys -prune -o \\( {names} \\) -print 2>/dev/null; "
                          f"find / -xdev -name truth.json 2>/dev/null; ls /evidence/../truth.json /work/../truth.json 2>&1 | grep -v 'No such'", 60)
        return out.strip() == "", out[-300:]
    check("host_only_files_unreachable", no_host_files)

    def ids():
        rc, out, err = sh("id -u; id -un; id -g; grep -c goutham /etc/passwd; cat /etc/hostname")
        lines = out.split()
        return rc == 0 and lines[:4] == ["1000", "agent", "1000", "0"] and lines[4] != socket.gethostname(), out[-200:]
    check("uid_1000_agent_synthetic_etc", ids)

    def procs():
        rc, out, err = sh("ps -eo pid,comm; cat /proc/1/comm")
        lines = [l for l in out.strip().splitlines() if l.strip()]
        names = " ".join(lines).lower()
        return rc == 0 and len(lines) <= 8 and not any(x in names for x in ("claude", "python3.12", "systemd", "node", "sshd")), out[-300:]
    check("pid_namespace_no_host_processes", procs)

    def ulimits():
        rc, out, err = sh("ulimit -t; ulimit -u; ulimit -v")
        return out.split() == ["120", "128", "4194304"], out[-100:]
    check("ulimits_applied", ulimits, quick_ok=False)

    def usr_ro():
        rc, out, err = sh("touch /usr/bin/.x 2>&1; touch /etc/.x 2>&1; echo done")
        return "Read-only" in out or "Permission denied" in out, out[-200:]
    check("usr_etc_readonly", usr_ro, quick_ok=False)

    def timeout_kill():
        rc, out, err = sh("sleep 30; echo late", 2)
        return rc == 124 and "late" not in out, (out + err)[-200:]
    check("timeout_kills_command", timeout_kill, quick_ok=False)

    if quick:
        checks = [c for c in checks if c[2]]
    return checks


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--tier", default="default", choices=sbx.TIERS)
    ap.add_argument("--quick", action="store_true")
    a = ap.parse_args()
    run_dir = Path(a.run_dir).resolve()
    checks = make_checks(run_dir, a.tier, a.quick)
    passed = 0
    for name, fn, _ in checks:
        try:
            ok, detail = fn()
        except Exception as exc:  # noqa: BLE001
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        passed += bool(ok)
        print(f"[{'ok' if ok else 'FAIL'}] {name}" + ("" if ok else f"  -- {detail!s}"[:400]))
    print(f"{passed}/{len(checks)} passed (tier={a.tier}{', quick' if a.quick else ''})")
    return 0 if passed == len(checks) else 1


if __name__ == "__main__":
    sys.exit(main())
