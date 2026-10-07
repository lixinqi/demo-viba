# distributed

Run one viba program on several services and one store. The package holds no program
and no api of its own — the caller brings both:

| Module | What it is |
|---|---|
| `service.py` | One service process's side: its api, the store it shares, the calls it answers, and the JSON report it prints |
| `scheduler.py` | The rounds over the services: the two phases, the failure state in the store, the outcome |

[`viba-distributed.md`](../viba-distributed.md) is the chapter over both;
[`demo/distributed/`](../demo/distributed/) holds three worked examples: two services in
[`naive/`](../demo/distributed/naive/), three in [`delivery/`](../demo/distributed/delivery/),
and five — one operation each — in [`reading/`](../demo/distributed/reading/).

## Run it

```bash
python3 -m distributed.scheduler --store <directory> --program <file> \
    --service <name>=<module> --service <name>=<module>
```

`--service NAME=MODULE` says two things: `NAME` is what the reports and the round record
call that service, and `MODULE` is a python module whose `__main__` runs
`distributed.service.run_service` with that service's api. One `--service` per service,
as many as the program has — the names and the modules are the caller's, and the scheduler
knows nothing about them beyond how to start them. Run it where `MODULE` is importable.

A command that runs a real program, with the names and modules filled in, is in each
demo's own README: [`naive/README.md`](../demo/distributed/naive/README.md) for two
services, [`delivery/README.md`](../demo/distributed/delivery/README.md) for three,
[`reading/README.md`](../demo/distributed/reading/README.md) for five.

The scheduler prints one JSON line per round and one line for the outcome:

```json
{"outcome": "ok", "rounds": 2, "service": "b", "value": 165}
```

