"""The delivery demo: one viba program whose steps three services take turns at.

The demo runs on the `distributed` package
([`distributed/README.md`](../../../distributed/README.md)): `distributed/service.py` is one
service process's side, `distributed/scheduler.py` is the round scheduler. What lives
here is the demo's own side — the program, its three api, and its test:

    python3 -m distributed.scheduler --store <dir> \\
        --program demo/distributed/delivery/estimate.viba \\
        --service parcels=demo.distributed.delivery.parcels \\
        --service couriers=demo.distributed.delivery.couriers \\
        --service notices=demo.distributed.delivery.notices

Nothing of this demo is in the framework: the other demo beside it is
[`demo/distributed/naive/`](../naive/) — two services, other names, other types — and the
same `distributed.scheduler` runs both.
"""

from pathlib import Path

PROGRAM = str(Path(__file__).resolve().parent / "estimate.viba")

# What the scheduler is given: one `NAME=MODULE` per service of this demo.
SERVICES = ("parcels=demo.distributed.delivery.parcels",
            "couriers=demo.distributed.delivery.couriers",
            "notices=demo.distributed.delivery.notices")

__all__ = ["PROGRAM", "SERVICES"]
