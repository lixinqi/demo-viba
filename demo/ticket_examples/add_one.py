"""A role that answers a name by running norm-repo code, and keeps the answer: `add_one`.

This is the other kind of table entry: the implementation runs `add_one.viba` of the norm repo
the ticket names (`ticket_system/repo.py`), and it goes through `replayed`, so the answer is
written under the **call's own storage path** and every later attempt of the same ticket reads
it back instead of running that module again. The role decides this: the same definition served
without `replayed` would just be computed again.

    python3 -m ticket_system.handler --tickets <dir> --handler add_one \\
        --api demo.ticket_examples.add_one:the_api --again
"""

from viba.interpret import replayed

from ticket_system import repo


def the_api(context):
    """`add_one`, with the answer kept under the call's storage path."""
    norm = context.norm

    def add_one(environ, x):
        return replayed(environ,
                        lambda: repo.run_definition(norm, "add_one", "add_one", environ,
                                                    [x]))

    return {"add_one": add_one}
