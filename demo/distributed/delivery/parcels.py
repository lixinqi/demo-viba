"""The parcels service of the delivery demo: two api, and the process that serves them.

`read_scale` is the demo's one impure api: which weight the scale shows is drawn in this
process, at this moment, out of the weights the scale has. `add_handling` is pure — it
adds the packing weight, the same every time. Both go through `Service.recorded` all the
same: that is what writes the result under the call's storage path, where a run of one of
the other services replays the step instead of stopping at it.

The scheduler starts this process; by hand it is:

    python3 -m demo.distributed.delivery.parcels --store <dir> --phase run \
        --program demo/distributed/delivery/estimate.viba
"""

import random
import sys

from distributed.service import Service, run_service

# What the scale can show, in kg.
THE_SCALE = (1, 2, 5, 12, 20)

# What the packing adds, in kg.
THE_PACKING = 1


def the_api(service: Service):
    """The parcels api: `read_scale` draws a weight, `add_handling` adds the packing."""

    def read_scale(environ, x):
        least = int(x.value)

        def draw():
            return random.choice([weight for weight in THE_SCALE if weight >= least])

        return service.recorded(environ, draw)

    def add_handling(environ, x):
        return service.recorded(environ, lambda: int(x.value) + THE_PACKING)

    return {"read_scale": read_scale, "add_handling": add_handling}


def main(argv=None) -> int:
    return run_service("parcels", the_api, argv)


if __name__ == "__main__":
    sys.exit(main())
