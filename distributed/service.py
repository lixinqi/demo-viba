"""One service process of a distributed viba program: its api, and the store it shares.

A distributed program is one viba file whose steps are calls no single service
implements: each service has its own api, and a run stops at the first call that is
not its own, answering `UnderlyingOpErr` under the `$not_implemented_err` tag. That
error names the step the way viba names one (`viba-interpreter.md`): `$module_path` is
the module the step is declared in, as a path (`service_b` is `/service_b`),
`$full_qualified_func_name` is its whole name (`service_b.b_step`), and `$call` is the
same call as data, in a form that can be run again (the whole name and the arguments,
the environment left out). **Where the call ran is not in those two names** — that is
the data path of the environment the step is handed, and this layer's own report and
work orders carry it (`Service.deferred`). The scheduler writes that call into the store
the services share as viba code: a file with one definition, `value`, holding `$call` and
`$result` (`nil` until someone answers it), written under the storage path the run
stopped at (`<storage path>/call/<api>.viba`, the api it asks for being the file name).
Anyone whose capability table has `<api>` can take the call from there and answer it:
`answer_pending` runs that call again, giving it an environment at its own storage
path, so the implementation is asked exactly the way the stopped run would have asked
it; the implementation's `recorded` writes the answer under that storage path as the
snapshot `replayed` reads (`<storage path>/value.viba`) — which is what the next
round's run goes on from. Re-running is continuing.

`Service` is one process's side of that:

- `get_func` is the capability table the interpreter sees, asked by the step's two
  names (`get_func(module, func_name)`). A step of this service's api is served by its
  own implementation — every implementation goes through `recorded`, which is
  `replayed`: the first run computes the result and records it, every later run replays
  it. Any other step of the program is served from the store when the store already
  holds **that call's** result (that is how a run passes a step it cannot compute); with
  nothing stored the service says so itself, and the run stops with the deferral.
- `answer_pending` is the other half: every call the store holds under this service's
  api names, with `$result` still `nil`, is run now — the call as the stopped run wrote
  it, given an environment at its own storage path — so that the next round's runs find
  the answer.
- `run_program` runs the program once and reports what came out.

The report is one JSON line on stdout — the scheduler reads it. A run that stopped
reports `path` (where the call ran), `func_name` (the name it asks for), the step's two
viba names (`module_path`, `full_qualified_func_name`) and the failure state of the round
as the viba source of the work order (`$call <the call> * $result nil`), which the
scheduler writes at the storage path the run stopped at: that is what the next round
answers.
"""

import argparse
import json
from pathlib import Path

from viba import serialize
from compliance import (call_of, call_viba_data, read_call, record_call,
                        result_of, the_call)
from compliance.storage import CALL_SEGMENT
from viba.interpret import (SNAPSHOT_NAME, Environment, EnvironmentCompute,
                            EnvironmentStorage, exec, interpret, read_snapshot,
                            replayed, viba_data)
from viba.reflect import VibaNode, access as reflect_access
from viba.type import (FAILURE_TAG, NOT_IMPLEMENTED_TAG, REASON_NO_IMPLEMENTATION,
                       Err, Ok, UnderlyingOpErr, VibaProgramErr)

# The path the program's own environment is. Every call the program makes is given a
# child of it (`root/c0`, `root/c1`, ...), and that child's path is the call's storage
# path in the store: what `replayed` writes the result under, and where the work order
# for that call goes.
ROOT = "root"


def environ_at(path: str, store, compute=None, viba_path=None) -> Environment:
    """An environment at a store path: the path a call's result and the work orders
    for that call are read and written through.

    `compute` is left out for the two places that only touch the store (writing a
    work order, reading one back): they never run anything.
    """
    return Environment(EnvironmentStorage(path, None, str(store)), compute,
                       str(viba_path) if viba_path else None)


