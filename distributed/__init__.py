"""The `distributed` package: one viba program, several services, one store.

`distributed.service` is one service process's side of that: its api, the store it
shares, and the calls it answers. `distributed.scheduler` is the round scheduler
over the services the caller names.

Neither module holds a program or an api of its own: the program comes from the
caller, and so does each service. A distributed program and its services are one
package's business — [`demo/distributed/`](demo/distributed/) holds three such packages:
[`naive/`](demo/distributed/naive/) with two services (the worked example of
[`viba-distributed.md`](viba-distributed.md)), [`delivery/`](demo/distributed/delivery/)
with three, and [`reading/`](demo/distributed/reading/) with five, one operation each.

    python3 -m distributed.scheduler --store <directory> --program <file> \\
        --service <name>=<module> --service <name>=<module>
"""

from distributed.service import Service, environ_at, run_service

__all__ = ["Service", "environ_at", "run_service"]
