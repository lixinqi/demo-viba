"""The naive distributed demo: one viba program whose steps two services take turns at.

The demo runs on the `distributed` package
([`distributed/README.md`](../../../distributed/README.md)): `distributed/service.py` is one
service process's side, `distributed/scheduler.py` is the round scheduler. What lives
here is the demo's own side — the program, its two api, and its test:

    python3 -m distributed.scheduler --store <dir> \\
        --program demo/distributed/naive/interleaved.viba \\
        --service a=demo.distributed.naive.service_a \\
        --service b=demo.distributed.naive.service_b

[`viba-distributed.md`](../../../viba-distributed.md) is the chapter over it. The other demo
beside this one is [`demo/distributed/delivery/`](../delivery/): three services, other
names, other types.
"""

from pathlib import Path

PROGRAM = str(Path(__file__).resolve().parent / "interleaved.viba")

# What the scheduler is given: one `NAME=MODULE` per service of this demo.
SERVICES = ("a=demo.distributed.naive.service_a", "b=demo.distributed.naive.service_b")

__all__ = ["PROGRAM", "SERVICES"]
