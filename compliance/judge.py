"""Running a rule: compliance is what the program answers.

A rule is a viba program — the environment in, a verdict out. Running it *is* the
judgment, so there is no judgment layer here: `is_compliant` runs the file and
reads the `bool` it answered.

What a rule cannot do by itself is the impure part: a measurement reads a clock,
a service, a die. That goes through `measure`, which is where the *call* lives:

    value = measure(environ, "distance", given, compute)

- the call it measures is kept as a file in the storage (`compliance/storage.py`):
  the call itself, in the form that can be run again (`the_call`), and `$result`, what
  it answered;
- a call that already carries a result is **replayed**: `compute` is not called at
  all;
- one that does not is measured now, and the result is written into this run's
  store, where the next run finds it.

`record_run` is the other direction: run a rule and *record* the calls it measured
into the backup, which is how a case comes to be measured once and judged as often as
wanted.
"""

from pathlib import Path

from viba import viba_ast
from viba.interpret import (Environment, VibaProgramErr, InterpretResult, Ok, interpret,
                              viba_data, read_snapshot, write_snapshot)
from viba.reflect import VibaNode, access as reflect_access, by_tag
from viba.type import Err
from compliance.storage import CALL_PREFIX, CALL_SEGMENT

CALL_TAG = "$call"
RESULT_TAG = "$result"

# The interpreter's own name for a call that can be run again: a recorded call is
# written `__dyn_call__ << "<name>" << <what it was given>` (viba-interpreter.md).
DYN_CALL = "__dyn_call__"

__all__ = ["is_compliant", "measure", "the_call", "call_viba_data", "call_path",
           "record_run", "read_call", "record_call", "result_of", "call_of",
           "given_of", "CALL_TAG", "RESULT_TAG", "DYN_CALL"]


# ----------------------------------------------------------------------
# Judging
# ----------------------------------------------------------------------


def is_compliant(rule_file: str, environ: Environment) -> InterpretResult:
    """`Ok(bool)`, or the error this run stopped with.

    A run that reaches an operator this host does not implement answers the stop
    instead of a verdict — the judgment is somebody else's to finish — and that stop
    is handed back as it is.
    """
    answer = interpret(rule_file, environ)
    if isinstance(answer, Err):
        return answer.error
    leaf = reflect_access.leaf(answer.ok_value)
    if isinstance(leaf, VibaProgramErr):
        return VibaProgramErr(f"the rule answered no verdict: {leaf.msg}")
    if not isinstance(leaf.ok_value, bool):
        return VibaProgramErr(f"the rule answered {type(leaf.ok_value).__name__}, "
                   f"and a verdict is a bool")
    return leaf


# ----------------------------------------------------------------------
# The call: which call it was, and what it answered
# ----------------------------------------------------------------------


def call_path(name: str) -> str:
    """Where a call lives in the store."""
    return f"{CALL_PREFIX}{name}"


def read_call(environ: Environment, name: str):
    """The stored call `name` as viba data, or None when there is none."""
    return read_snapshot(environ, call_path(name))


def the_call(name: str, *given):
    """A call in the form that can be run again: `__dyn_call__ << "<name>" << …`.

    What is written on it is what the call was given, as it was written, one
    argument each; the environment is not part of a call — giving it one is what
    running it is — so an environment handed in as an argument is not kept here. This
    is the form `UnderlyingOpErr.call` carries (`viba-interpreter.md`).
    """
    node = viba_ast.Partial(viba_ast.TypeRef(DYN_CALL), viba_ast.Constant(name))
    for one in given:
        if one is not None:
            node = viba_ast.Partial(node, _piece(one))
    return viba_data(node)


def call_viba_data(call, result=None):
    """A call as it is kept: `$call` is the call itself, `$result` what it answered.

    Unanswered is written `nil`, so a call reads the same whether or not it has been
    answered yet."""
    return viba_ast.ProductChain([
        viba_ast.Tagged(CALL_TAG, _piece(call)),
        viba_ast.Tagged(RESULT_TAG,
                        _piece(result) if result is not None else viba_ast.Nil()),
    ])


