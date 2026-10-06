# The delivery demo

The second worked program of the [`distributed`](../../../distributed/README.md) package:
three services, other names, other types. The first one is
[`demo/distributed/naive/`](../naive/), and it is the one
[`viba-distributed.md`](../../../viba-distributed.md) walks through; this one is here to
show that the scheduler and the service process know nothing about the program they run.

## The program

`estimate.viba` says how long a parcel takes: the weight is read off a scale in the
`parcels` service, the packing weight is added there too, the `couriers` service says how
many days that weight takes, and the `notices` service writes the days as a notice and
puts the notice in upper case. Five calls, and each one's argument is the call before it —
so the three services can only take turns.

Every call runs at a sub-environment of its own, all of them below the one named `order`:
`read_scale` at `root/order/weight`, `add_handling` at `root/order/handling`, and so on.
That path is the call's storage path.

Each service's api is a file of leaves beside the program — `parcels.viba`, `couriers.viba`,
`notices.viba` — and the program imports them. One leaf is impure: `parcels.read_scale`
draws the weight off the scale in the process that owns it. The other four are pure. All
five go through `Service.recorded`, so the first result of each is written into the store,
and every later run in any service replays it instead of computing it again.

## Run it

```bash
python3 -m distributed.scheduler --store /tmp/distributed-delivery-store \
    --program demo/distributed/delivery/estimate.viba \
    --service parcels=demo.distributed.delivery.parcels \
    --service couriers=demo.distributed.delivery.couriers \
    --service notices=demo.distributed.delivery.notices
```

Run it from the repository root: the services are named by python module path. One line of
JSON per round on stdout, and one line for the outcome; the exit code is 0 when a service
reported `ok`. The demo's own test:

```bash
python3 demo/distributed/delivery/test_delivery.py
```

## The files

| File | What it is |
|---|---|
| `estimate.viba` | The distributed program: imports the three api files and writes five calls, each at a sub-environment below `root/order/` |
| `parcels.viba` | The parcels api as viba code — the two signatures `read_scale` and `add_handling`, with the hint each one implements |
| `couriers.viba` | The couriers api as viba code — `days_for` |
| `notices.viba` | The notices api as viba code — `announce`, `emphasize` |
| `parcels.py` | The parcels implementations — `read_scale` draws the weight, `add_handling` adds the packing — and the process that serves them |
| `couriers.py` | The couriers implementation — `days_for` — and the process that serves it |
| `notices.py` | The notices implementations — `announce` writes the notice, `emphasize` puts it in upper case — and the process that serves them |
| `test_delivery.py` | The demo's test (below) |
| `README.md` | This file |

## What the test checks

- every round starts all three services, the last round reports `ok` on one of them, and
  every round before it stopped at a deferral;
- no storage path is stopped at twice across rounds, and each of the five calls is computed
  exactly once — the records in the store are the evidence;
- the store holds the chain's five results under `root/order/`, and each one follows from
  the weight the scale drew;
- a second schedule on the same store finishes in one round and computes nothing.

The store layout, the reports, the two phases of a round, and the outcome kinds are in
[`distributed/README.md`](../../../distributed/README.md); `stuck`, `unfinished` and
`broken` are covered by the naive demo's test.
