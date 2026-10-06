"""The reading demo: one viba program whose steps five services take turns at.

The demo runs on the `distributed` package
([`distributed/README.md`](../../../distributed/README.md)): `distributed/service.py` is one
service process's side, `distributed/scheduler.py` is the round scheduler. What lives
here is the demo's own side — the program, its five api, and its test:

    python3 -m distributed.scheduler --store <dir> \\
        --program demo/distributed/reading/reading.viba \\
        --service gauge=demo.distributed.reading.gauge \\
        --service factor=demo.distributed.reading.factor \\
        --service label=demo.distributed.reading.label \\
        --service length=demo.distributed.reading.length \\
        --service check=demo.distributed.reading.check

One service, one operation, one type along the chain (int, float, str, int, bool). The two
demos beside it are [`demo/distributed/naive/`](../naive/) (two services) and
[`demo/distributed/delivery/`](../delivery/) (three); the same `distributed.scheduler` runs
all three.
"""

from pathlib import Path

PROGRAM = str(Path(__file__).resolve().parent / "reading.viba")

# What the scheduler is given: one `NAME=MODULE` per service of this demo.
SERVICES = ("gauge=demo.distributed.reading.gauge",
            "factor=demo.distributed.reading.factor",
            "label=demo.distributed.reading.label",
            "length=demo.distributed.reading.length",
            "check=demo.distributed.reading.check")

__all__ = ["PROGRAM", "SERVICES"]
