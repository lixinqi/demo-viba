"""A role that answers a name itself, without any norm-repo code: `length`.

The same shape as `upper.py`, and the other half of what those two roles are there to show:
which name a process answers is its own module's line, so this process answers `length` and
stops at `upper` — and no norm repo is read for either.

    python3 -m ticket_system.handler --tickets <dir> --handler length \\
        --api demo.ticket_examples.length:the_api
"""


def the_api(context):
    """This role's whole table: `length` says how many characters it was given."""

    def length(environ, x):
        return len(str(x.value))

    return {"length": length}