The exit code is 0 for a schedule that reached `ok`, 1 for one that did not
(`stuck` — the program did not move; `unfinished` — the round cap; `broken` — a service
crashed or a step's implementation failed). `--rounds` (default 1024) is the cap.

## A service process

One service is one process, started by the scheduler twice per round:

```bash
python3 -m some.package.service_a --store /tmp/store --phase answer|run \
    --program path/to/program.viba
```

- `--phase answer`: run the calls the store holds under this service's api names — what an
  earlier round left behind;
- `--phase run`: run the program once.

Either way the process prints one JSON line, which is its report:

```json
{"service": "a", "phase": "run", "api": [{"path": "root/c0", "computed": true, "value": 9}],
 "result": "not_my_duty", "reason": "no implementation", "path": "root/c1",
 "func_name": "b_step", "call": "value =\n  $call (__dyn_call__ << \"b_step\" << 9)\n  * $result nil\n"}
```

A module serves a service by naming its api — a function from a `Service` to
`{func_name: implementation}`, where an implementation takes the environment and one value
per argument of the call (`(environ, x)`, `(environ, x, y)`, …) and answers one result.
`demo/distributed/naive/service_a.py` is one; everything in it but the imports and the
docstring:

```python
def the_api(service):
    def a_step(environ, x):
        return service.recorded(environ, lambda: int(x.value) + random.randrange(1, 10))

    def a_scale(environ, x):
        return service.recorded(environ, lambda: int(x.value) * random.randrange(2, 5))

    return {"a_step": a_step, "a_scale": a_scale}


def main(argv=None) -> int:
    return run_service("a", the_api, argv)
```

A work order keeps the call itself, so a service that fills one in does not piece the
arguments together again: it runs the call (`exec`, the call's own data), and viba hands the
implementation the arguments exactly as the stopped run would have — one per argument, in
written order, the environment first. A call that was given a host value beside the
environment is not written into `$call` at all: viba leaves it out, so what a work order
keeps is the call that can be made again.

## The round

Every round starts every service at once, twice: the **answer** phase first, then the
**run** phase. The order cannot be swapped — with a call still owed in the store, the
run stops at the same storage path a second time.

A round that ends with a deferral leaves its failure state in the store in two places:
viba code under the call's storage path (`<storage path>/call/<api>.viba`), and the
round as a record, `failure/round-<k>.viba`, naming where each service stopped and where
its file is.

## What the store holds

| Path | What it is |
|---|---|
| `<storage path>/call/<api>.viba` | viba code (the call itself, `$result` still to come) under the call's storage path |
| `<storage path>/value.viba` | The result of that call — what `replayed` reads and writes, and what a replay reads |
| `failure/round-<k>.viba` | That round's failure state: which service stopped where, and where the first file is |

A run that reaches a step its host has no implementation for does not fail: it stops
with the **deferral** — `$err InterpretError`, the third stop of an `interpret` result,
`$not_implemented_err UnderlyingOpErr` ([`viba-interpreter.md`](../viba/viba-interpreter.md)
writes all of them out):

```viba
InterpretResult =
    Oneof
  | $ok VibaNode
  | $err InterpretError

InterpretError =
    Oneof
  | $viba_program_err ProgramErr                 # the program, or the environment
  | $underlying_viba_op_err UnderlyingOpErr      # that step broke
  | $not_implemented_err UnderlyingOpErr         # nothing implements that step

UnderlyingOpErr =
    Object
  * $msg str                                     # one sentence, the reason first
  * $module_path str                             # the definition, at that storage path
  * $func_name str                               # the name the step asks for
  * $call (Any <- $env Env)                      # the call itself, as it was written
```

- `$module_path` is the call's **storage path** — the path of the child environment the
  call was given (`root/c1` here); `$func_name` is the name it asks for (`b_step` here),
  the one this process has no implementation for.
- `$call` is **the call itself**, as it was written: `__dyn_call__ << "b_step" << 9`, the
  name and the arguments written on it, each with the tag it was written with. It is
  serializable viba data, and giving it an environment is what running it is, so the call
  can be made again from this result alone. The environment is not part of it — whoever
  runs the call makes its own.
- `$msg` is **why it stopped**: one sentence, the reason first — `no implementation` here.

The scheduler writes that call into the store. What is written has only two parts, and
neither works without the other:

- **viba code**: the file's content — one definition, `value`, with two members: `$call`
  (the call itself, runnable) and `$result` (what it answered, `nil` until someone runs it);
- **the storage path**: where it is written — the path the run stopped at, with the api it
  asks for as the file name.

```viba
# <storage path>/call/<api>.viba
value =
  $call (__dyn_call__ << "b_step" << 9)  # the call itself
  * $result nil                          # what it answered, not computed yet
```

Each part carries half, so five things have their place:

| What you want to know | Where it is |
|---|---|
| which step | the storage path: the `<storage path>` piece (the `$module_path`) |
| which api | the storage path: the file name `<api>` (the `$func_name`) |
| which call to make | the viba code: `$call` (runnable; the arguments are in it) |
| what is still missing | the viba code: the nil `$result`; and the result file under that storage path, `<storage path>/value.viba` |
| where the result goes | `<storage path>/value.viba` under the same storage path — the file `replayed` reads and writes |

Those two parts together are the **viba work order**: whoever has `<api>` in its capability
table can take it, run the call, and write the answer back without knowing anything else
about the run — the call comes from the work order, and where the answer goes is the work
order's own storage path. What a run reads is the result file there,
`<storage path>/value.viba` (`replayed`'s file; the name is viba's own snapshot convention,
see [`viba-interpreter.md`](../viba/viba-interpreter.md)). The answer phase writes the same
answer into the work order's `$result` as well — that is its own record: the next answer
phase replays it instead of running the call again. No execution state travels; the files
in the store are the whole of it.

Both services read and write one store at the same time, so a snapshot is written whole
or not at all (it is written beside the path and renamed onto it — see
[`viba-interpreter.md`](../viba/viba-interpreter.md), the chapter on snapshots and replay).
What a reader gets is either nothing yet or one complete file, never half of one.

Replay has no source but the store: one step's result lands in two places
(`<storage path>/value.viba` and the work order's `$result`), and a run does not report
it when they disagree — delete `value.viba` and keep a filled `$result` and the step is
computed again while the steps after it still replay the earlier run, so one chain mixes
the results of two runs and the schedule still says `ok`.

## The handles

| Name | What it is |
|---|---|
| `Service` (`service.py`) | One process's side: the api table, the shared store, `get_func` (the capability table), `answer_pending` (fill in what this service owes), `run_program` (run the program once and report it) |
| `Service.recorded` | What an implementation goes through: `replayed` — compute the result once, record it, replay it from then on |
| `Service.get_func` | A call of this service's api goes to its own implementation; a call of another service's api is replayed from the store when the store already holds that call's result; with neither the result is `None`, and the run stops with the deferral |
| `Service.pending` | The work orders under this service's api names that have no answer yet |
| `run_service(name, api, argv)` | One service process's `__main__`: `--store`, `--phase answer\|run`, `--program` |
| `environ_at(module_path, store, ...)` | An environment at a store path — what a tool reads the store through |
| `distributed.scheduler.main` | The schedule: the rounds, filling in what is owed and running the program, the failure state, `--rounds` (default 1024) |
| `python3 -m distributed.scheduler --store <dir> --program <file> --service <name>=<module>` | Run one schedule; one JSON line per round on stdout, the last one the outcome |

## Where it is tested

`tests/test_distributed_service.py` covers this module's own side: how many arguments an
implementation takes, how a work order's `$call` is split back into them, and a whole
schedule in which a call with two arguments is answered from its work order. The demos'
tests (`demo/distributed/*/test_*.py`) cover whole schedules, each with its own program and
its own services.
