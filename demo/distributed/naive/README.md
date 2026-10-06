# The naive distributed demo

One viba program whose steps two services take turns at: the worked example of
[`viba-distributed.md`](../../../viba-distributed.md). The two modules that run it are the
[`distributed`](../../../distributed/README.md) package; what lives here is the demo's own
side — the program, its two api, and its test. The other demo beside this one is
[`demo/distributed/delivery/`](../delivery/): three services, other names, other types, and
its own test.

## The program

`interleaved.viba` is the program: it imports the two api files — `service_a.viba` and
`service_b.viba` — and writes five calls, the api of A and B alternating (`service_a.a_step`,
then `service_b.b_step`, and so on), each call at a sub-environment of its own (that path
is the call's storage path). Every call's argument is the call before it, so the two
service processes can only take turns, and neither can finish the program alone.

Each api file is that service's side of the design: four leaves in all, an int in and an
int out each. `a_step` and `b_step` add an amount, `a_scale` and `b_scale` multiply by
one, and the amount is drawn in the service that owns it. `Service.recorded` is what keeps
the program reproducible: the result is written into the store, so every later run replays
it instead of drawing again.

## Run it

```bash
python3 -m distributed.scheduler --store /tmp/distributed-naive-store \
    --program demo/distributed/naive/interleaved.viba \
    --service a=demo.distributed.naive.service_a \
    --service b=demo.distributed.naive.service_b
```

Run it from the repository root: the services are named by python module path. One line of
JSON per round on stdout, and one line for the outcome; the exit code is 0 when a service
reported `ok`. The demo's own test:

```bash
python3 demo/distributed/naive/test_distributed.py
```

## The files

| File | What it is |
|---|---|
| `interleaved.viba` | The distributed program: imports the two api files and writes five calls, A's and B's api alternating, each call at a sub-environment of its own |
| `service_a.viba` | Service A's api as viba code — the two signatures `a_step` and `a_scale`, with the hint each one implements |
| `service_b.viba` | Service B's api as viba code — `b_step`, `b_scale` |
| `service_a.py` | Service A's implementations — `a_step` adds, `a_scale` multiplies — and the process that serves them |
| `service_b.py` | Service B's implementations — `b_step`, `b_scale` — and the process that serves them |
| `test_distributed.py` | The demo's test (below) |
| `README.md` | This file |

## What the test checks

- the last round reports `ok` on one service, and every round before it stopped at a
  deferral;
- no storage path is stopped at twice, and each api call of the chain is computed exactly
  once (the records in the store are the evidence);
- a second schedule on the same store finishes in one round and computes nothing;
- a call nobody implements is reported as `stuck` instead of looping, the round cap as
  `unfinished`, and a service that cannot start as `broken`.

The store layout, the reports, and the handles are in
[`distributed/README.md`](../../../distributed/README.md).
