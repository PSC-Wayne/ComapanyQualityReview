#!/usr/bin/env python3
"""Validate one JSON document against a JSON Schema deterministically."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker, validators
from jsonschema.exceptions import SchemaError, ValidationError


def _strictly_ascending(validator: object, enabled: bool, instance: object, schema: object):
    if not enabled or not isinstance(instance, list):
        return
    if not all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in instance):
        return
    if any(left >= right for left, right in zip(instance, instance[1:])):
        yield ValidationError("array values must be strictly ascending")


ContractValidator = validators.extend(
    Draft202012Validator, {"x-strictlyAscending": _strictly_ascending}
)


def _pointer(parts: object) -> str:
    return "/" + "/".join(str(part).replace("~", "~0").replace("/", "~1") for part in parts)  # type: ignore[arg-type]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schema", required=True, type=Path)
    parser.add_argument("--input", required=True, type=Path)
    args = parser.parse_args(argv)

    try:
        schema = json.loads(args.schema.read_text(encoding="utf-8"))
        instance = json.loads(args.input.read_text(encoding="utf-8"))
        ContractValidator.check_schema(schema)
    except (OSError, json.JSONDecodeError, SchemaError) as exc:
        print(f"INVALID setup: {exc}", file=sys.stderr)
        return 2

    validator = ContractValidator(schema, format_checker=FormatChecker())
    errors = sorted(
        validator.iter_errors(instance),
        key=lambda error: (_pointer(error.absolute_path), error.message),
    )
    if errors:
        for error in errors:
            print(f"INVALID {_pointer(error.absolute_path)}: {error.message}", file=sys.stderr)
        return 1

    print(f"VALID {args.input.as_posix()} against {args.schema.as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
