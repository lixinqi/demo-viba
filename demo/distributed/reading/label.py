"""The label service of the reading demo: one api, and the process that serves it.

`write` is pure, and it is the step where the chain changes from numbers to text: it is
given a float and answers a str. `Service.recorded` still records it, so the services
after it replay the text out of the store instead of stopping at it.

The scheduler starts this process; by hand it is:

    python3 -m demo.distributed.reading.label --store <dir> --phase run \
        --program demo/distributed/reading/reading.viba
"""

import sys

from distributed.service import Service, run_service

# What one unit is called on the label.
THE_UNIT = "units"


def the_api(service: Service):
    """The label api: `write` writes the number as the text on the label."""

    def write(environ, x):
        def compute():
            return f"{float(x.value)} {THE_UNIT}"

        return service.recorded(environ, compute)

    return {"write": write}


def main(argv=None) -> int:
    return run_service("label", the_api, argv)


if __name__ == "__main__":
    sys.exit(main())
