"""Service B of the naive distributed demo: two api, and the process that serves them.

The same two api as service A (`b_step` adds, `b_scale` multiplies), drawn in this
process. Neither service has the other's implementations: what one of them cannot
serve, the run answers with the deferral, and the store carries the result over.

The scheduler starts this process; by hand it is:

    python3 -m demo.distributed.naive.service_b --store <dir> --phase run \
        --program demo/distributed/naive/interleaved.viba
"""

import random
import sys

from distributed.service import Service, run_service


def the_api(service: Service):
    """B's api: `b_step` adds the drawn amount, `b_scale` multiplies by it."""

    def b_step(environ, x):
        return service.recorded(environ, lambda: int(x.value) + random.randrange(1, 10))

    def b_scale(environ, x):
        return service.recorded(environ, lambda: int(x.value) * random.randrange(2, 5))

    return {"b_step": b_step, "b_scale": b_scale}


def main(argv=None) -> int:
    return run_service("b", the_api, argv)


if __name__ == "__main__":
    sys.exit(main())
