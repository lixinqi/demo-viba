# The reading demo

The third worked program of the [`distributed`](../../../distributed/README.md) package:
five services, one operation each. The other two are
[`demo/distributed/naive/`](../naive/) (two services, the one
[`viba-distributed.md`](../../../viba-distributed.md) walks through) and
[`demo/distributed/delivery/`](../delivery/) (three services).

## The program

`reading.viba` takes one reading and asks whether its label is over the limit. Five calls,
one service for each of them, and each one's argument is the call before it:

| Call | Service | Type in → out | What it does |
|---|---|---|---|
| `gauge.take` | `gauge.py` | int → int | draws the reading (impure) |
| `factor.times` | `factor.py` | int → float | writes the reading in the label's unit |
| `label.write` | `label.py` | float → str | writes the number as text |
| `length.count` | `length.py` | str → int | counts the characters of that text |
| `check.over` | `check.py` | int → bool | whether the count is over the limit |

So the chain changes type five times and the program's own answer is a bool. Every call runs
at a sub-environment of its own, directly below the program's environment, and the name says
what the call is: `root/taken`, `root/factored`, `root/labelled`, `root/counted`,
`root/checked`. That path is the call's storage path. One of the five (`gauge.take`) is
impure; all five go through `Service.recorded`, so each result is written into the store and
every later run in any service replays it.

`reading.viba` also defines `spare`, a second `factor.times` call that nothing needs: viba
computes a definition only when something asks for it, so no round ever takes that call and
nothing is written under `root/spare`.

## Run it

```bash
python3 -m distributed.scheduler --store /tmp/distributed-reading-store \
    --program demo/distributed/reading/reading.viba \
    --service gauge=demo.distributed.reading.gauge \
    --service factor=demo.distributed.reading.factor \
    --service label=demo.distributed.reading.label \
    --service length=demo.distributed.reading.length \
    --service check=demo.distributed.reading.check
```

Run it from the repository root: the services are named by python module path. One line of
JSON per round on stdout, and one line for the outcome; the exit code is 0 when a service
reported `ok`. The demo's own test:

```bash
python3 demo/distributed/reading/test_reading.py
```

## The files

| File | What it is |
|---|---|
| `reading.viba` | The distributed program: imports the five api files and writes the chain, each call at a sub-environment of its own |
| `gauge.viba`, `factor.viba`, `label.viba`, `length.viba`, `check.viba` | The five api as viba code, one leaf each, with the hint that leaf's process implements |
| `gauge.py`, `factor.py`, `label.py`, `length.py`, `check.py` | The five implementations and the processes that serve them |
| `test_reading.py` | The demo's test (below) |
| `README.md` | This file |

## What the test checks

- every round starts all five services, the last round reports `ok` on one of them, and
  every round before it stopped at a deferral;
- no storage path is stopped at twice across rounds, and each of the five calls is computed
  exactly once — the records in the store are the evidence;
- the call nothing needs is never taken: no round stops at `root/spare`, and nothing is
  written under it;
- the store holds the chain's five results under the program's own environment, and they
  follow from the reading the gauge drew, across all four types;
- a second schedule on the same store finishes in one round and computes nothing.

The store layout, the reports, the two phases of a round, and the outcome kinds are in
[`distributed/README.md`](../../../distributed/README.md); `stuck`, `unfinished` and
`broken` are covered by the naive demo's test.
