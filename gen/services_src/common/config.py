"""Layered JSON config: deploy/config.json, then deploy/config.override.json (if present), then env."""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def load(section=None):
    cfg = {}
    for name in ("config.json", "config.override.json"):
        path = os.path.join(ROOT, "deploy", name)
        if os.path.exists(path):
            with open(path) as f:
                layer = json.load(f)
            for k, v in layer.items():
                if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                    cfg[k].update(v)
                else:
                    cfg[k] = v
    for k, v in os.environ.items():
        if k.startswith("CC_"):
            cfg[k[3:]] = v
    if section:
        return cfg.get(section, {})
    return cfg


def log_path(service):
    d = os.environ.get("CC_LOG_DIR") or os.path.join(ROOT, "deploy", "logs")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, service + ".log")
