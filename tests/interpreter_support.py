"""各套件共用的计数器，和读一次运行结果的那几个小函数。

不是套件本身（没有 `__main__` 的跑法），`tests/` 下那几套从这里取：

    from interpreter_support import Checks, is_ok, value_of, stop_tag

`Checks` 管每个套件自己的通过/失败计数与那一行汇总；失败会打出来。用例文件是
`tests/data/` 下的 `.viba` 文件，不写在这里。

`interpret` 与 `exec` 回答的是一份 viba 数据（声明里的 `InterpretResult`，
`viba/interpret_result.viba`），所以这里读它也按数据读：`is_ok`、`value_of`、
`stop_tag`、`stop_text`、`stop_node`。名字与 viba 自己那套（`viba/tests/interpreter_support.py`）
一样，看过那边的人在这边照读。
"""

from viba.reflect import access as reflect_access, by_tag
from viba.type import ERR_TAG, OK_TAG, Ok


def is_ok(result) -> bool:
    """Did the run answer a value, rather than stop?"""
    return result.data.tag == OK_TAG


def answer_of(result):
    """The answer a run gave, as viba data: the `$ok` branch's payload."""
    return result.by_tag(OK_TAG)


def leaf_of(node):
    """The leaf one piece of viba data carries, or the error the accessor gave."""
    leaf = reflect_access.leaf(node)
    if not isinstance(leaf, Ok):
        return leaf
    return leaf.ok_value


def value_of(result):
    """The leaf a run answered; the result itself when it stopped.

    A suite writes `is_ok(result) and value_of(result) == 7`, and the left side is false
    when the run stopped, so this must not assume a value: a stop has no leaf to read.
    """
    if not is_ok(result):
        return result
    return leaf_of(answer_of(result))


def stop_of(result):
    """What the run stopped with, as viba data (`$err`'s payload); None for a value."""
    return None if is_ok(result) else result.by_tag(ERR_TAG)


def stop_tag(result) -> str:
    """Which kind of stop it was: `$not_implemented_err`, `$viba_program_err`, ..."""
    stop = stop_of(result)
    return "" if stop is None else stop.data.tag


def stop_members(result):
    """The members of the stop: its payload's object — `$msg`, `$call`, `$api_name`."""
    stop = stop_of(result)
    return None if stop is None else stop.by_tag(stop.data.tag)


def _member(result, tag):
    members = stop_members(result)
    if members is None:
        return None
    given = reflect_access.get(members, by_tag(tag))
    if not isinstance(given, Ok) or given.ok_value is None:
        return None
    return given.ok_value


def stop_text(result, tag: str) -> str:
    """The str one member of the stop carries; '' when it carries none."""
    given = _member(result, tag)
    if given is None:
        return ""
    leaf = reflect_access.leaf(given)
    if isinstance(leaf, Ok) and isinstance(leaf.ok_value, str):
        return leaf.ok_value
    return ""


def stop_node(result, tag: str):
    """One member of the stop, as viba data; None when it carries none."""
    return _member(result, tag)


class Checks:
    """One suite's counter: `check` and the summary line."""

    def __init__(self, name: str):
        self.name = name
        self.passed = 0
        self.failures = 0

    def check(self, ok: bool, label: str):
        if ok:
            self.passed += 1
        else:
            self.failures += 1
            print(f"FAIL: {label}")

    def report(self) -> int:
        print(f"{self.name}: {self.passed} passed, {self.failures} failed")
        return 1 if self.failures else 0
