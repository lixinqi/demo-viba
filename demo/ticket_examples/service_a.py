"""Service A of the two_handlers example: one process, one file, one capability table.

This module **is** service A. It is the only place `a_add` is implemented, and
`$handler_name2api_repo_commit_id` pins the commit this file has to be at for a process to
answer as `a`. Service B is another file and another process
([`demo/ticket_examples/service_b.py`](service_b.py)): nothing here says what B does, and
nothing there says what A does.

    python3 -m ticket_system.handler --tickets <dir> --handler a \\
        --api demo.ticket_examples.service_a:the_api

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
    """A's capability table: the program, and A's own step of it."""
    return {THE_PROGRAM: the_program(context.norm), "a_add": _a_add}


def the_program(norm):
    """The program of that norm repo, as the implementation of its name.

    Running the program is what a round is: the steps another process recorded come back
    from the ticket's storage (`ticket_system/handler.py` 的 `get_func`), and the ones
    this process implements are computed and recorded.
    """

    def run(environ, *given):
        return repo.run_definition(norm, THE_PROGRAM, "run", environ, list(given))

    return run


def _a_add(environ, x):
    """A's step: draw this process's amount, add it, and record the answer.

    `replayed` is what makes the program reproducible: the answer is written under the
    storage path of that very call, so every later round — this process's or B's — answers
    the value of the first run instead of drawing again.
    """
    return replayed(environ, lambda: int(x.value) + random.randrange(1, 10))
