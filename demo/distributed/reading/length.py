"""The length service of the reading demo: one api, and the process that serves it.

`count` is pure: how many characters the label's text has. It takes the chain back from
str to int, and `Service.recorded` records that int under the call's storage path.

The scheduler starts this process; by hand it is:

    python3 -m demo.distributed.reading.length --store <dir> --phase run \
        --program demo/distributed/reading/reading.viba
"""

import sys

from distributed.service import Service, run_service


def the_api(service: Service):
    """The length api: `count` counts the characters of the text."""

    def count(environ, x):
        return service.recorded(environ, lambda: len(str(x.value)))

    return {"count": count}


def main(argv=None) -> int:
    return run_service("length", the_api, argv)


if __name__ == "__main__":
    sys.exit(main())
