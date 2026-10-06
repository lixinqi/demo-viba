"""The gauge service of the reading demo: one api, and the process that serves it.

`take` is the demo's one impure api: which reading the gauge shows is drawn in this
process, at this moment, somewhere at or above the minimum it was given. It goes through
`Service.recorded` like every other api here — that is what writes the result under the
call's storage path, where the other services replay it from.

The scheduler starts this process; by hand it is:

    python3 -m demo.distributed.reading.gauge --store <dir> --phase run \
        --program demo/distributed/reading/reading.viba
"""

import random
import sys

from distributed.service import Service, run_service

# How far above the minimum a reading can land, in the gauge's own unit.
THE_SPREAD = 20


def the_api(service: Service):
    """The gauge api: `take` draws a reading."""

    def take(environ, x):
        least = int(x.value)

        def draw():
            return random.randrange(least, least + THE_SPREAD)

        return service.recorded(environ, draw)

    return {"take": take}


def main(argv=None) -> int:
    return run_service("gauge", the_api, argv)


if __name__ == "__main__":
    sys.exit(main())
