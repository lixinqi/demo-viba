"""One handler process: it polls the tickets path, runs the calls it can, and logs.

A handler is a name, a **role** (a module that answers a capability table
`{name: implementation}` when it is handed a `Context`), and a loop:

1. sleep one second (`--interval`), then read the tickets path and every ticket's
   progress;
2. take each ticket whose progress holds no `$ok` yet and whose newest stage is not this
   handler's own — that is whose turn it is, and it is how several processes advance one
   ticket by turns;
3. **be at the three versions the ticket names** — the viba **interpreter** this process
   runs, the **norm repo** the call's code is written in, and its own role module. All
   three are read off the file system (`the_commit_id_problem`), and a run that is not at
   them writes the stop instead of an answer: the answer to a call is the host's code, so
   another version's answer is another answer. The norm repo is read at its commit
   by extracting that commit's tree, so a checkout somebody is working in is never
   written to (`ticket_system/repo.py`);
4. run the ticket's `$call` in the ticket's own environment — its storage root is the
   ticket's `$storage_path`, its module search path is the ticket's `$VIBA_PATH` with the
   norm repo's checkout first, and the implementations around the call are the role's
   table plus the builtin operators (`ticket_system/builtins.py`);
5. append one stage, holding what the call answered: `$ok <value>`, or the error the run
   stopped with (`$not_implemented_err` when the call is another role's business);
6. stop when every ticket's progress holds a `$ok` — the stop condition of the whole
   system, in `ticket_system/README.md` — or when `--ticks` says how many polls to make.

Two handlers running at once are two processes over one tickets path; they never write
the same file (`progress.stage_name`), and neither waits for the other: each takes the
tickets whose newest stage is not its own, so they advance one ticket by turns. A step one
of them cannot do and the other has already recorded is served from the ticket's storage
(`_capabilities`), which is what lets either run pass it and go on.

    python3 -m ticket_system.handler --tickets <tickets path> --handler a \
        --api my_package.my_role:the_api
"""

import argparse
import json
import os
import signal
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from compliance import the_call
from viba.interpret import (Environment, EnvironmentCompute, EnvironmentStorage,
                            exec, read_snapshot)
from viba.type import (Err, NOT_IMPLEMENTED_TAG, REASON_NO_IMPLEMENTATION,
                       UnderlyingOpErr)

from ticket_system import builtins, code, progress, repo, tickets

# How long one poll waits before the next one. The system is a poll loop over the
# file system: one second is the resolution it runs at.
INTERVAL = 1.0


@dataclass
class Context:
    """What a role's api is handed: who is serving, over what — and which norm repo.

    `norm` is the checkout of the norm repo the ticket names (`ticket_system/repo.py`),
    made before the call runs. A role that serves norm-repo code builds its entries out
    of it (`demo/ticket_examples/service_a.py`), which is why the api is asked for the
    table per ticket and not once at startup: two tickets can name two norm repos.
    """

    name: str
    tickets_path: str
    interval: float
    norm: object = None


def where_the_api_is(spec: str) -> str:
    """The file the capability table of `MODULE:FUNCTION` was loaded from.

    That file is the answer to "which commit is this handler's api at": it is read off
    the code that is about to answer, not taken on the process's word
    (`ticket_system/code.py`). A spec that names a file directly is that file.
    """
    module_name, _, function_name = spec.partition(":")
    if not module_name or not function_name:
        raise SystemExit(f"the api wants MODULE:FUNCTION, not {spec!r}")
    path = Path(module_name)
    if path.suffix == ".py" or path.is_file():
        return str(path)
    module = __import__(module_name, fromlist=[function_name])
    return str(getattr(module, "__file__", "") or module_name)


def the_running_interpreter() -> str:
    """The commit of the viba interpreter this process is running.

    Read from the package that is imported right now, not from the ticket: the ticket
    says which interpreter a run has to be made by, and this is the one that would make
    it. A process cannot change the interpreter it is running, so the two have to be the
    same one.
    """
    from viba import interpret

    where = getattr(interpret, "__file__", None)
    if not where:
        raise code.Error("the running viba package does not say where it is loaded from")
    return code.git_commit(where, "the running viba interpreter", "this process")


