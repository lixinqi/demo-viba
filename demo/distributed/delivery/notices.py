"""The notices service of the delivery demo: two api, and the process that serves them.

Both api answer a str: `announce` writes the days as the notice, `emphasize` puts the
notice in upper case. Both are pure, and both go through `Service.recorded` all the same —
that is what puts the result where the other services replay it from.

The scheduler starts this process; by hand it is:

    python3 -m demo.distributed.delivery.notices --store <dir> --phase run \
        --program demo/distributed/delivery/estimate.viba
"""

import sys

from distributed.service import Service, run_service

# What one day is called on the notice.
THE_UNIT = "days"


def the_api(service: Service):
    """The notices api: `announce` writes the days, `emphasize` puts them in upper case."""

    def announce(environ, x):
        def compute():
            return f"{int(x.value)} {THE_UNIT}"

        return service.recorded(environ, compute)

    def emphasize(environ, x):
        def compute():
            return str(x.value).upper()

        return service.recorded(environ, compute)

    return {"announce": announce, "emphasize": emphasize}


def main(argv=None) -> int:
    return run_service("notices", the_api, argv)


if __name__ == "__main__":
    sys.exit(main())
