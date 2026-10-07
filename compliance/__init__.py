"""Compliance: rules and witnesses, as executable viba modules.

A rule is a program (the environment in, a `bool` verdict out) and a witness is the
program that answers the viba data it judges, so a judgment is a run —
`is_compliant(rule_file, environ)`.
The impure part of a rule (measuring something) goes through `measure`, which
replays a **call** that was backed up before the run and records one that was
not (see `compliance/storage.py`).

The worked example is `compliance/demo/`; the story is in
`viba-compliance.md`.
"""

from compliance.judge import (CALL_TAG, RESULT_TAG, Error, call_of, given_of,
                                   is_compliant, measure, result_of, call_viba_data,
                                   call_path, record_run, read_call,
                                   record_call, the_call)
from compliance.storage import CALL_PREFIX, CallStorage

__all__ = [
    "CALL_TAG", "RESULT_TAG", "CALL_PREFIX", "CallStorage", "Error",
    "call_of", "given_of", "is_compliant", "measure", "result_of",
    "call_viba_data", "call_path", "record_run", "read_call", "record_call",
    "the_call",
]