def the_interpreter_problem(ticket: "tickets.Ticket", running: str) -> Optional[str]:
    """Why this process's interpreter must not run this ticket, or None.

    `$viba_interpreter_repo_commit_id` + `$viba_interpreter_repo_path` name the interpreter
    the ticket was written against. There is one interpreter per process, and this
    process is already running one: what is read is that package's own commit
    (`the_running_interpreter`), and it has to be the one the ticket names.
    """
    if not ticket.viba_interpreter_repo_commit_id:
        return None
    wanted = str(ticket.viba_interpreter_repo_commit_id)
    if running != wanted:
        return (f"this ticket asks for the viba interpreter at commit {wanted!r}, and "
                f"this process runs {running!r} ({ticket.viba_interpreter_repo_path})")
    return None


def the_norm_problem(ticket: "tickets.Ticket", norm) -> Optional[str]:
    """Why this process must not read this ticket's norm repo, or None.

    `$norm_repo_commit_id` + `$norm_repo_path` name the code the calls are written in, and
    the run reads that commit of it (`ticket_system/repo.py`). A repo with no such
    commit, or no checkout at all, is a stop rather than a fallback: the code this run
    would read is not the code the ticket was written against.
    """
    if not ticket.norm_repo_commit_id:
        return None
    try:
        norm.checkout
    except code.Error as problem:
        return str(problem)
    return None


def the_commit_id_problem(ticket: "tickets.Ticket", handler_name: str,
                       api_path=None, running=None, norm=None) -> Optional[str]:
    """Why this handler must not run this call, or None when it may.

    A run is pinned to three versions, and all three are **read off the file system** —
    there is no way to say "trust me, I am at that commit", because that is exactly the
    claim the pinning exists to check:

    - `$viba_interpreter_repo_commit_id`: the viba that reads and runs the program
      (`the_interpreter_problem`, read from the package this process is running);
    - `$norm_repo_commit_id` with `$norm_repo_path`: the code the call is written in
      (`the_norm_problem`, read at that commit — from the checkout, or from a tree
      extracted out of it);
    - `$handler_name2api_repo_commit_id`: the commit the ticket names **for this handler**,
      because which names this process serves is its own module's business — and that
      module is code too. Its commit is read at `api_path`, the file it was loaded from
      (`handler.where_the_api_is`).

    Three cases for the role's own commit, and only the third one runs:

    - the ticket names a commit for this handler, and the code is at another one: a stop
      to write down, not an answer;
    - the ticket names one, and the code cannot be read at any commit (no checkout, no
      git): the same — a version that cannot be pinned cannot be checked;
    - the ticket names no commit for this handler: nothing was promised, so nothing is
      broken.
    """
    if running is not None:
        problem = the_interpreter_problem(ticket, running)
        if problem is not None:
            return problem
    if norm is not None:
        problem = the_norm_problem(ticket, norm)
        if problem is not None:
            return problem
    wanted = ticket.api_commit_id_of(handler_name)
    if wanted is None:
        return None
    try:
        mine = code.git_commit(api_path, f"handler {handler_name!r}", ticket.uid)
    except code.Error as broken:
        return str(broken)
    if str(mine) != str(wanted):
        return (f"this ticket asks handler {handler_name!r} at commit {wanted!r}, and "
                f"the code that would answer it is at {mine!r}")
    return None


