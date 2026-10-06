"""One service process of a distributed viba program: its api, and the store it shares.

A distributed program is one viba file whose steps are calls no single service
implements: each service has its own api, and a run stops at the first call that is
not its own, answering the deferral (`NotMyDutyException`) instead — which names the
storage path (`$step`) and the argument (`$call`). The scheduler writes that into the
store the services share as viba code: a file with one definition, `value`, holding
`$call` (the argument the step was given) and `$measured` (the result, `nil` until it
is filled in), written under the storage path the run stopped at
(`<storage path>/prepare/<api>.viba`, the api it asks for being the file name).
Anyone whose capability table has `<api>` can take the step from there and fill the
result in: `measure` writes it into `$measured`, and the implementation's `recorded`
writes it under that storage path as the snapshot `replayed` reads
(`<storage path>/value.viba`) — which is what the next round's run goes on from.
Re-running is continuing.

`Service` is one process's side of that:

- `get_func` is the capability table the interpreter sees. A call of this service's
  api is served by its own implementation — every implementation goes through
  `recorded`, which is `replayed`: the first run computes the result and records it,
  every later run replays it. A call of another service's api is served from the
  store when the store already holds that call's result (that is how a run passes a
  step it cannot compute); with nothing stored the result is None, and the run stops
  with the deferral.
- `answer_pending` is the other half: what the store holds under this service's api
  names is computed now — the implementation handed the call's arguments the way a
  run hands them (`_the_computation`) — so that the next round's runs find it.
- `run_program` runs the program once and reports what came out.

The report is one JSON line on stdout — the scheduler reads it. A run that stopped
reports the failure state of the round as the viba source of the work order
(`$call $the_call * $measured nil`), which the scheduler writes at the storage path
the run stopped at: that is what the next round answers.
"""

import argparse
import inspect
import json
from pathlib import Path

from viba import serialize, viba_ast
from compliance import (call_of, measure, measured_of, prepare_path,
                             prepare_viba_data, read_prepare)
from compliance.storage import PREPARE_SEGMENT
from viba.interpret import (SNAPSHOT_NAME, Environment, EnvironmentCompute,
                            EnvironmentStorage, NotMyDutyException, Ok,
                            UnderlyingVibaOpFailed, VibaProgramErr, interpret,
                            read_snapshot, replayed, snapshot_path, viba_data)
from viba.reflect import VibaNode, access as reflect_access
from viba.viba_ast import convert_to_chain_style

# The path the program's own environment is. Every call the program makes is given a
# child of it (`root/c0`, `root/c1`, ...), and that child's path is the call's storage
# path in the store: what `replayed` writes the result under, and where the work order
# for that call goes.
ROOT = "root"


def environ_at(module_path: str, store, compute=None, viba_path=None) -> Environment:
    """An environment at a store path: the path a call's result and the work orders
    for that call are read and written through.

    `compute` is left out for the two places that only touch the store (writing a
    work order, reading one back): they never run anything.
    """
    return Environment(EnvironmentStorage(module_path, None, str(store)), compute,
                       str(viba_path) if viba_path else None)


def storage_path(environ: Environment) -> str:
    """The store path this environment is: the path of the call that runs there."""
    return environ.storage.cur_storage_path


def leaf_value(value):
    """The leaf a viba data or a host value carries — what a report names."""
    if not isinstance(value, VibaNode):
        return value
    leaf = reflect_access.leaf(value)
    return leaf.err_msg if isinstance(leaf, VibaProgramErr) else leaf.ok_value


def prepare_text(call) -> str:
    """The work order's text: the call it was given, with `$measured` still nil.

    This is the failure state a stopped run hands the scheduler, serialized as viba
    source (`value = $call … * $measured nil`). The scheduler writes that text at the
    storage path the run stopped at; it is a file a person, a model or another
    `interpret` can read.
    """
    written = serialize.serialize(SNAPSHOT_NAME, viba_data(prepare_viba_data(call)))
    if isinstance(written, VibaProgramErr):
        raise RuntimeError(f"cannot write the work order: {written.err_msg}")
    return written.ok_value


