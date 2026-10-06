"""Service A of the naive distributed demo: two api, and the process that serves them.

Both api are leaves with one int in and one int out, and both are impure: the
amount they add (or multiply by) is drawn in this process, at this moment. What
makes the program reproducible is `Service.recorded` — the result is written into
the store, so every later run, in this process or in the other, replays it instead
of drawing again.

The scheduler starts this process; by hand it is:

    python3 -m demo.distributed.naive.service_a --store <dir> --phase run \
        --program demo/distributed/naive/interleaved.viba
"""

import random
import sys

from distributed.service import Service, run_service


def the_api(service: Service):
    """A's api: `a_step` adds the drawn amount, `a_scale` multiplies by it."""

    def a_step(environ, x):
        return service.recorded(environ, lambda: int(x.value) + random.randrange(1, 10))

    def a_scale(environ, x):
        return service.recorded(environ, lambda: int(x.value) * random.randrange(2, 5))

    return {"a_step": a_step, "a_scale": a_scale}


def main(argv=None) -> int:
    return run_service("a", the_api, argv)


if __name__ == "__main__":
    sys.exit(main())
