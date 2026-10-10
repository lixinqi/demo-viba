"""The builtin members `viba/builtin.viba` declares, as a host answers them.

viba ships no library: every implementation a run can reach comes from the host's compute
side (`viba.interpret`), and the arithmetic in `viba/builtin.viba` is no exception — the
host is asked for `builtin.mul`, `builtin.add`, and the rest. A handler of this system is
a host like any other, so it has to be able to answer them, or the norm repo's code has
nothing to add two numbers with.

What is here is every member of that file that is a **function of values**: the
arithmetic, comparison, conversion and string operations over `int`, `float`, `str` and
`bool`, and the two branch selectors `if` picks a branch with (`echo_or_never` and
`never_or_echo`). `echo` is not here: it hands its argument over as it is, which is no
computation this table could do for it. The names and the meanings are that file's, not
this one's.

What `get_func` is asked for is `builtin.add` — the module the member is declared in and
its name there — and the member's own name answers the same call, so both are keyed here.
A handler's own implementation of a name still wins over this table
(`ticket_system/handler.py`).

An argument the member cannot take — a range outside the string, an empty separator, an
empty thing to replace, a count below zero — is refused by **raising** here: a host says
a stop no other way, and a run reads it as `$underlying_viba_op_err` with `raised:` first
(`viba-interpreter.md`「一次执行会得到什么」).
"""

from viba import viba_ast
from viba.interpret import sub_env, viba_data
from viba.reflect import VObject


def _int(one) -> int:
    return int(one.value)


def _float(one) -> float:
    return float(one.value)


def _str(one) -> str:
    return str(one.value)


def _bool(one):
    return one.value if hasattr(one, "value") else one


def _refused(why: str):
    """This member cannot take what it was given: the implementation stops here."""
    raise ValueError(why)


def _parts(one) -> list:
    """A `list[str]` argument as the strings it holds (`join` takes one)."""
    return [str(part.value) if isinstance(part, VObject) else str(part) for part in one]


def _a_list_of(items) -> VObject:
    """Several strings as one `list[str]` — the one container form a host can answer."""
    return viba_data(viba_ast.TypeApp(
        "ListLiteral", [viba_ast.Constant(one) for one in items]))


def _never() -> VObject:
    """The value of a branch that is not taken: `never` (`never * value = never`)."""
    return viba_data(viba_ast.Never())


def _echo_or_never(environ, condition, get_v):
    """`if`'s true side: run that branch (in a child of its own) when the condition holds."""
    if condition.value:
        return get_v(sub_env(environ, "echo_or_never"))
    return _never()


def _never_or_echo(environ, condition, get_v):
    """`if`'s false side: run that branch (in a child of its own) when it does not."""
    if condition.value:
        return _never()
    return get_v(sub_env(environ, "never_or_echo"))


# {name: function(environ, x): value} and {name: function(environ, x, y): value}.
_ONE = {
    "neg": lambda _e, x: -_int(x),
    "abs": lambda _e, x: abs(_int(x)),
    "neg_f": lambda _e, x: -_float(x),
    "abs_f": lambda _e, x: abs(_float(x)),
    "not": lambda _e, x: not _bool(x),
    "len_str": lambda _e, x: len(_str(x)),
    "upper_str": lambda _e, x: _str(x).upper(),
    "lower_str": lambda _e, x: _str(x).lower(),
    "trim": lambda _e, x: _str(x).strip(),
    "int_to_float": lambda _e, x: float(_int(x)),
    "float_to_int": lambda _e, x: int(_float(x)),
    "int_to_str": lambda _e, x: str(_int(x)),
    "float_to_str": lambda _e, x: str(_float(x)),
    "bool_to_str": lambda _e, x: "true" if _bool(x) else "false",
    "str_to_int": lambda _e, x: int(_str(x)),
    "str_to_float": lambda _e, x: float(_str(x)),
}

