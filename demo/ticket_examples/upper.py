"""A role that answers a name itself, without any norm-repo code: `upper`.

Not every capability is viba code. A role may put a plain python function in its table —
this one uppercases a string — and that is the same kind of entry as one that runs a
norm-repo definition (`demo/ticket_examples/service_a.py` shows that kind). Nothing here reads
the ticket's norm repo, and nothing is written under the ticket's storage: the answer is one
string, and it is not kept.

    python3 -m ticket_system.handler --tickets <dir> --handler upper \\
        --api demo.ticket_examples.upper:the_api
"""


def the_api(context):
    """This role's whole table: `upper` uppercases the string it is given."""

    def upper(environ, x):
        return str(x.value).upper()

    return {"upper": upper}
