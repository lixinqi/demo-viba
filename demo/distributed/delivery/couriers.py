"""The couriers service of the delivery demo: one api, and the process that serves it.

`days_for` is pure — a parcel of this weight always takes this many days — and it still
goes through `Service.recorded`: the result has to be written under the call's storage
path, or the other services could never pass that step.

The scheduler starts this process; by hand it is:

    python3 -m demo.distributed.delivery.couriers --store <dir> --phase run \
        --program demo/distributed/delivery/estimate.viba
"""

import sys

from distributed.service import Service, run_service

# One more day for every five kg, and one day to pick the parcel up.
KG_PER_DAY = 5


def the_api(service: Service):
    """The couriers api: `days_for` says how long a parcel of this weight takes."""

    def days_for(environ, x):
        def compute():
            return 1 + int(x.value) // KG_PER_DAY

        return service.recorded(environ, compute)

    return {"days_for": days_for}


def main(argv=None) -> int:
    return run_service("couriers", the_api, argv)


if __name__ == "__main__":
    sys.exit(main())
