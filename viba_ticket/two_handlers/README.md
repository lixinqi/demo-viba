# The two_handlers example: one program, two services taking turns at it.

This directory **is** the norm code the tickets name (`$norm_repo_path`): the viba code a
ticket's `$call` executes. It is not a repository of its own — it is one directory of
demo-viba, so the tickets name **this** repository's commit as `$norm_repo_commit_id`
(`ticket_system/repo.py` reads the code at that commit, from this directory up). Three modules:

| Module | What it is |
|---|---|
| `the_program.viba` | The program the ticket's `$call` names: four calls, A's step and B's step alternating, each step's argument the answer of the step before it |
| `service_a.viba` | Service A's api — the signature and hint of `a_add`, the step A's process implements |
| `service_b.viba` | Service B's api — the same for `b_scale` |

The program imports the two api files and calls them:

```viba
c0 = service_a.a_add << $env ($sub_env << args.env << "c0") << $x args.x
c1 = service_b.b_scale << $env ($sub_env << args.env << "c1") << $x c0
c2 = service_a.a_add << $env ($sub_env << args.env << "c2") << $x c1
c3 = service_b.b_scale << $env ($sub_env << args.env << "c3") << $x c2
```

Every call runs at a sub-environment of its own — `c0`, `c1`, … under the program's path.
That path is the call's storage path: whoever does that step records its answer there, and
every later round replays it instead of doing the step again. The steps are a chain, so they
have to run in this order: the two processes can only take turns, and neither of them can
finish the program alone.

Which process implements which step is written in the two role modules, one file per service:
[`demo/ticket_examples/service_a.py`](../../demo/ticket_examples/service_a.py) serves `a_add`,
[`service_b.py`](../../demo/ticket_examples/service_b.py) serves `b_scale`, and both of them
serve `the_program` — running it is what a round is. Each file is pinned by its own entry in
`$handler_name2api_repo_commit_id`, which is how a ticket can say "the process answering as
`a` has to be at this commit of this file". A role that is asked for a step it does not serve
writes the stop into the ticket's progress instead: that is its record of having taken the
ticket, and the other role takes that ticket next.

    python3 -m ticket_system.scheduler --tickets <tickets path> \
        --handler a=demo.ticket_examples.service_a:the_api \
        --handler b=demo.ticket_examples.service_b:the_api

A ticket of this example therefore ends up with four stages — `a`, `b`, `a`, `b` — the last one
answering `$ok`; and with four recorded answers under the ticket's `$storage_path`, one per step
of the chain. Both are what [`viba-ticket.md`](../../viba-ticket.md) §2 and §5 read.

The tickets say three versions: the interpreter (`$viba_interpreter_repo_commit_id`), this norm
repo (`$norm_repo_commit_id`), and each role's own module
(`$handler_name2api_repo_commit_id`). All three are read off the file system before a call runs
([`viba-ticket.md`](../../viba-ticket.md) §3); when this directory is not at that commit, or has
edits on top of it, the commit's tree is read out under the tickets path instead, so a person's
checkout is not written to at all.

The tickets themselves are written by whoever has the work; the suite that runs this example is
[`tests/test_ticket_system.py`](../../tests/test_ticket_system.py), and the chapter over the
whole system is [`viba-ticket.md`](../../viba-ticket.md).