def answer(ticket: "tickets.Ticket", api, handler_name: str = None, api_path=None,
           running=None, norm=None, tickets_path="", interval=INTERVAL) -> object:
    """Run the ticket's call in the ticket's own environment.

    The call is a viba closure of type `Any <- Env` — the environment left out — and
    `exec` is what gives it one (`viba-interpreter.md`「把一次调用写成可执行的」).
    Nothing of the call's arguments is split apart here: they are inside it, and the
    environment is the only thing missing.

    The environment is the ticket's: its storage root is `$storage_path` (so the
    call's snapshots land there and a second run replays them), and its module search
    path is `$VIBA_PATH`, with the norm repo's checkout first — the code the call names
    is written there. The path travels as one string joined with `os.pathsep`, which is
    the form `Environment.viba_path` takes (the same string `$VIBA_PATH` is stored as).

    Before any of that, the versions have to line up: `handler_name` is who is asking,
    and the ticket's commit members say which viba interpreter, which norm repo and which
    handler's api this run has to be at (`the_commit_id_problem`). Not at them is a stop
    that says so.

    The capabilities around the call are what this role's own module makes of the norm
    repo (`Context.norm`), plus the builtin operators (`ticket_system/builtins.py`). Which
    norm-repo code this role serves is that module's business: this function never guesses
    it from a name (`ticket_system/README.md`「一个角色一张能力表」).
    """
    problem = (the_commit_id_problem(ticket, handler_name, api_path, running, norm)
               if handler_name is not None else None)
    if problem is not None:
        return Err(UnderlyingOpErr(problem, "", handler_name or ""))
    capabilities = _capabilities(api, handler_name or "", tickets_path, interval, norm)
    search = [one for one in list(ticket.viba_path) if one]
    if norm is not None:
        search = [norm.viba_path()] + search
    seen = []
    for one in search:
        if one not in seen:
            seen.append(one)
    environ = Environment(
        EnvironmentStorage("", None, ticket.storage_path),
        EnvironmentCompute(capabilities),
        os.pathsep.join(seen))
    return exec(ticket.call, environ)


def _capabilities(the_api, name, tickets_path, interval, norm):
    """`get_func`: this role's table, then what the ticket's storage remembers, then nobody.

    `the_api` is the role module's function (`MODULE:FUNCTION`): it is asked for the
    table now, with a `Context` that carries this ticket's norm repo, so a role that
    serves norm-repo code answers for the repo this call is written in.

    The run asks by the step's two names (`get_func(module, func_name)`): the module the
    step is declared in, as it was imported (`service_a`), and the name the step has in it
    (`a_add`). A table entry is looked up by both (`service_a.a_add`), and by the bare name
    as well — the builtin operators are one module's steps like any other (`builtin.mul`).

    **A step this role does not serve** is served from the ticket's storage when somebody
    has already recorded it: that is what lets one process's run pass a step another
    process answered, and it is what makes a program whose steps two processes take turns
    at finish at all (`demo/ticket_examples/service_a.py` and `service_b.py`). Which call
    that is — the data path — is on the environment the step is handed, so this decision
    can only be made inside the implementation: the module a step is declared in is known
    when it is asked, where it ran only when it runs. Nothing recorded there is a
    `$not_implemented_err` this layer writes itself (`not_implemented`): viba fills that
    in for a `get_func` that says so, and hands back as it is an error raised from inside
    an implementation.

    A name that is no step of the norm code at all (`__dyn_call__` at the ticket's own
    `$call`, say) is nobody's here, so this answers `None` and viba says it: that step was
    never declared in a module, and this layer has nothing to name it with.
    """
    context = Context(name=name, tickets_path=tickets_path, interval=interval, norm=norm)
    table = dict(the_api(context) or {})
    for name, implementation in builtins.the_table().items():
        table.setdefault(name, implementation)

    def get_func(module, func_name):
        mine = (table.get(f"{module}.{func_name}") if module else None)
        if mine is None:
            mine = table.get(func_name)
        if mine is not None:
            return mine
        if not module or norm is None or not norm.has(module):
            return None                     # 不是 norm 代码里的一步：viba 自己会说

        def from_the_storage(environ, *given):
            """This step's recorded answer, or `$not_implemented_err` when there is none."""
            stored = read_snapshot(environ)
            if stored is not None:
                return stored
            raise not_implemented(module, func_name, given)

        return from_the_storage

    return get_func


def not_implemented(module: str, func_name: str, given=()) -> UnderlyingOpErr:
    """`$not_implemented_err` for a step said from inside an implementation.

    A host that says so from `get_func` need not fill anything in: the run fills the step
    in for it (`viba.interpret._refused`). Said from inside the implementation it cannot —
    the run hands that error back as it is — so the step is written here the way the run
    writes it (`viba-interpreter.md`): `$module_path` is the module read as a path
    (`service_b` is `/service_b`), `$full_qualified_func_name` is the whole name
    (`service_b.b_scale`), and `$call` is the `__dyn_call__` carrying that whole name,
    which is the form a call can be run again from.

    What a host implementation is handed are the values, not the tags they were written
    with (`viba.interpret._argument_value`), so the call carries the values, in written
    order. `given` is the arguments without the environment, which is handed first.
    """
    whole = f"{module}.{func_name}" if module else func_name
    return UnderlyingOpErr(REASON_NO_IMPLEMENTATION,
                           "/" + module.replace(".", "/") if module else "",
                           whole, the_call(whole, *given),
                           tag=NOT_IMPLEMENTED_TAG)


