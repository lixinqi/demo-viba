"""The role modules the ticket examples are run with.

A **role** is one capability table: a process's answer to "which names do I serve, and
how". One module is one process, and the two_handlers example is two of them —
[`service_a.py`](service_a.py) and [`service_b.py`](service_b.py) — with a program they
share, so the ticket's `$handler_name2api_repo_commit_id` pins two files and two commits.
[`add_one.py`](add_one.py) runs the viba code of the norm repo the ticket names too — and keeps
the answer under the call's storage — while [`upper.py`](upper.py) and [`length.py`](length.py)
answer in python, with no norm-repo code behind them and nothing written under the ticket's
storage.

Which names a role serves is written in its own module, one line per name; the viba code
it serves lives in a norm repo ([`viba_ticket/`](../../viba_ticket/)) and is pinned by the
ticket (`$norm_repo_commit_id`). Neither layer lists the other: the role names the
definitions, and the ticket names the role's commit.
"""
