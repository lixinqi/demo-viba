"""The scheduler: rounds over the services of one distributed viba program.

Every round starts every service process at once, twice:

- the **answer** phase: each service fills in what the round before left for it (a
  stopped run leaves viba code under the call's storage path,
  `<storage path>/call/<api>.viba` — `service.py` says what is in it), so that
  every run of the next phase starts from the same store;
- the **run** phase: each service runs the distributed program once and reports what
  came out.

A round that ends with a deferral is saved — this round's failure state — into the
store the rounds share: the deferral itself as viba code at the storage path the run
stopped at (`<storage path>/call/<api>.viba`), and the round as a record
(`failure/round-<k>.viba`). The next round's answer phase reads those, so the front of
the program moves on: a call deferred once is answered before the next round runs.

A round that ends with `ok` on either service is the last round. A round that defers a
call that was deferred before — the program did not move — and the round cap both end
the schedule with a failure, so a schedule that cannot finish is reported instead of
looping.

The scheduler holds no program and no api of its own: the program comes from
`--program`, and each `--service NAME=MODULE` names a module whose `__main__` runs
`distributed.service.run_service` with that service's api. `demo/distributed/naive/`
(two services), `demo/distributed/delivery/` (three) and `demo/distributed/reading/`
(five, one operation each) are three such sets of modules.

    python3 -m distributed.scheduler --store <directory> --program <file> \\
        --service <name>=<module> --service <name>=<module>

It prints one JSON line per round and one line for the outcome; the exit code is 0 for
a schedule that reached `ok`.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

from viba import viba_ast
from compliance import call_path
from distributed import service
from viba.interpret import snapshot_path, put_snapshot

# How long one service process may take. A schedule that hangs is a failure to
# report, not a schedule to wait for.
TIMEOUT = 60

DEFAULT_ROUNDS = 1024


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="run the services of a distributed viba program, round after round")
    parser.add_argument("--store", required=True,
                        help="the environment storage every round shares")
    parser.add_argument("--program", required=True,
                        help="the distributed viba program")
    parser.add_argument("--service", action="append", required=True,
                        metavar="NAME=MODULE",
                        help="one service: the name its reports and the round record "
                             "use, and the python module that serves it (repeat for "
                             "each service)")
    parser.add_argument("--rounds", type=int, default=DEFAULT_ROUNDS,
                        help="the most rounds one schedule may take")
    options = parser.parse_args(argv)
    options.program = str(Path(options.program).resolve())
    services = [the_service(one) for one in options.service]

    deferred_before = set()
    for number in range(1, options.rounds + 1):
        answers = the_phase("answer", services, options)
        runs = the_phase("run", services, options)
        broken = [one for one in list(answers.values()) + list(runs.values())
                  if one.get("result") in ("crashed", "failed", "program_err")]
        if broken:
            return the_outcome({"outcome": "broken", "round": number, "reports": broken})
        deferred = [the_deferral(one) for one in runs.values()
                    if one["result"] == "not_my_duty"]
        save_the_failure(services, options.store, number, deferred)
        print(json.dumps({"round": number,
                          "answered": answers,
                          "runs": runs,
                          "deferred": deferred}), flush=True)

        repeated = [one for one in deferred
                    if (one["path"], one["func_name"]) in deferred_before]
        if repeated:
            return the_outcome({"outcome": "stuck", "round": number, "repeated": repeated})
        deferred_before |= {(one["path"], one["func_name"]) for one in deferred}

        finished = [one for one in runs.values() if one["result"] == "ok"]
        if finished:
            return the_outcome({"outcome": "ok", "rounds": number,
                                "service": finished[0]["service"],
                                "value": finished[0]["value"]})
    return the_outcome({"outcome": "unfinished", "rounds": options.rounds})


def the_service(spec: str) -> tuple:
    """One `NAME=MODULE` from the command line, as (name, module)."""
    name, _, module = spec.partition("=")
    if not name or not module:
        raise SystemExit(f"--service wants NAME=MODULE, not {spec!r}")
    return name, module


def the_phase(phase: str, services: list, options) -> dict:
    """Start every service at once and collect what each of them reported."""
    processes = {name: start(name, module, phase, options)
                 for name, module in services}
    return {name: the_report(name, phase, process)
            for name, process in processes.items()}


def start(name: str, module: str, phase: str, options) -> subprocess.Popen:
    """One service process, in the phase it was asked for."""
    return subprocess.Popen(
        [sys.executable, "-m", module,
         "--store", str(options.store), "--phase", phase,
         "--program", str(options.program)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def the_report(name: str, phase: str, process: subprocess.Popen) -> dict:
    """What one service reported: its JSON line, or why there was none."""
    try:
        out, err = process.communicate(timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
        return {"service": name, "phase": phase, "result": "crashed",
                "error": f"the service did not answer within {TIMEOUT} s"}
    line = next((one for one in reversed(out.splitlines()) if one.strip().startswith("{")),
                None)
    if process.returncode != 0 or line is None:
        return {"service": name, "phase": phase, "result": "crashed",
                "error": (err or out).strip()[-2000:]}
    try:
        return json.loads(line)
    except json.JSONDecodeError as problem:
        return {"service": name, "phase": phase, "result": "crashed",
                "error": f"the service's report is no JSON ({problem}): {line[:400]}"}


def the_deferral(report: dict) -> dict:
    """The failure state a stopped run reports, as the scheduler reads it."""
    return {"service": report["service"], "path": report["path"],
            "func_name": report["func_name"], "reason": report["reason"],
            "call": report["call"]}


def save_the_failure(services: list, store, number: int, deferred: list) -> None:
    """This round's failure state, into the store the rounds share.

    Each deferral becomes viba code where the run stopped: the call the run handed
    over (written as it can be run again, its `$result` still nil), written under the
    call's storage path (`<storage path>/call/<api>.viba`). The round itself becomes a
    record, `failure/round-<number>.viba`, naming every call that stopped it.
    """
    for one in deferred:
        environ = service.environ_at(one["path"], store)
        environ.storage.put_text(
            snapshot_path(environ, call_path(one["func_name"])), one["call"])
    record = viba_ast.ProductChain(
        [viba_ast.Tagged("$round", viba_ast.Constant(number))]
        + [viba_ast.Tagged(f"${name}", the_services_deferral(deferred, name))
           for name, _module in services])
    put_snapshot(service.environ_at("", store), record, f"failure/round-{number}")


def the_services_deferral(deferred: list, name: str):
    """The one call that service stopped at, as viba data — or nil when it finished."""
    for one in deferred:
        if one["service"] == name:
            return viba_ast.ProductChain([
                viba_ast.Tagged("$path", viba_ast.Constant(one["path"])),
                viba_ast.Tagged("$func_name", viba_ast.Constant(one["func_name"])),
                viba_ast.Tagged("$reason", viba_ast.Constant(one["reason"] or "")),
                viba_ast.Tagged("$call_path", viba_ast.Constant(
                    f"{one['path']}/call/{one['func_name']}.viba")),
            ])
    return viba_ast.Nil()


def the_outcome(outcome: dict) -> int:
    """Print the outcome of the schedule and say with the exit code whether it is one."""
    print(json.dumps(outcome), flush=True)
    return 0 if outcome["outcome"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