def attempt(ticket, api, handler_name, tickets_path, api_path=None, running=None,
            norm=None, interval=INTERVAL) -> object:
    """Answer one ticket, append the stage for the attempt, and answer the stage.

    What the answer is read as comes back from the log, not from the object that
    was written: a stage is what a reader of the log sees, and the two have to be
    one thing — the value under `$ok` is a leaf there, a viba data here.
    """
    result = answer(ticket, api, handler_name, api_path, running, norm, str(tickets_path),
                    interval)
    value = result.ok_value if hasattr(result, "ok_value") else None
    progress.write_stage(
        tickets_path,
        progress.a_stage(ticket.uid, handler_name, tickets.a_result(result, value)))
    return progress.latest(tickets_path, ticket.uid)


class Handler:
    """One handler process: its name, its capability table, and its poll loop."""

    def __init__(self, name: str, api, tickets_path, interval: float = INTERVAL,
                 again: bool = False, api_path=None, running=None):
        self.name = name
        # The role module's function (`MODULE:FUNCTION`), asked for the capability table
        # once per call — with the norm repo that call names (`_capabilities`).
        self.api = api
        self.tickets_path = Path(tickets_path)
        self.interval = interval
        # Where this process's api was loaded from: its commit is read there, and a
        # ticket that names a commit for this handler is only answered at that one
        # (`the_commit_id_problem`). Nothing here is taken on the process's word.
        self.api_path = api_path
        # The commit of the interpreter this process runs: read once, at startup, from
        # the package itself. It cannot change for the life of the process, which is
        # what makes it the honest answer to "which interpreter would run this".
        self.running = running if running is not None else the_running_interpreter()
        # One `NormRepo` per norm repo this process has served, made on demand: the tree
        # of a commit is read out once, and then by every ticket that names it.
        self.norms = {}
        # `again` is for showing what a ticket's storage is: with it, this process
        # attempts every ticket twice, which is what makes the second attempt
        # replay the first one's snapshot.
        self.again = again
        # (ticket uid, handler name) -> how often this process has attempted that ticket.
        # It is the report's attempt number, and it is what `again` counts to two; whose
        # turn it is is not kept here but read off the log (`the_latest_is_mine`), because
        # another process may have moved that ticket since this one last looked.
        self.done = {}

    # ---- the poll ----

    def tick(self) -> list:
        """One poll: take every ticket this handler is free to take.

        Answers what it did, one note per attempt — what the reports carry.

        **Whose turn it is** is read off the log, and it is what makes the processes take
        turns at one ticket: this handler takes a ticket whose progress holds no `$ok`
        and whose newest stage is **not this handler's own**. Written the other way round
        — one attempt per ticket per process — a program whose steps two processes take
        turns at could never be finished: the second process advances the ticket by a
        step, and the first one would have to take it again to advance the next, which is
        the round this rule allows and that one forbids
        (`viba_ticket/two_handlers/the_program.viba` is such a program).

        The ticket's state is read again before every attempt, not once per poll: two
        handlers run at once over one tickets path, so a ticket this process found
        unfinished a moment ago may have been answered by the other one since, and
        attempting it again would only write a stop next to an answer
        (`progress.answered`). The re-read makes that window a few milliseconds wide
        instead of a whole poll. (`again` is the one thing that looks at a finished
        ticket on purpose: it attempts every ticket twice, which is how a ticket's storage is
        shown to answer the second attempt.)
        """
        notes = []
        for uid in tickets.ticket_uids(self.tickets_path):
            if progress.answered(self.tickets_path, uid):
                continue
            key = (uid, self.name)
            if not self.again:
                if self.the_latest_is_mine(uid):
                    # 上一篇是我写的：这张票据还没做完，但下一手不是我的 —— 等别人。
                    continue
                # 这一手只做一次；下一手要等别人写过一篇之后才轮到我。
                wanted = self.done.get(key, 0) + 1
            else:
                wanted = 2
            while self.done.get(key, 0) < wanted:
                if not self.again and progress.answered(self.tickets_path, uid):
                    notes.append({"ticket": uid, "handler": self.name,
                                  "attempt": self.done.get(key, 0),
                                  "result": "answered_elsewhere"})
                    break
                ticket = tickets.read_ticket(self.tickets_path, uid)
                if ticket is None:
                    break
                self.done[key] = self.done.get(key, 0) + 1
                stage = attempt(ticket, self.api, self.name, self.tickets_path,
                                self.api_path, self.running, self.norm_for(ticket),
                                self.interval)
                notes.append({"ticket": uid, "handler": self.name,
                              "attempt": self.done[key],
                              "result": "ok" if stage.is_ok() else "stopped"})
        return notes

    def the_latest_is_mine(self, uid: str) -> bool:
        """Did this process write the newest stage of that ticket?

        A ticket nobody has tried is nobody's, so it is this process's to take.
        """
        last = progress.latest(self.tickets_path, uid)
        return last is not None and last.handler_name == self.name

    def norm_for(self, ticket):
        """This ticket's norm repo, with its commit read out (once per repo and commit)."""
        key = (str(ticket.norm_repo_path), str(ticket.norm_repo_commit_id))
        if key not in self.norms:
            self.norms[key] = repo.NormRepo(ticket.norm_repo_path,
                                            ticket.norm_repo_commit_id,
                                            self.tickets_path)
        return self.norms[key]

    def run(self, ticks=None) -> dict:
        """Poll until every ticket is finished, or until `ticks` polls are made.

        `ticks` is for a run that is to end by itself: with it, the loop makes that
        many polls whether or not the tickets are finished, which is what a test
        wants. Without it, the loop ends on the stop condition — every ticket's
        progress holding a `$ok`.
        """
        polls = 0
        notes = []
        while True:
            notes += self.tick()
            polls += 1
            if progress.finished(self.tickets_path):
                break
            if ticks is not None and polls >= ticks:
                break
            time.sleep(self.interval)
        return {"handler": self.name, "polls": polls, "notes": notes,
                "finished": progress.finished(self.tickets_path)}


