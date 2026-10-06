"""The check service of the reading demo: one api, and the process that serves it.

`over` is pure and it is the last step of the chain: the program's own answer is the bool
it answers. Like every other step here it goes through `Service.recorded`, so a later
schedule on the same store replays it.

The scheduler starts this process; by hand it is:

    python3 -m demo.distributed.reading.check --store <dir> --phase run \
        --program demo/distributed/reading/reading.viba
"""

import sys

from distributed.service import Service, run_service

# A count above this many characters is over the limit.
THE_LIMIT = 8


def the_api(service: Service):
    """The check api: `over` says whether the count is over the limit."""

    def over(environ, x):
        return service.recorded(environ, lambda: int(x.value) > THE_LIMIT)

    return {"over": over}


def main(argv=None) -> int:
    return run_service("check", the_api, argv)


if __name__ == "__main__":
    sys.exit(main())