def storage_path(environ: Environment) -> str:
    """The store path this environment is: the path of the call that runs there."""
    return environ.storage.cur_storage_path


def module_path_of(module: str) -> str:
    """The module a step is declared in, read as a path: `service_a` is `/service_a`."""
    return "/" + module.replace(".", "/") if module else ""


def not_implemented(module: str, func_name: str, where: dict) -> UnderlyingOpErr:
    """`$not_implemented_err` for a step said from inside an implementation.

    A host that says so from `get_func` need not fill anything in — the run fills the
    step in for it. Said from inside the implementation it cannot: the run hands that
    error back as it is. So the step is written here the way the run writes it
    (`viba-interpreter.md`): the module as a path, and the whole name as the data the
    call carries. `where` is what only this service knows — where the call ran, and the
    call as this layer writes it (a work order): the run hands a step its environment,
    not its path (viba-interpreter.md「`get_func` 与 `full_qualified_func_name`」).
    """
    return UnderlyingOpErr(REASON_NO_IMPLEMENTATION, module_path_of(module),
                           where["full_name"], viba_data(where["call"]),
                           tag=NOT_IMPLEMENTED_TAG)


def leaf_value(value):
    """The leaf a viba data or a host value carries — what a report names."""
    if not isinstance(value, VibaNode):
        return value
    leaf = reflect_access.leaf(value)
    return leaf.msg if isinstance(leaf, VibaProgramErr) else leaf.ok_value


def call_text(call) -> str:
    """The work order's text: the call, with `$result` still nil.

    This is the failure state a stopped run hands the scheduler, serialized as viba
    source (`value = $call … * $result nil`). The scheduler writes that text at the
    storage path the run stopped at; it is a file a person, a model or another
    `interpret` can read.
    """
    written = serialize.serialize(SNAPSHOT_NAME, viba_data(call_viba_data(call)))
    if isinstance(written, VibaProgramErr):
        raise RuntimeError(f"cannot write the work order: {written.msg}")
    return written.ok_value


