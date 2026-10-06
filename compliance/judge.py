"""Running a rule: compliance is what the program answers.

A rule is a viba program — the environment in, a verdict out. Running it *is* the
judgment, so there is no judgment layer here: `is_compliant` runs the file and
reads the `bool` it answered.

What a rule cannot do by itself is the impure part: a measurement reads a clock,
a service, a die. That goes through `measure`, which is where the *Prepare*
lives:

    value = measure(environ, "distance", call, compute)

- the call it measures is a Prepare — the arguments fixed, the result declared —
  kept as a file in the storage (`compliance/storage.py`);
- a Prepare that already carries a measured value is **replayed**: `compute` is
  not called at all;
- one that does not is measured now, and the value is written into this run's
  store, where the next run finds it.

`prepare_run` is the other direction: run a rule and *record* the Prepares it
measured into the backup, which is how a case comes to be prepared once and
judged as often as wanted.
"""

from pathlib import Path

from viba import viba_ast
from viba.interpret import (Environment, VibaProgramErr, InterpretResult, Ok, interpret,
                              viba_data, read_snapshot, write_snapshot)
from viba.reflect import VibaNode, access as reflect_access, by_tag
from compliance.storage import PREPARE_PREFIX, PREPARE_SEGMENT

CALL_TAG = "$call"
MEASURED_TAG = "$measured"

__all__ = ["is_compliant", "measure", "prepare_viba_data", "prepare_path", "prepare_run",
           "read_prepare", "record_prepare", "measured_of", "call_of",
           "CALL_TAG", "MEASURED_TAG"]


# ----------------------------------------------------------------------
# Judging
# ----------------------------------------------------------------------


def is_compliant(rule_file: str, environ: Environment) -> InterpretResult:
    """Result[bool]: run the rule and read its verdict.

    A run that reaches an operator this host does not implement answers the
    deferral instead of a verdict — the judgment is somebody else's to finish.
    """
    answer = interpret(rule_file, environ)
    if not isinstance(answer, Ok):
        return answer
    leaf = reflect_access.leaf(answer.ok_value)
    if isinstance(leaf, VibaProgramErr):
        return VibaProgramErr(f"the rule answered no verdict: {leaf.err_msg}")
    if not isinstance(leaf.ok_value, bool):
        return VibaProgramErr(f"the rule answered {type(leaf.ok_value).__name__}, "
                   f"and a verdict is a bool")
    return leaf


# ----------------------------------------------------------------------
# The Prepare: the call, and what it measured
# ----------------------------------------------------------------------


def prepare_path(name: str) -> str:
    """Where a Prepare lives in the store."""
    return f"{PREPARE_PREFIX}{name}"


def read_prepare(environ: Environment, name: str):
    """The stored Prepare `name` as viba data, or None when there is none."""
    return read_snapshot(environ, prepare_path(name))


def prepare_viba_data(call, measured=None):
    """A Prepare: `$call` is the prepared call, `$measured` what it answered.

    Unmeasured is written `nil`, so a Prepare reads the same whether or not the
    measurement happened yet."""
    return viba_ast.ProductChain([
        viba_ast.Tagged(CALL_TAG, _piece(call)),
        viba_ast.Tagged(MEASURED_TAG,
                        _piece(measured) if measured is not None else viba_ast.Nil()),
    ])


def record_prepare(environ: Environment, name: str, call, measured=None) -> None:
    """Write the Prepare into this run's store."""
    write_snapshot(environ, prepare_viba_data(call, measured), prepare_path(name))


def call_of(prepare):
    """The prepared call of a stored Prepare, or None."""
    return _member(prepare, CALL_TAG)


def measured_of(prepare):
    """(value, True) when this Prepare carries a measurement, else (None, False)."""
    node = _member(prepare, MEASURED_TAG)
    if node is None:
        return None, False
    leaf = reflect_access.leaf(node)
    if isinstance(leaf, VibaProgramErr) or leaf.ok_value is None:
        return None, False
    return leaf.ok_value, True


def measure(environ: Environment, name: str, call, compute, evidence: Environment = None):
    """The measured value of the prepared call `name`.

    `environ` is the environment the call runs under: any environment does, a
    temporary one included, because a call has no storage path of its own. `evidence`
    is the environment the Prepare belongs to — the case's, whose path is stable
    — and without it the Prepare goes under the call's path, where a temporary
    one can never be found again.

    Replayed when the Prepare carries a value; measured by `compute(call)` — the
    impure step — only when there is nothing to replay, and then written into
    this run's store. The call the Prepare names wins over the one written here:
    the prepared call is the one that was fixed."""
    store_env = evidence if isinstance(evidence, Environment) else environ
    prepare = read_prepare(store_env, name)
    value, recorded = measured_of(prepare)
    if recorded:
        return value
    prepared = call_of(prepare)
    if prepared is None:
        prepared = viba_data(call)
    value = compute(prepared)
    record_prepare(store_env, name, prepared, value)
    return value


# ----------------------------------------------------------------------
# Preparing: a run whose Prepares are recorded as the backup
# ----------------------------------------------------------------------


def prepare_run(rule_file: str, environ: Environment) -> InterpretResult:
    """Run the rule, recording into the backup every Prepare it measured.

    Nothing is recorded by a run that stopped: a deferral is not an answer, and
    a case is not prepared by a judgment that never happened.
    """
    storage = getattr(environ, "storage", None)
    record = getattr(storage, "record_text", None)
    if record is None or getattr(storage, "prepare_root_dir", None) is None:
        return VibaProgramErr("this storage cannot record a Prepare: give a PreparedStorage "
                   "with a prepare_root_dir")
    answer = is_compliant(rule_file, environ)
    if not isinstance(answer, Ok):
        return answer
    for path in _run_prepares(storage):
        text = storage.read_text(path)
        if text is not None:
            record(path, text)
    return answer


def _run_prepares(storage):
    """The store paths of the Prepares this run wrote, `.viba` and all.

    A store path is what `storage.read_text` takes: `<storage path>/prepare/...`,
    relative to the store root."""
    store = Path(storage.store_root_dir)
    root = store / Path(*[part for part in str(storage.cur_storage_path).split("/") if part])
    if not root.is_dir():
        return []
    return [str(path.relative_to(store)) for path in sorted(root.rglob("*.viba"))
            if PREPARE_SEGMENT in path.parts]


# ----------------------------------------------------------------------
# Small helpers
# ----------------------------------------------------------------------


def _member(node, tag):
    if node is None:
        return None
    given = reflect_access.get(node, by_tag(tag))
    if isinstance(given, VibaProgramErr) or given.ok_value is None:
        return None
    return given.ok_value


def _data(value):
    """The AST piece under a viba data (or the piece itself)."""
    return value.data if isinstance(value, VibaNode) else value


def _piece(value):
    """A host value as an AST piece of viba data (a scalar becomes its leaf)."""
    return _data(viba_data(value))