def arguments_taken(implementation) -> int:
    """How many arguments an implementation takes, the environment not counted.

    A run hands an implementation one value per argument of the call; a work order
    keeps those arguments as one viba data, so this number is what says how to hand
    them over again. 0 when the implementation takes the environment alone, 1 when
    the `$call` is one argument, more when it has to be split apart. -1 when the
    signature does not say how many — a callable without a readable one, or one
    written `(environ, *args)` — and then the `$call` is handed over whole.
    """
    try:
        parameters = list(inspect.signature(implementation).parameters.values())
    except (TypeError, ValueError):
        return -1
    if any(one.kind is inspect.Parameter.VAR_POSITIONAL for one in parameters):
        return -1
    counted = [one for one in parameters
               if one.kind in (inspect.Parameter.POSITIONAL_ONLY,
                               inspect.Parameter.POSITIONAL_OR_KEYWORD)]
    return len(counted) - 1


def the_arguments(prepared, count: int, func_name: str) -> tuple:
    """The arguments a work order's `$call` holds, in the order they were written.

    A call with several arguments keeps them as one product, each piece tagged with
    the slot it went to (`call_viba_data`); a call with one argument keeps that
    argument itself — a tagged product of its own among them — so it is handed over
    whole and never split by its own size; a call that was given nothing but its
    environment keeps `nil`, which is no argument at all. What the implementation
    takes is what decides, and a call that cannot give it that many is refused:
    only arguments that are viba data travel.
    """
    if count == 1:
        return (prepared,)
    pieces = _the_pieces(prepared)
    if len(pieces) != count:
        raise ValueError(
            f"the implementation of {func_name!r} takes {count} arguments and the work "
            f"order holds {len(pieces)}: only arguments that are viba data travel")
    return tuple(pieces)


def _the_pieces(prepared) -> list:
    """The pieces of a written product, in written order — the value itself when it
    is one piece, and nothing at all for a `$call` that is `nil`.

    The product a work order stores is read back as the written chain it is, so it
    is flattened the way the rest of viba flattens one (`convert_to_chain_style`):
    a run of `*` is its pieces, and a branch inside one of them stays that piece and
    is not split further.
    """
    piece = getattr(prepared, "data", None)
    if piece is None or isinstance(piece, viba_ast.Nil):
        return []
    chain = convert_to_chain_style(piece)
    if not isinstance(chain, viba_ast.ProductChain):
        return [prepared]
    return [viba_data(one.type if isinstance(one, viba_ast.Tagged) else one)
            for one in chain.elements]


