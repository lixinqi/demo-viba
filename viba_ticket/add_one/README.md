# The add_one example: where the answer of a call is kept.

One norm module, `add_one.viba` — a leaf that adds one — one directory of the demo-viba
repository (the tickets name its commit as `$norm_repo_commit_id`), and one role
([`demo/ticket_examples/add_one.py`](../../demo/ticket_examples/add_one.py)) that serves `add_one`
**through `replayed`**: the first attempt computes the answer and writes it under the ticket's
`$storage_path`, and every later attempt of the same ticket reads that snapshot back instead of
running the module again.

The storage is the call's own, so there is no state to maintain anywhere else: the ticket names
where its call's storage is, and viba already knows what to do with it. The suite runs the role
with `--again`, so one process attempts the ticket twice and the second attempt replays.

    python3 -m ticket_system.handler --tickets <tickets path> --handler add_one \
        --api demo.ticket_examples.add_one:the_api --again

This ticket's `$handler_name2api_repo_commit_id` names no commit for `add_one`, and a ticket that
names none for a role leaves that role free; the interpreter and the norm repo it names are still
read and have to be the ones this run is under.

The suite that runs this example is
[`tests/test_ticket_system.py`](../../tests/test_ticket_system.py).
