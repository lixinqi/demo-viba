# The distributed demos

Three viba programs that run on [`distributed/`](../../distributed/README.md): one service
process per service, one store they share, one scheduler. None of them is part of the
package — the package holds no program and no api of its own, and these are three programs
with the api and the tests that go with them.

| Demo | Services | What it is |
|---|---|---|
| [`naive/`](naive/) | 2 | Two api each (`a_step`, `a_scale` / `b_step`, `b_scale`), five int calls alternating them; the worked example of [`viba-distributed.md`](../../viba-distributed.md) |
| [`delivery/`](delivery/) | 3 | One service for the weight, one for the days, one for the notice; a chain of ints that ends in a str, every data path below the one sub-environment `order` |
| [`reading/`](reading/) | 5 | One operation per service, five steps that change type five times (int, float, str, int, bool), every data path below the program's own environment, and one call written that nothing needs |

Run one from the repository root; the command that fills in its names and modules is in that
demo's README. The three tests:

```bash
python3 demo/distributed/naive/test_distributed.py
python3 demo/distributed/delivery/test_delivery.py
python3 demo/distributed/reading/test_reading.py
```

How many services there are, what they are named, how many api each of them owns, what
types travel, where the data paths sit, and whether every call written is needed — the
scheduler is given none of that and does not ask: it starts the modules it was handed and
reads back their reports. The store layout, the two phases of a round, the reports, and the
outcome kinds are in [`distributed/README.md`](../../distributed/README.md).