def load_api(spec: str):
    """`module:function` from the command line, as the role's api function.

    That function answers the capability table `{func_name: implementation}` when it is
    handed a `Context`; an implementation takes the environment the call runs in and one
    value per argument of the call (`(environ, x)`, `(environ, x, y)`, …), the way an
    implementation of `get_func` does, and answers one value. It is asked per call, with
    the norm repo that call names (`_capabilities`).
    """
    module_name, _, function_name = spec.partition(":")
    if not module_name or not function_name:
        raise SystemExit(f"--api wants MODULE:FUNCTION, not {spec!r}")
    module = __import__(module_name, fromlist=[function_name])
    return getattr(module, function_name)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="one ticket handler process")
    parser.add_argument("--tickets", required=True, help="the tickets path")
    parser.add_argument("--handler", required=True,
                        help="this process's name, which its stages carry")
    parser.add_argument("--api", required=True, metavar="MODULE:FUNCTION",
                        help="the capability table: a function from the context "
                             "to {func_name: implementation}")
    parser.add_argument("--interval", type=float, default=INTERVAL,
                        help=f"seconds between two polls (default {INTERVAL})")
    parser.add_argument("--ticks", type=int, default=None,
                        help="stop after this many polls even when a ticket is not "
                             "finished yet (default: only the stop condition stops)")
    parser.add_argument("--again", action="store_true",
                        help="attempt every ticket twice, so the second attempt "
                             "replays the answer the first one stored")
    options = parser.parse_args(argv)

    handler = Handler(options.handler, load_api(options.api),
                      options.tickets, options.interval, options.again,
                      where_the_api_is(options.api))

    def stop(_number, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    try:
        report = handler.run(options.ticks)
    except KeyboardInterrupt:
        report = {"handler": handler.name, "polls": None, "notes": [],
                  "finished": progress.finished(handler.tickets_path),
                  "stopped": "signal"}
    report["api_path"] = handler.api_path
    print(json.dumps(report), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
