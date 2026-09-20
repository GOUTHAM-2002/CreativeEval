"""flock'd USD ledger: per-tag file with reserve/settle, plus a project-wide odometer with a hard cap."""
from __future__ import annotations

import fcntl
import json
import os
import time
from contextlib import contextmanager
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
GLOBAL_FILE = Path(os.environ.get("EVAL_GLOBAL_LEDGER") or PROJECT / "runs" / "global_spend.json")
GLOBAL_CAP = float(os.environ.get("EVAL_GLOBAL_CAP", "2000"))


class BudgetExceeded(RuntimeError):
    pass


@contextmanager
def _locked(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(path) + ".lock", "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lk, fcntl.LOCK_UN)


def _load(path: Path, default: dict) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return dict(default)


def _save(path: Path, data: dict) -> None:
    data["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    tmp = str(path) + ".tmp"
    Path(tmp).write_text(json.dumps(data, indent=1))
    os.replace(tmp, path)


def global_total() -> float:
    return float(_load(GLOBAL_FILE, {}).get("total_usd", 0.0))


def global_add(usd: float, note: str = "") -> float:
    with _locked(GLOBAL_FILE):
        d = _load(GLOBAL_FILE, {"total_usd": 0.0, "cap_usd": GLOBAL_CAP})
        d["total_usd"] = round(float(d.get("total_usd", 0.0)) + float(usd or 0.0), 6)
        d["cap_usd"] = GLOBAL_CAP
        d["last"] = note
        _save(GLOBAL_FILE, d)
        return d["total_usd"]


class Ledger:
    def __init__(self, path, cap_usd: float):
        self.path = Path(path)
        self.cap = float(cap_usd)
        with _locked(self.path):
            d = _load(self.path, {})
            d.setdefault("cap_usd", self.cap)
            d["cap_usd"] = self.cap
            d.setdefault("spent_usd", 0.0)
            d.setdefault("reserved", {})
            d.setdefault("cells", {})
            _save(self.path, d)

    def reserve(self, cell: str, usd: float) -> bool:
        with _locked(self.path):
            d = _load(self.path, {})
            reserved = sum(float(v) for v in d.get("reserved", {}).values())
            if float(d.get("spent_usd", 0.0)) + reserved + usd > self.cap:
                return False
            if global_total() + reserved + usd > GLOBAL_CAP:
                return False
            d.setdefault("reserved", {})[cell] = float(usd)
            _save(self.path, d)
            return True

    def settle(self, cell: str, cost_usd: float, note: str = "") -> None:
        cost = float(cost_usd or 0.0)
        with _locked(self.path):
            d = _load(self.path, {})
            d.setdefault("reserved", {}).pop(cell, None)
            d["spent_usd"] = round(float(d.get("spent_usd", 0.0)) + cost, 6)
            d.setdefault("cells", {})[cell] = {"cost_usd": round(cost, 6), "note": note, "t": time.time()}
            _save(self.path, d)
        if cost:
            global_add(cost, f"{self.path.parent.name}/{cell}")

    def release(self, cell: str) -> None:
        with _locked(self.path):
            d = _load(self.path, {})
            d.setdefault("reserved", {}).pop(cell, None)
            _save(self.path, d)

    def snapshot(self) -> dict:
        d = _load(self.path, {})
        return {"cap_usd": self.cap, "spent_usd": d.get("spent_usd", 0.0), "reserved_usd": round(sum(d.get("reserved", {}).values()), 4),
                "n_cells": len(d.get("cells", {})), "global_total_usd": round(global_total(), 4), "global_cap_usd": GLOBAL_CAP}
