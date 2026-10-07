"""Service B of the two_handlers example: one process, one file, one capability table.

This module **is** service B. It is the only place `b_scale` is implemented, and
`$handler_name2api_repo_commit_id` pins the commit this file has to be at for a process to
answer as `b`. Service A is another file and another process
([`demo/ticket_examples/service_a.py`](service_a.py)): the two are pinned apart, so a run
made by a process whose file is at another commit writes the stop instead of an answer.

    python3 -m ticket_system.handler --tickets <dir> --handler b \\
        --api demo.ticket_examples.service_b:the_api

The program both of them run, and how two processes get one ticket finished, are in
[`viba-ticket.md`](../../viba-ticket.md) §2.
"""

import random

from viba.interpret import replayed

from ticket_system import repo

# The name the ticket's `$call` carries: the program of the norm repo. Both services answer
# it — each runs the same program, replaying the steps already recorded and doing its own —
# so this process has it in its table too.
THE_PROGRAM = "the_program"


def the_api(context):
    """B's capability table: the program, and B's own step of it."""
    return {THE_PROGRAM: the_program(context.norm), "b_scale": _b_scale}


def the_program(norm):
    """The program of that norm repo, as the implementation of its name.

    Running the program is what a round is: the steps another process recorded come back
    from the ticket's storage (`ticket_system/handler.py` 的 `get_func`), and the ones
    this process implements are computed and recorded.
    """

    def run(environ, *given):
        return repo.run_definition(norm, THE_PROGRAM, "run", environ, list(given))

    return run


def _b_scale(environ, x):
    """B's step: draw this process's factor, multiply by it, and record the answer.

    `replayed` is what makes the program reproducible: the answer is written under the
    storage path of that very call, so every later round — this process's or A's — answers
    the value of the first run instead of drawing again.
    """
    return replayed(environ, lambda: int(x.value) * random.randrange(2, 5))
