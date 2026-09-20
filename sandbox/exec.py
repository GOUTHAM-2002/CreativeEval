"""bwrap sandbox for the solver: run-dir staging, argv builder, one-shot exec. stdlib only; runs on python 3.10+.

Bind sources are staged under a neutral store dir (default /var/tmp/.sbx/<random>) because /proc/*/mountinfo
inside bwrap shows the host path of every bind source; the run dir keeps symlinks to the store."""
from __future__ import annotations

import glob
import json
import os
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLBOX = HERE / "toolbox.txt"
BWRAP = shutil.which("bwrap") or "/usr/bin/bwrap"
TIERS = ("default", "no_compute")
AGENT_UID = 1000
AGENT_USER = "agent"
DEFAULT_STORE = "/var/tmp/.sbx"
STAGED = ("evidence", "work", "home", "etc")
ULIMIT_WRAP = 'ulimit -t 120 -v 4194304 -u 128 -f 2097152 2>/dev/null; exec "$@"'
HOST_ENV = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}

PASSWD = (
    "root:x:65534:65534:root:/root:/bin/bash\n"
    "daemon:x:1:1:daemon:/usr/sbin:/usr/sbin/nologin\n"
    f"{AGENT_USER}:x:{AGENT_UID}:{AGENT_UID}::/home/{AGENT_USER}:/bin/bash\n"
    "nobody:x:65533:65533:nobody:/nonexistent:/usr/sbin/nologin\n"
)
GROUP = f"root:x:65534:\ndaemon:x:1:\n{AGENT_USER}:x:{AGENT_UID}:\nnogroup:x:65533:\n"

ETC_RO_TRY = ["/etc/alternatives", "/etc/ld.so.cache", "/etc/ld.so.conf", "/etc/ld.so.conf.d", "/etc/os-release",
              "/etc/bash.bashrc", "/etc/profile", "/etc/profile.d", "/etc/inputrc", "/etc/terminfo",
              "/etc/magic", "/etc/magic.mime", "/etc/mime.types"]
ETC_DEFAULT_ONLY = ["/etc/python3", "/etc/python3.10", "/etc/python3.11"]
NO_COMPUTE_TMPFS = ["/usr/sbin", "/usr/libexec", "/usr/local", "/usr/lib/python3*", "/usr/lib/x86_64-linux-gnu/perl*",
                    "/usr/lib/x86_64-linux-gnu/ruby*", "/usr/lib/ruby*", "/usr/lib/node*", "/usr/lib/nodejs*",
                    "/usr/lib/x86_64-linux-gnu/node*", "/usr/share/perl*", "/usr/share/ruby*"]


def store_root() -> Path:
    return Path(os.environ.get("EVAL_STORE") or DEFAULT_STORE)


def toolbox_names() -> list[str]:
    out = []
    for line in TOOLBOX.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out


def _copy_tree(src: Path, dst: Path) -> str:
    p = subprocess.run(["cp", "-al", "--", str(src), str(dst)], capture_output=True, text=True)
    if p.returncode == 0:
        return "hardlink"
    shutil.rmtree(dst, ignore_errors=True)
    shutil.copytree(src, dst, symlinks=True, copy_function=shutil.copy2)
    return "copy"


def prepare_run_dir(run_dir, evidence_src, store_root_dir=None) -> Path:
    run_dir = Path(run_dir).resolve()
    evidence_src = Path(evidence_src).resolve()
    if not (evidence_src / "TASK.md").exists():
        raise FileNotFoundError(f"not an evidence dir: {evidence_src}")
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "answer_history").mkdir(exist_ok=True)
    meta_path = run_dir / "store.json"
    if meta_path.exists():
        store = Path(json.loads(meta_path.read_text())["store"])
        if (store / "etc" / "hostname").exists():
            _link_store(run_dir, store)
            return store
    root = Path(store_root_dir) if store_root_dir else store_root()
    root.mkdir(parents=True, exist_ok=True)
    store = root / secrets.token_hex(8)
    store.mkdir(mode=0o700)
    mode = _copy_tree(evidence_src, store / "evidence")
    for d in ("work", "home"):
        (store / d).mkdir()
    etc = store / "etc"
    etc.mkdir()
    hostname = "ws-" + secrets.token_hex(3)
    (etc / "passwd").write_text(PASSWD)
    (etc / "group").write_text(GROUP)
    (etc / "hostname").write_text(hostname + "\n")
    (etc / "hosts").write_text(f"127.0.0.1\tlocalhost\n127.0.1.1\t{hostname}\n")
    _link_store(run_dir, store)
    meta_path.write_text(json.dumps({"store": str(store), "evidence_src": str(evidence_src), "evidence_mode": mode}))
    return store


def _link_store(run_dir: Path, store: Path) -> None:
    for name in STAGED:
        link = run_dir / name
        target = store / name
        if link.is_symlink():
            if os.readlink(link) == str(target):
                continue
            link.unlink()
        elif link.exists():
            raise FileExistsError(f"{link} exists and is not a symlink to the store")
        link.symlink_to(target)


def purge_store(run_dir) -> None:
    meta_path = Path(run_dir) / "store.json"
    if not meta_path.exists():
        return
    store = Path(json.loads(meta_path.read_text())["store"])
    if store.exists() and store.parent in (store_root(), Path(DEFAULT_STORE)):
        shutil.rmtree(store, ignore_errors=True)


