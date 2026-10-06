"""Distributed demos: one `distributed` package, three programs to run on it.

`naive/` — two services, the same two api each, five int calls alternating them; the
worked example of [`viba-distributed.md`](../../viba-distributed.md).

`delivery/` — three services, a chain of ints that ends in a str, the data paths nested
below one sub-environment.

`reading/` — five services, one operation each, five steps that change type five times
(int, float, str, int, bool), and a call written that nothing needs.

Their service names, api names, module names and types have nothing in common, and the same
`distributed.scheduler` runs all three.
"""