def record_call(environ: Environment, name: str, call, result=None) -> None:
    """Write the call into this run's store."""
    write_snapshot(environ, call_viba_data(call, result), call_path(name))


def call_of(call):
    """The runnable call a stored call holds, or None."""
    return _member(call, CALL_TAG)


def given_of(call):
    """What a stored call was given, as it was written; None when it was given nothing.

    The call is `__dyn_call__ << "<name>" << <what it was given>`: one argument is
    that argument itself, several are kept as the product they were written as, tags
    and all. The name is not among them — that is the call, not what it was given.
    """
    node = getattr(call, "data", None)
    written = []
    while isinstance(node, viba_ast.Partial):
        written.append(node.argument)
        node = node.function
    given = list(reversed(written))[1:]
    if not given:
        return None
    pieces = [one.type if isinstance(one, viba_ast.Tagged) else one for one in given]
    if len(pieces) == 1:
        return viba_data(pieces[0])
    return viba_data(viba_ast.ProductChain(pieces))


def result_of(call):
    """(value, True) when this call instance carries a measurement, else (None, False)."""
    node = _member(call, RESULT_TAG)
    if node is None:
        return None, False
    leaf = reflect_access.leaf(node)
    if isinstance(leaf, VibaProgramErr) or leaf.ok_value is None:
        return None, False
    return leaf.ok_value, True


def measure(environ: Environment, name: str, given, compute,
            evidence: Environment = None):
    """The measured value of the call `name`, given what it was given.

    `environ` is the environment the call runs under: any environment does, a
    temporary one included, because a call has no storage path of its own. `evidence`
    is the environment the call belongs to — the case's, whose path is stable — and
    without it the call goes under the call's own path, where a temporary one can
    never be found again.

    Replayed when the call carries a result; measured by `compute(given)` — the
    impure step — only when there is nothing to replay, and then written into this
    run's store. What the stored call was given wins over what is handed in here: the
    call that was fixed is the one that counts."""
    store_env = evidence if isinstance(evidence, Environment) else environ
    stored = read_call(store_env, name)
    value, answered = result_of(stored)
    if answered:
        return value
    fixed = given_of(call_of(stored)) if stored is not None else None
    if fixed is None:
        fixed = given
    value = compute(fixed)
    record_call(store_env, name, the_call(name, fixed), value)
    return value


# ----------------------------------------------------------------------
# Recording: a run whose calls are recorded as the backup
# ----------------------------------------------------------------------


def record_run(rule_file: str, environ: Environment) -> InterpretResult:
    """Run the rule, recording into the backup every call it measured.

    Nothing is recorded by a run that stopped: a deferral is not an answer, and
    a case is not measured by a judgment that never happened.
    """
    storage = getattr(environ, "storage", None)
    record = getattr(storage, "record_text", None)
    if record is None or getattr(storage, "call_root_dir", None) is None:
        return VibaProgramErr("this storage cannot record a call: give a "
                   "CallStorage with a call_root_dir")
    answer = is_compliant(rule_file, environ)
    if not isinstance(answer, Ok):
        return answer
    for path in _run_calls(storage):
        text = storage.read_text(path)
        if text is not None:
            record(path, text)
    return answer


def _run_calls(storage):
    """The store paths of the calls this run wrote, `.viba` and all.

    A store path is what `storage.read_text` takes: `<storage path>/call/...`,
    relative to the store root."""
    store = Path(storage.store_root_dir)
    root = store / Path(*[part for part in str(storage.cur_storage_path).split("/") if part])
    if not root.is_dir():
        return []
    return [str(path.relative_to(store)) for path in sorted(root.rglob("*.viba"))
            if CALL_SEGMENT in path.parts]


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
