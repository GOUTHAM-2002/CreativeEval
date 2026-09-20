"""Schema validation for answer.json (never reads truth). CLI prints {"schema_valid", "errors"}."""
import argparse
import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SCHEMA = ROOT / "contract" / "answer_schema.template.json"
MAX_ERRORS = 20
MAX_MSG = 300


def load_schema(path=None):
    return json.loads(Path(path or DEFAULT_SCHEMA).read_text())


def section_schema(template, section):
    return {"$defs": template.get("$defs", {}), **template["properties"][section]}


def validate(obj, schema):
    errs = list(Draft202012Validator(schema).iter_errors(obj))
    errs.sort(key=lambda e: "/".join(str(p) for p in e.absolute_path))
    msgs = [("/".join(str(p) for p in e.absolute_path) or "<root>") + ": " + e.message[:MAX_MSG] for e in errs]
    return not msgs, msgs[:MAX_ERRORS]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("answer")
    ap.add_argument("--schema", default=None)
    a = ap.parse_args(argv)
    schema = load_schema(a.schema)
    try:
        obj = json.loads(Path(a.answer).read_text())
    except (OSError, ValueError) as e:
        out = {"schema_valid": False, "errors": [f"cannot read/parse answer: {e}"[:MAX_MSG]]}
    else:
        ok, errs = validate(obj, schema)
        out = {"schema_valid": ok, "errors": errs}
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
