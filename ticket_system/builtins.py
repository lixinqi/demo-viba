"""The builtin operators, as a host answers them.

viba ships no library: every implementation a run can reach comes from the host's compute
side (`viba.interpret`), and the arithmetic in `viba/builtin.viba` is no exception — the
host is asked for `builtin.mul`, `builtin.add`, and the rest. A handler of this system is
a host like any other, so it has to be able to answer them, or the norm repo's code has
nothing to add two numbers with.

What is here is the arithmetic, comparison and conversion over `int`, `float`, `str` and
`bool`, one implementation per member of `viba/builtin.viba` — the names and the meanings
are that file's, not this one's. A member's own name is the same call as the qualified
one (`add << …` is `builtin.add << …`, so both are keyed here), and a handler's own
implementation of a name still wins over this table (`ticket_system/handler.py`).
"""


def _int(one) -> int:
    return int(one.value)


def _float(one) -> float:
    return float(one.value)


def _str(one) -> str:
    return str(one.value)


def _bool(one):
    return one.value if hasattr(one, "value") else one


# {name: function(environ, x): value} and {name: function(environ, x, y): value}.
_ONE = {
    "$neg": lambda _e, x: -_int(x),
    "$abs": lambda _e, x: abs(_int(x)),
    "$neg_f": lambda _e, x: -_float(x),
    "$abs_f": lambda _e, x: abs(_float(x)),
    "$not": lambda _e, x: not _bool(x),
    "$len_str": lambda _e, x: len(_str(x)),
    "$upper_str": lambda _e, x: _str(x).upper(),
    "$lower_str": lambda _e, x: _str(x).lower(),
    "$int_to_float": lambda _e, x: float(_int(x)),
    "$float_to_int": lambda _e, x: int(_float(x)),
    "$int_to_str": lambda _e, x: str(_int(x)),
    "$float_to_str": lambda _e, x: str(_float(x)),
    "$bool_to_str": lambda _e, x: "true" if _bool(x) else "false",
    "$str_to_int": lambda _e, x: int(_str(x)),
    "$str_to_float": lambda _e, x: float(_str(x)),
}

_TWO = {
    "$add": lambda _e, x, y: _int(x) + _int(y),
    "$sub": lambda _e, x, y: _int(x) - _int(y),
    "$mul": lambda _e, x, y: _int(x) * _int(y),
    "$div": lambda _e, x, y: _int(x) // _int(y),
    "$rem": lambda _e, x, y: _int(x) % _int(y),
    "$min": lambda _e, x, y: min(_int(x), _int(y)),
    "$max": lambda _e, x, y: max(_int(x), _int(y)),
    "$pow": lambda _e, x, y: _int(x) ** _int(y),
    "$lt": lambda _e, x, y: _int(x) < _int(y),
    "$le": lambda _e, x, y: _int(x) <= _int(y),
    "$gt": lambda _e, x, y: _int(x) > _int(y),
    "$ge": lambda _e, x, y: _int(x) >= _int(y),
    "$eq": lambda _e, x, y: _int(x) == _int(y),
    "$ne": lambda _e, x, y: _int(x) != _int(y),
    "$add_f": lambda _e, x, y: _float(x) + _float(y),
    "$sub_f": lambda _e, x, y: _float(x) - _float(y),
    "$mul_f": lambda _e, x, y: _float(x) * _float(y),
    "$div_f": lambda _e, x, y: _float(x) / _float(y),
    "$rem_f": lambda _e, x, y: _float(x) % _float(y),
    "$min_f": lambda _e, x, y: min(_float(x), _float(y)),
    "$max_f": lambda _e, x, y: max(_float(x), _float(y)),
    "$pow_f": lambda _e, x, y: _float(x) ** _float(y),
    "$lt_f": lambda _e, x, y: _float(x) < _float(y),
    "$le_f": lambda _e, x, y: _float(x) <= _float(y),
    "$gt_f": lambda _e, x, y: _float(x) > _float(y),
    "$ge_f": lambda _e, x, y: _float(x) >= _float(y),
    "$eq_f": lambda _e, x, y: _float(x) == _float(y),
    "$ne_f": lambda _e, x, y: _float(x) != _float(y),
    "$concat": lambda _e, x, y: _str(x) + _str(y),
    "$eq_str": lambda _e, x, y: _str(x) == _str(y),
    "$ne_str": lambda _e, x, y: _str(x) != _str(y),
    "$lt_str": lambda _e, x, y: _str(x) < _str(y),
    "$le_str": lambda _e, x, y: _str(x) <= _str(y),
    "$gt_str": lambda _e, x, y: _str(x) > _str(y),
    "$ge_str": lambda _e, x, y: _str(x) >= _str(y),
    "$and": lambda _e, x, y: _bool(x) and _bool(y),
    "$or": lambda _e, x, y: _bool(x) or _bool(y),
    "$xor": lambda _e, x, y: _bool(x) != _bool(y),
    "$eq_bool": lambda _e, x, y: _bool(x) == _bool(y),
    "$ne_bool": lambda _e, x, y: _bool(x) != _bool(y),
}


def the_table() -> dict:
    """Every operator, keyed under both spellings of its name.

    `builtin.mul` is the name `get_func` is asked for, and `mul` is the member's own
    name — `viba/builtin.viba` says they are the same call, so one table answers both.
    """
    table = {}
    for name, one in list(_ONE.items()) + list(_TWO.items()):
        table[name] = one
        table[f"builtin.{name[1:]}"] = one
    return table