class Service:
    """One service's api, its store, and the calls it answers."""

    def __init__(self, name: str, api, store, program):
        self.name = name
        self.store = Path(store)
        self.program = str(program)
        self.viba_path = str(Path(self.program).resolve().parent)
        # func_name -> implementation(environ, x, ...): one value per argument of
        # the call, the environment first, one result out. Built from this service,
        # so that an implementation can record what it computed (`recorded`).
        self.api = api(self)
        # One note per api call this process answered: whether it computed the
        # result or replayed it, and what the result was. A report carries them.
        self.notes = []

    # ---- the capability table the interpreter sees ----

    def get_func(self, module_path, func_name):
        """This service's implementation of the call, or the store's result, or None.

        None is what makes the run stop and answer the deferral; the store's result
        is what lets the run pass a step this service does not implement.
        """
        own = self.api.get(func_name)
        if own is not None:
            return own
        stored = self.stored_answer(module_path)
        if stored is None:
            return None
        return lambda environ, *args: stored

    def stored_answer(self, module_path):
        """The result the store holds for the call at this path, or None."""
        return read_snapshot(environ_at(module_path, self.store))

    def environ_at(self, module_path, compute=True) -> Environment:
        """The environment for a call at this path, in this process: its storage is that
        path, and its compute side is this service's `get_func`."""
        return environ_at(module_path, self.store,
                          EnvironmentCompute(self.get_func) if compute else None,
                          self.viba_path)

    # ---- what an implementation goes through ----

    def recorded(self, environ, compute):
        """`replayed`, and a note: did this run compute the result, or replay it?

        The note is a report's window on the one promise a distributed program
        makes about its impure steps: each one runs once, and every later run
        replays the result it left.
        """
        stored = read_snapshot(environ)
        value = replayed(environ, compute)
        self.notes.append({"path": storage_path(environ), "computed": stored is None,
                           "value": leaf_value(value)})
        return value

    # ---- the answer phase ----

    def answer_pending(self):
        """Answer what the store holds under this service's api names.

        A work order that carries a measurement already is left alone: a result is
        computed once, by whichever round reached it first.
        """
        answered = []
        for module_path, func_name, prepare in self.pending():
            environ = self.environ_at(module_path)
            value = measure(environ, func_name, call_of(prepare),
                            self._the_computation(environ, func_name),
                            evidence=environ)
            answered.append({"path": module_path, "func_name": func_name,
                             "value": leaf_value(value)})
        return answered

    def _the_computation(self, environ, func_name):
        """What `measure` computes with: this service's implementation, handed the
        call's arguments — one value per argument, the environment first, the way a
        run hands them (`_call_host`).

        A work order keeps those arguments as one viba data, so how many the
        implementation takes (`arguments_taken`) is what says how to hand them over
        again (`the_arguments`). An implementation whose signature does not say how
        many is handed the `$call` itself.
        """
        implementation = self.api[func_name]
        count = arguments_taken(implementation)
        if count < 0:
            return lambda prepared: implementation(environ, prepared)
        return lambda prepared: implementation(
            environ, *the_arguments(prepared, count, func_name))

    def pending(self):
        """(path, func_name, prepare) for the unmeasured work orders of this api.

        A work order is a file under the call's own path
        (`<path>/prepare/<func_name>.viba`) holding that call with `$measured` still
        nil, so the file's place is the path and its name is the api it asks for.
        """
        found = []
        for file in sorted(self.store.rglob(f"{PREPARE_SEGMENT}/*.viba")):
            func_name = file.stem
            if func_name not in self.api:
                continue
            module_path = file.parent.parent.relative_to(self.store).as_posix()
            prepare = read_prepare(self.environ_at(module_path, compute=False), func_name)
            if prepare is None or measured_of(prepare)[1]:
                continue
            found.append((module_path, func_name, prepare))
        return found

    # ---- the run phase ----

    def run_program(self):
        """Run the distributed program once, in this process, and report it.

        What came out is one of four: the result (`ok`), the deferral of a step this
        service does not implement (the failure state of the round), a step whose
        implementation broke (`failed`), or a program or environment that cannot run
        at all (`program_err`).
        """
        result = interpret(self.program, self.environ_at(ROOT))
        report = {"service": self.name, "phase": "run", "api": self.notes}
        if isinstance(result, Ok):
            report.update(result="ok", value=leaf_value(result.ok_value))
        elif isinstance(result, NotMyDutyException):
            report.update(result="not_my_duty", reason=result.reason,
                          path=result.step.module_path if result.step else None,
                          func_name=result.step.func_name if result.step else None,
                          prepare=prepare_text(result.call))
        elif isinstance(result, UnderlyingVibaOpFailed):
            report.update(result="failed", msg=result.msg, reason=result.reason,
                          path=result.step.module_path if result.step else None)
        else:
            report.update(result="program_err", msg=result.err_msg)
        return report


def run_service(name: str, api, argv=None) -> int:
    """The `__main__` of one service process: answer what is owed, or run once.

    `name` is the name the reports and the round record use, and `api` is a function
    from a `Service` to `{func_name: implementation}` — the caller's own side of the
    program.
    """
    parser = argparse.ArgumentParser(
        description=f"service {name!r} of a distributed viba program")
    parser.add_argument("--store", required=True,
                        help="the environment storage every round shares")
    parser.add_argument("--phase", choices=("answer", "run"), required=True,
                        help="answer this service's work orders, or run the program once")
    parser.add_argument("--program", required=True,
                        help="the distributed viba program")
    options = parser.parse_args(argv)
    service = Service(name, api, options.store, options.program)
    if options.phase == "answer":
        answered = service.answer_pending()
        report = {"service": name, "phase": "answer", "result": "answered",
                  "api": service.notes, "answered": answered}
    else:
        report = service.run_program()
    print(json.dumps(report), flush=True)
    return 0
