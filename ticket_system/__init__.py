"""ticket_system: a call written as a ticket, and the processes that answer it.

A **ticket** is one call some process is to run, written as viba code under a tickets
path, together with the viba checkout it is to run against and the storage root its
snapshots go under (`ticket_system.tickets`). A **stage** is one process's attempt at
one ticket, and the log of the attempts is `TicketProgress` — one file each, under the
ticket's own directory, so the log is append-only without a lock
(`ticket_system.progress`).

A **handler** is a non-agent process: a name, a **role** (the module that answers its
capability table), and a loop that polls the tickets path once a second, runs the calls it
can, and logs what came back (`ticket_system.handler`). Which names a role serves is that
module's own business; the viba code those names are is the ticket's norm repo, read at the
commit the ticket names (`ticket_system.repo`). The **scheduler** starts every handler over
one tickets path and stops them when every ticket's progress holds a `$ok`
(`ticket_system.scheduler`).

The worked examples of viba code are under [`../viba_ticket/`](../viba_ticket/), one norm
repo each, with the roles that serve them in
[`../demo/ticket_examples/`](../demo/ticket_examples/); the story is in
[`../viba-ticket.md`](../viba-ticket.md).
"""

from ticket_system.handler import Context, Handler, answer
from ticket_system.progress import (TicketStage, answered, latest, latest_ok,
                                     read_stages, write_stage)
from ticket_system.scheduler import OneHandler, run
from ticket_system.tickets import (Ticket, read_ticket, ticket_uids, write_ticket)

__all__ = ["Context", "Handler", "OneHandler", "Ticket", "TicketStage", "answer",
           "answered", "latest", "latest_ok", "read_stages", "read_ticket", "run", "ticket_uids",
           "write_stage", "write_ticket"]
