# Shipped instances carry the services repo as a working tree plus a git bundle (a nested .git cannot live inside
# the outer repository). The build bundles at freeze time; staging restores .git before the solver sees the tree.
from __future__ import annotations
import shutil
import subprocess
from pathlib import Path

BUNDLE = "repo.git.bundle"


def bundle_repo(ev: Path) -> Path | None:
    repo = (Path(ev) / "repo").resolve()
    if not (repo / ".git").exists():
        return None
    out = (Path(ev) / BUNDLE).resolve()
    subprocess.run(["git", "-C", str(repo), "bundle", "create", str(out), "--all"], check=True, capture_output=True)
    shutil.rmtree(repo / ".git")
    return out


def restore_repo(ev: Path, remove_bundle: bool = True) -> bool:
    ev = Path(ev).resolve()
    repo, bundle = ev / "repo", ev / BUNDLE
    if (repo / ".git").exists() or not bundle.exists():
        return False
    subprocess.run(["git", "clone", "-q", "--bare", str(bundle), str(repo / ".git")], check=True, capture_output=True)
    env_free = ["git", "-C", str(repo)]
    subprocess.run(env_free + ["config", "core.bare", "false"], check=True, capture_output=True)
    subprocess.run(env_free + ["config", "--unset", "remote.origin.url"], capture_output=True)
    subprocess.run(env_free + ["config", "user.name", "coldchain-bot"], capture_output=True)
    subprocess.run(env_free + ["config", "user.email", "bot@example"], capture_output=True)
    subprocess.run(env_free + ["reset", "-q"], check=True, capture_output=True)      # rebuild the index from HEAD
    for p in (repo / ".git").glob("logs/**/*"):
        pass
    if remove_bundle:
        bundle.unlink()
    return True
