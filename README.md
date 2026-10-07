# demo-viba

Worked examples over [`viba`](viba/) (a git submodule of
[`git@github.com:lixinqi/viba.git`](https://github.com/lixinqi/viba), tracked on `main`):
three layers, each a chapter and a package, plus the demos that run them.

| Layer | The chapter | The package | The examples |
|---|---|---|---|
| Compliance: a rule is a program, and a call is measured once | [`viba-compliance.md`](viba-compliance.md) | [`compliance/`](compliance/) | [`compliance/demo/`](compliance/demo/) |
| Distributed: one program over several services and one store | [`viba-distributed.md`](viba-distributed.md) | [`distributed/`](distributed/) | [`demo/distributed/`](demo/distributed/) |
| Tickets: one call written on the file system, and the roles that answer it | [`viba-ticket.md`](viba-ticket.md) | [`ticket_system/`](ticket_system/) | [`viba_ticket/`](viba_ticket/) + [`demo/ticket_examples/`](demo/ticket_examples/) |

Each layer's viba code is beside its examples: the distributed demos write their programs
in `demo/distributed/`, and the ticket layer's norm repos are
[`viba_ticket/two_handlers/`](viba_ticket/two_handlers/) and
[`viba_ticket/add_one/`](viba_ticket/add_one/), with the roles that serve them in
[`demo/ticket_examples/`](demo/ticket_examples/). The ticket type itself is
[`viba_ticket/ticket_design.viba`](viba_ticket/ticket_design.viba) — the ticket and the
progress log both.

## Run the suites

Every suite is a script with its own counter; run it from this directory. They need the
submodule's python package, so its directory comes first on `PYTHONPATH`:

```bash
export PYTHONPATH=$PWD/viba:$PWD:$PYTHONPATH

python3 tests/test_documents.py           # every viba block in the documents compiles
python3 tests/test_compliance.py
python3 tests/test_distributed_service.py
python3 tests/test_ticket_system.py
python3 demo/distributed/naive/test_distributed.py
python3 demo/distributed/delivery/test_delivery.py
python3 demo/distributed/reading/test_reading.py
```

The suites that start processes (`demo/distributed/` and `tests/test_ticket_system.py`)
run them with this same `PYTHONPATH`; `tests/test_ticket_system.py` sets it for its own
subprocesses.