def _real(run_dir: Path, name: str) -> str:
    p = run_dir / name
    if not p.exists():
        raise FileNotFoundError(f"run dir not prepared: missing {p}")
    return os.path.realpath(p)


def bwrap_argv(run_dir, tier: str, command: list[str]) -> list[str]:
    if tier not in TIERS:
        raise ValueError(f"unknown tier {tier!r}")
    run_dir = Path(run_dir).resolve()
    ev, work, home, etc = (_real(run_dir, n) for n in STAGED)
    hostname = Path(etc, "hostname").read_text().strip()
    argv = [BWRAP, "--clearenv",
            "--unshare-user", "--unshare-pid", "--unshare-net", "--unshare-uts", "--unshare-ipc", "--unshare-cgroup-try",
            "--uid", str(AGENT_UID), "--gid", str(AGENT_UID), "--hostname", hostname,
            "--ro-bind", "/usr", "/usr",
            "--symlink", "usr/bin", "/bin", "--symlink", "usr/sbin", "/sbin",
            "--symlink", "usr/lib", "/lib", "--symlink", "usr/lib64", "/lib64"]
    if tier == "no_compute":
        argv += ["--tmpfs", "/usr/bin"]
        for name in toolbox_names():
            p = "/usr/bin/" + name
            if os.path.exists(p):
                argv += ["--ro-bind", p, p]
        argv += ["--remount-ro", "/usr/bin"]
        for pat in NO_COMPUTE_TMPFS:
            for d in sorted(glob.glob(pat)):
                if os.path.isdir(d) and not os.path.islink(d):
                    argv += ["--tmpfs", d, "--remount-ro", d]
    argv += ["--perms", "0755", "--dir", "/etc",
             "--ro-bind", f"{etc}/passwd", "/etc/passwd", "--ro-bind", f"{etc}/group", "/etc/group",
             "--ro-bind", f"{etc}/hostname", "/etc/hostname", "--ro-bind", f"{etc}/hosts", "/etc/hosts"]
    for p in ETC_RO_TRY + (ETC_DEFAULT_ONLY if tier == "default" else []):
        argv += ["--ro-bind-try", p, p]
    argv += ["--proc", "/proc", "--dev", "/dev",
             "--perms", "1777", "--tmpfs", "/tmp",
             "--perms", "0755", "--dir", "/var", "--perms", "1777", "--tmpfs", "/var/tmp",
             "--ro-bind", ev, "/evidence",
             "--bind", work, "/work",
             "--perms", "0755", "--dir", "/home",
             "--bind", home, f"/home/{AGENT_USER}",
             "--die-with-parent", "--new-session", "--chdir", "/work",
             "--setenv", "HOME", f"/home/{AGENT_USER}", "--setenv", "USER", AGENT_USER, "--setenv", "LOGNAME", AGENT_USER,
             "--setenv", "PATH", "/usr/local/bin:/usr/bin:/bin", "--setenv", "LANG", "C.UTF-8",
             "--setenv", "TERM", "xterm", "--setenv", "TZ", "UTC",
             "--", "bash", "-c", ULIMIT_WRAP, "sbx"]
    return argv + list(command)


def _killpg(p: subprocess.Popen) -> None:
    try:
        os.killpg(p.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def _read_head(f, cap: int) -> tuple[str, int]:
    f.seek(0, os.SEEK_END)
    total = f.tell()
    f.seek(0)
    data = f.read(cap)
    return data.decode("utf-8", "replace"), total


def run_in_sandbox(run_dir, tier: str, argv: list[str], timeout_s: float = 60, stdin=None, max_bytes: int = 1 << 20):
    cmd = bwrap_argv(run_dir, tier, argv)
    if isinstance(stdin, str):
        stdin = stdin.encode()
    timed_out = False
    with tempfile.TemporaryFile() as fo, tempfile.TemporaryFile() as fe:
        p = subprocess.Popen(cmd, stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
                             stdout=fo, stderr=fe, env=HOST_ENV, cwd="/", start_new_session=True)
        try:
            p.communicate(input=stdin, timeout=timeout_s)
        except subprocess.TimeoutExpired:
            timed_out = True
            _killpg(p)
            try:
                p.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                pass
        finally:
            _killpg(p)
        out, n_out = _read_head(fo, max_bytes)
        err, n_err = _read_head(fe, max_bytes)
    if n_out > max_bytes:
        out += f"\n[sandbox] stdout truncated ({n_out} bytes total)"
    if n_err > max_bytes:
        err += f"\n[sandbox] stderr truncated ({n_err} bytes total)"
    rc = 124 if timed_out else p.returncode
    if timed_out:
        err += f"\n[sandbox] command timed out after {timeout_s:g}s and was killed"
    return rc, out, err


def main(argv=None) -> int:
    a = argv if argv is not None else sys.argv[1:]
    if len(a) >= 2 and a[0] == "purge":
        purge_store(a[1])
        return 0
    if len(a) >= 3 and a[0] == "argv":
        print(" ".join(bwrap_argv(a[1], a[2], ["bash"])))
        return 0
    print("usage: exec.py purge <run_dir> | argv <run_dir> <tier>", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