def answer_the_call(call, environ: Environment):
    """Run `call` with `environ`: `Ok(its answer)`, or the error the run stopped with.

    `call` is the call as the stopped run wrote it — a closure of type
    `Any <- $env Env`, its environment left out — so running it is giving it one, and
    `exec` takes that data as the call to run (`viba-interpreter.md`「把一次调用写成
    可执行的」). The implementation is then asked exactly the way the stopped run would
    have asked it, at that storage path, with the arguments the call was written with.
    """
    return exec(call, environ)


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
        # 这一次运行停在哪一步：两个名字之外的东西 —— 这次调用跑在哪条数据路径上、
        # 它作为工作单长什么样。viba 不再把数据路径交给 `get_func`，宿主在实现里从环境上读
        # （`from_the_store`），这里就是把它记下来给报告用。
        self.deferred = None
        # One note per api call this process answered: whether it computed the
        # result or replayed it, and what the result was. A report carries them.
        self.notes = []

    # ---- the capability table the interpreter sees ----

    def get_func(self, module, func_name):
        """This service's step, or the store's result for it, or a deferral.

        The run asks by the step's two names (`get_func(module, func_name)`,
        viba-interpreter.md): the module it is declared in as it was imported
        (`service_a`), and the name it has there (`a_step`). A step this service's api has
        is its own.

        Any other step of this program is answered from the store when the store already
        holds **that call's** result — and which call that is, its data path, is on the
        environment the step is handed: the two names say which step, not where it ran.
        With nothing stored the step is a deferral, said here (`not_implemented`), with
        what only this service knows: where the call ran (`self.deferred`), for the
        report and the work order.

        A name that is no step of this program at all answers `None`: the run says it
        (`__dyn_call__` at a program's own name, say), and this service has nothing to
        name it with.
        """
        own = self.api.get(func_name)
        if own is not None:
            return own
        if not self.is_a_step_of_the_program(module):
            return None

        def from_the_store(environ, *args):
            """This call's recorded result, or the deferral that hands it on."""
            stored = read_snapshot(environ)
            if stored is not None:
                return stored
            whole = f"{module}.{func_name}" if module else func_name
            self.deferred = {"path": storage_path(environ), "module": module,
                             "func_name": func_name, "full_name": whole,
                             "call": the_call(whole, *args)}
            raise not_implemented(module, func_name, self.deferred)

        return from_the_store

    def is_a_step_of_the_program(self, module: str) -> bool:
        """Is that module one of this program's api files? A step is declared in one.

        The api files sit beside the program (`service_a.viba` next to
        `interleaved.viba`), which is where the run looks them up too
        (`Service.viba_path`).
        """
        if not module:
            return False
        return (Path(self.viba_path) / f"{module}.viba").is_file()

    def environ_at(self, path, compute=True) -> Environment:
        """The environment for a call at this path, in this process: its storage is that
        path, and its compute side is this service's `get_func`."""
        return environ_at(path, self.store,
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
        """Answer every call the store holds under this service's api names.

        A call that already carries a `$result` is left alone: a result is computed
        once, by whichever round reached it first. What is run is the call itself, at
        the storage path it stopped at, so this service's implementation is asked the
        way the stopped run would have asked it; the answer is recorded into the same
        file, and `recorded` also leaves it under that path as the snapshot the next
        run replays.
        """
        answered = []
        for path, func_name, call in self.pending():
            environ = self.environ_at(path)
            the_call = call_of(call)
            result = answer_the_call(the_call, environ)
            if not isinstance(result, Ok):
                raise RuntimeError(f"{func_name!r} did not answer: {result!r}")
            record_call(environ, func_name, the_call, result.ok_value)
            answered.append({"path": path, "func_name": func_name,
                             "value": leaf_value(result.ok_value)})
        return answered

    def pending(self):
        """(path, func_name, call) for the unanswered calls of this api.

        A work order is a file under the call's own path
        (`<path>/call/<func_name>.viba`) holding that call with `$result` still nil,
        so the file's place is the path and its name is the api it asks for.
        """
        found = []
        for file in sorted(self.store.rglob(f"{CALL_SEGMENT}/*.viba")):
            func_name = file.stem
            if func_name not in self.api:
                continue
            path = file.parent.parent.relative_to(self.store).as_posix()
            call = read_call(self.environ_at(path, compute=False), func_name)
            if call is None or result_of(call)[1]:
                continue
            found.append((path, func_name, call))
        return found

    # ---- the run phase ----

    def run_program(self):
        """Run the distributed program once, in this process, and report it.

        What came out is one of four: the result (`ok`), a step no service here
        implements (`not_my_duty` — the failure state of the round), a step whose
        implementation broke (`failed`), or a program or environment that cannot run
        at all (`program_err`).
        """
        self.deferred = None
        result = interpret(self.program, self.environ_at(ROOT))
        report = {"service": self.name, "phase": "run", "api": self.notes}
        if isinstance(result, Ok):
            report.update(result="ok", value=leaf_value(result.ok_value))
            return report
        error = result.error
        if isinstance(error, UnderlyingOpErr) and error.tag == NOT_IMPLEMENTED_TAG:
            where = self.deferred or {}
            handed_over = where["call"] if where.get("call") is not None else error.call
            report.update(result="not_my_duty", reason=error.msg,
                          path=where.get("path", error.module_path),
                          func_name=where.get("func_name",
                                              error.full_qualified_func_name),
                          module_path=error.module_path,
                          full_qualified_func_name=error.full_qualified_func_name,
                          call=call_text(handed_over))
        elif isinstance(error, UnderlyingOpErr) and error.tag == FAILURE_TAG:
            report.update(result="failed", msg=error.msg, reason=error.msg,
                          path=error.module_path or None)
        else:
            report.update(result="program_err", msg=error.msg)
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
