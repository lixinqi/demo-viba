"""The factor service of the reading demo: one api, and the process that serves it.

`times` is pure: the gauge's unit is a fixed multiple of the label's. It answers a float
where it was given an int, and `Service.recorded` records it the same way as any other
step — the store is what carries the result to the runs of the other services.

The scheduler starts this process; by hand it is:

    python3 -m demo.distributed.reading.factor --store <dir> --phase run \
        --program demo/distributed/reading/reading.viba
"""

import sys

from distributed.service import Service, run_service

# What one unit of the gauge is, in the unit the label writes.
THE_FACTOR = 2.5


def the_api(service: Service):
    """The factor api: `times` writes the reading in the label's unit."""

    def times(environ, x):
        return service.recorded(environ, lambda: int(x.value) * THE_FACTOR)

    return {"times": times}


def main(argv=None) -> int:
    return run_service("factor", the_api, argv)


if __name__ == "__main__":
    sys.exit(main())
