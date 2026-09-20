# Scan an evidence tree for anything that must never reach the solver.
from __future__ import annotations
import os
import re
import subprocess
from pathlib import Path

PATH_RE = re.compile(r"truth|decoy|herring|canar|generator|world\.json|sim_series|docs_meta|driver_report", re.I)


def scan(ev: Path, truth: dict) -> list[str]:
    problems = []
    canaries = [c for c in truth["canaries"] if len(c) >= 4]
    mtimes = set()
    for p in ev.rglob("*"):
        rel = p.relative_to(ev).as_posix()
        if ".git/" in rel + "/" and not rel.endswith("config"):
            continue
        if PATH_RE.search(rel) and not rel.startswith("repo/.git"):
            problems.append(f"path vocabulary: {rel}")
        if p.is_file():
            mtimes.add(int(p.stat().st_mtime))
            try:
                text = p.read_text(errors="replace")
            except OSError:
                continue
            for c in canaries:
                if c in text:
                    problems.append(f"canary {c!r} in {rel}")
                    break
    if len(mtimes) > 1 and (max(mtimes) - min(mtimes)) > 600:
        # a build spreads mtimes over the replay (~25 min) and would reveal generation order; a git checkout does not
        problems.append(f"mtimes spread over {max(mtimes) - min(mtimes)} s: {sorted(mtimes)[:3]}...")
    repo = ev / "repo"
    import tempfile, shutil as _sh
    tmpd = None
    if not (repo / ".git").exists() and (ev / "repo.git.bundle").exists():
        from gen.gitbundle import restore_repo
        tmpd = Path(tempfile.mkdtemp(prefix="leakcheck_"))
        _sh.copytree(repo, tmpd / "repo"); _sh.copy(ev / "repo.git.bundle", tmpd / "repo.git.bundle")
        restore_repo(tmpd); repo = tmpd / "repo"
    if (repo / ".git").exists():
        r = subprocess.run(["git", "-C", str(repo), "log", "--all", "-p"], capture_output=True, text=True)
        for c in canaries:
            if c in r.stdout:
                problems.append(f"canary {c!r} in git history")
    if tmpd:
        _sh.rmtree(tmpd, ignore_errors=True)
    for name in ("truth.json", "world.json", "answer.json"):
        if list(ev.rglob(name)):
            problems.append(f"forbidden file {name} inside evidence")
    return problems


if __name__ == "__main__":
    import json, sys
    inst = Path(sys.argv[1])
    t = json.load(open(inst / "truth.json"))
    pr = scan(inst / "evidence", t)
    print("\n".join(pr) if pr else "leakcheck: clean")
    sys.exit(1 if pr else 0)
