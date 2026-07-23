#!/usr/bin/env python3
"""Validate one JSON document against a JSON Schema deterministically."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import cast

from jsonschema import Draft202012Validator, FormatChecker, validators
from jsonschema.exceptions import SchemaError, ValidationError


def _strictly_ascending(validator: object, enabled: bool, instance: object, schema: object):
    if not enabled or not isinstance(instance, list):
        return
    if not all(
        isinstance(item, (int, float))
        and not isinstance(item, bool)
        and math.isfinite(item)
        for item in instance
    ):
        return
    if any(left >= right for left, right in zip(instance, instance[1:])):
        yield ValidationError("array values must be strictly ascending")


def _sum_equals(validator: object, rule: object, instance: object, schema: object):
    if not isinstance(rule, dict) or not isinstance(instance, dict):
        return
    names = rule.get("fields")
    expected = rule.get("value")
    if not isinstance(names, list) or not isinstance(expected, (int, float)):
        return
    values = [instance.get(name) for name in names]
    if not all(
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        for value in values
    ):
        return
    numeric_values = [float(cast(int | float, value)) for value in values]
    if not math.isclose(
        math.fsum(numeric_values), float(expected), rel_tol=0.0, abs_tol=1e-12
    ):
        yield ValidationError(f"fields {names} must sum to {expected}")


ContractValidator = validators.extend(
    Draft202012Validator,
    {"x-strictlyAscending": _strictly_ascending, "x-sumEquals": _sum_equals},
)


def _reject_non_json_number(value: str) -> object:
    raise ValueError(f"non-JSON numeric constant: {value}")


def _pointer(parts: object) -> str:
    return "/" + "/".join(str(part).replace("~", "~0").replace("/", "~1") for part in parts)  # type: ignore[arg-type]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schema", required=True, type=Path)
    parser.add_argument("--input", required=True, type=Path)
    args = parser.parse_args(argv)

    try:
        schema = json.loads(
            args.schema.read_text(encoding="utf-8"), parse_constant=_reject_non_json_number
        )
        instance = json.loads(
            args.input.read_text(encoding="utf-8"), parse_constant=_reject_non_json_number
        )
        ContractValidator.check_schema(schema)
    except (OSError, ValueError, SchemaError) as exc:
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
