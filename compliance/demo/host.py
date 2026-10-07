"""The demo's host side: what the witness' and the rule's functions actually do.

`DistanceHost` is the `get_func` of a run of `rule_distance.viba` — the case of
the victim at (0,0) and the suspect at (3,4) at 12:30. It records what it was
asked, which is how a test tells a replayed run from a measured one:

- `witnessed` gets one entry per witness asked for — the facts of the case come
  through the host, not written into the witness file;
- `measured` gets one entry per *measurement actually taken* — a run that
  replayed its call leaves it empty;
- `judged` gets one entry per verdict asked for, which every run does.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from viba import viba_ast
from compliance import measure
from viba.interpret import viba_data
from viba.reflect import access as reflect_access

RULE = Path(__file__).resolve().parent / "rule_distance.viba"
WITNESS = Path(__file__).resolve().parent / "case_at_1230.viba"

# Where they actually were, and when: what the implementation reads. Here a
# table so the demo is short; a case reads a log, a database or a service — and
# then that reading is not pure, so it is snapshotted under the case's own
# storage path (`replayed`), the way the measurement is recorded as a call.
FACTS = {"victim": (0, 0), "suspect": (3, 4)}
MOMENT = "12:30"


class DistanceHost:
    """The demo's implementations, and a record of what they were asked."""

    def __init__(self):
        self.witnessed = []
        self.measured = []
        self.judged = []

    def get_func(self, module_path, func_name):
        if func_name == "at_1230":
            return self.at_1230
        if func_name == "measure_distance":
            return self.measure_distance
        if func_name == "distance_ge":
            return self.distance_ge
        return None

    def at_1230(self, env):
        """The three facts of that moment, as viba data.

        The witness says which facts there are (its type is that product); the
        answer here is where they come from. Nothing about the case is written
        into the witness file, so a case whose facts come from elsewhere is the
        same file with another implementation.
        """
        self.witnessed.append(MOMENT)
        return viba_data(viba_ast.ProductChain([
            viba_ast.Tagged("$victim", _point_viba_data(*FACTS["victim"])),
            viba_ast.Tagged("$suspect", _point_viba_data(*FACTS["suspect"])),
            viba_ast.Tagged("$at", viba_ast.Constant(MOMENT)),
        ]))

    def measure_distance(self, env, evidence, case):
        """How far apart the two were: the impure step, through `measure`.

        `env` is the environment the call runs under — the rule hands a
        temporary one, since a call has no storage path of its own. `evidence` is the
        case's environment, and that is where the call is kept, so the
        evidence says which case it belongs to: `root/case_at_1230/call/
        measure_distance.viba`.
        """
        def compute(given):
            victim = _point(given, "victim")
            suspect = _point(given, "suspect")
            self.measured.append((victim, suspect))
            return int(round(((victim[0] - suspect[0]) ** 2
                              + (victim[1] - suspect[1]) ** 2) ** 0.5))
        return measure(env, "measure_distance", case, compute, evidence=evidence)

    def distance_ge(self, env, d, threshold):
        """The predicate: pure, so it runs on every judgment."""
        self.judged.append(d.value)
        return d.value >= threshold.value


def _point_viba_data(x, y):
    """A point as viba data: `$x x * $y y`, the way `Point` is written."""
    return viba_ast.ProductChain([viba_ast.Tagged("$x", viba_ast.Constant(x)),
                                  viba_ast.Tagged("$y", viba_ast.Constant(y))])


def _point(node, tag):
    """(x, y) of a point member, read through the reflection protocol."""
    point = node.by_tag(tag)
    return (reflect_access.leaf(point.by_tag("x")).ok_value,
            reflect_access.leaf(point.by_tag("y")).ok_value)