_TWO = {
    "add": lambda _e, x, y: _int(x) + _int(y),
    "sub": lambda _e, x, y: _int(x) - _int(y),
    "mul": lambda _e, x, y: _int(x) * _int(y),
    "div": lambda _e, x, y: _int(x) // _int(y),
    "rem": lambda _e, x, y: _int(x) % _int(y),
    "min": lambda _e, x, y: min(_int(x), _int(y)),
    "max": lambda _e, x, y: max(_int(x), _int(y)),
    "pow": lambda _e, x, y: _int(x) ** _int(y),
    "lt": lambda _e, x, y: _int(x) < _int(y),
    "le": lambda _e, x, y: _int(x) <= _int(y),
    "gt": lambda _e, x, y: _int(x) > _int(y),
    "ge": lambda _e, x, y: _int(x) >= _int(y),
    "eq": lambda _e, x, y: _int(x) == _int(y),
    "ne": lambda _e, x, y: _int(x) != _int(y),
    "add_f": lambda _e, x, y: _float(x) + _float(y),
    "sub_f": lambda _e, x, y: _float(x) - _float(y),
    "mul_f": lambda _e, x, y: _float(x) * _float(y),
    "div_f": lambda _e, x, y: _float(x) / _float(y),
    "rem_f": lambda _e, x, y: _float(x) % _float(y),
    "min_f": lambda _e, x, y: min(_float(x), _float(y)),
    "max_f": lambda _e, x, y: max(_float(x), _float(y)),
    "pow_f": lambda _e, x, y: _float(x) ** _float(y),
    "lt_f": lambda _e, x, y: _float(x) < _float(y),
    "le_f": lambda _e, x, y: _float(x) <= _float(y),
    "gt_f": lambda _e, x, y: _float(x) > _float(y),
    "ge_f": lambda _e, x, y: _float(x) >= _float(y),
    "eq_f": lambda _e, x, y: _float(x) == _float(y),
    "ne_f": lambda _e, x, y: _float(x) != _float(y),
    "concat": lambda _e, x, y: _str(x) + _str(y),
    "eq_str": lambda _e, x, y: _str(x) == _str(y),
    "ne_str": lambda _e, x, y: _str(x) != _str(y),
    "lt_str": lambda _e, x, y: _str(x) < _str(y),
    "le_str": lambda _e, x, y: _str(x) <= _str(y),
    "gt_str": lambda _e, x, y: _str(x) > _str(y),
    "ge_str": lambda _e, x, y: _str(x) >= _str(y),
    "char_at": lambda _e, x, at: (_str(x)[_int(at)] if 0 <= _int(at) < len(_str(x))
                                  else _refused("there is no character there")),
    "find": lambda _e, x, needle: (_str(x).find(_str(needle))
                                   if _str(x).find(_str(needle)) >= 0 else None),
    "contains": lambda _e, x, needle: _str(needle) in _str(x),
    "starts_with": lambda _e, x, prefix: _str(x).startswith(_str(prefix)),
    "ends_with": lambda _e, x, suffix: _str(x).endswith(_str(suffix)),
    "split": lambda _e, x, separator: (
        _a_list_of(_str(x).split(_str(separator))) if _str(separator)
        else _refused("split takes a separator, and this one is empty")),
    "join": lambda _e, parts, separator: _str(separator).join(_parts(parts)),
    "repeat": lambda _e, x, times: (_str(x) * _int(times) if _int(times) >= 0
                                    else _refused("repeat takes a count that is not "
                                                  "negative")),
    "and": lambda _e, x, y: _bool(x) and _bool(y),
    "or": lambda _e, x, y: _bool(x) or _bool(y),
    "xor": lambda _e, x, y: _bool(x) != _bool(y),
    "eq_bool": lambda _e, x, y: _bool(x) == _bool(y),
    "ne_bool": lambda _e, x, y: _bool(x) != _bool(y),
}

# {name: function(environ, x, y, z): value} — the members that take three arguments.
_THREE = {
    "substr": lambda _e, x, start, end: (
        _str(x)[_int(start):_int(end)]
        if 0 <= _int(start) <= _int(end) <= len(_str(x))
        else _refused("the range is not inside the string")),
    "replace": lambda _e, x, old, new: (
        _str(x).replace(_str(old), _str(new)) if _str(old)
        else _refused("replace takes something to replace, and this is empty")),
}

# The two selectors `if` picks a branch with: their last argument is a call owed an
# environment, not a value (`viba/if.viba`), so they are kept apart from the tables above.
_SWITCH = {
    "echo_or_never": _echo_or_never,
    "never_or_echo": _never_or_echo,
}


def the_table() -> dict:
    """Every member, keyed under both spellings of its name.

    `builtin.mul` is the name `get_func` is asked for, and `mul` is the member's own
    name — `viba/builtin.viba` says they are the same call, so one table answers both.
    """
    table = {}
    for one in (_ONE, _TWO, _THREE, _SWITCH):
        for name, implementation in one.items():
            table[name] = implementation
            table[f"builtin.{name}"] = implementation
    return table
