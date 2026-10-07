"""TicketProgress: the append-only log of the attempts at one ticket.

Every process that picks a ticket up writes one **stage** for that attempt, and never
writes one again: the log is the directory, and a stage is a file in it. That is what
makes the log append-only without a lock — two processes appending at once write two
files, each under its own name, and neither can lose the other's.

    TicketStage =
        Object
        * $ticket_uid str
        * $handler_name str            # an agent's name, or a process's
        * $interpret_result InterpretResult
        * $time datetime

`$interpret_result` is what the attempt answered:

- a stage whose result is `$ok <value>` is a **finished** attempt — the call ran, and
  that value is what it answered;
- any other stage is a **record of a stop**: `$not_implemented_err` when this process
  does not implement that call (another process's business, and the file is how the
  scheduler sees that this one tried), `$underlying_viba_op_err` when the
  implementation broke, `$viba_program_err` when the call or the environment cannot run
  at all.

The state of a ticket is its **log**, and the log only grows: a ticket is finished when
one of its stages is a `$ok`. `answered` is the rule the stop condition of the whole
system is made of, and it is a latch — a stage that answered is in the log for good, so
no later stage can take that answer back (`viba-ticket.md` 第 5 节).
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from viba import viba_ast
from viba.interpret import Environment, EnvironmentStorage, read_snapshot, write_snapshot
from viba.reflect import access as reflect_access
from viba.type import Frame, VibaProgramErr

from ticket_system.tickets import (PROGRESS_SEGMENT, a_time, progress_dir,
                                   stage_path, the_product, ticket_uids)

# The tags of a stage, in the order they are written.
STAGE_TAGS = ("$ticket_uid", "$handler_name", "$interpret_result", "$time")


# The name an attempt writes under: `<time>-<handler>`, so the two walks of one
# process never land on one path and two processes never can either.
def stage_name(handler_name: str, when: Optional[datetime] = None) -> str:
    """The file name of one attempt: `<writing time>-<handler>`, in UTC.

    A compact stamp (`20240102T030405.123456Z`) so that sorting the file names is
    sorting the writing times — the log is read in the order it was appended. The
    stamp holds no colon: a file name has to be one path part on every system.
    """
    stamp = (when or datetime.now(timezone.utc)).astimezone(timezone.utc).strftime(
        "%Y%m%dT%H%M%S.%fZ")
    return f"{stamp}-{handler_name}"


def _stage_environ(tickets_path, uid: str) -> Environment:
    """The environment a stage is read and written through: `<uid>/progress`."""
    root = str(Path(tickets_path))
    return Environment(EnvironmentStorage(f"{uid}/{PROGRESS_SEGMENT}", None, root), None)


@dataclass
class TicketStage:
    """One process's attempt at one ticket."""

    ticket_uid: str
    handler_name: str
    interpret_result: object          # the viba data of an `InterpretResult`
    time: str

    @property
    def ok(self) -> bool:
        """Did this attempt answer a value? (`$ok` on the result, carrying one.)"""
        return result_of(self.interpret_result)[1]

    def is_ok(self, wanted=None) -> bool:
        """Did this attempt answer? With `wanted`, is that what it answered?"""
        value, answered = result_of(self.interpret_result)
        if not answered:
            return False
        return True if wanted is None else value == wanted

    def as_fields(self):
        """The members, in the order `STAGE_TAGS` names them."""
        return (("$ticket_uid", self.ticket_uid),
                ("$handler_name", self.handler_name),
                ("$interpret_result", self.interpret_result),
                ("$time", self.time))


def result_of(interpret_result):
    """(the value, True) when this result answered, (None, False) when it did not.

    `InterpretResult` is `$ok Any | $err InterpretError`, and a stage keeps the branch
    the run answered, as it answered it (`tickets.a_result`). The other branch is simply
    not there, so
    `by_tag` on it raises: a branch this data does not hold, a `nil`, and a branch that
    holds something other than a value are all "no answer". Reading a result is never an
    error, because not answering is one of the two things a result may say.
    """
    node = _member(interpret_result, "$ok")
    if node is None:
        return None, False
    value = _leaf_or_none(node)
    return (value, True) if value is not None else (None, False)


def error_of(interpret_result):
    """The `$err` branch — one sentence — or None when this result answered `$ok`.

    The stored error is the tagged product `InterpretError` is (what the run answered,
    kept as it came back by `tickets.a_result`), so
    what comes back is `"<the tag that says which way>: <its $msg>"`
    (`reason_of`). The fields themselves are one call away (`error_tag`,
    `field_of`, `call_of`, `stack_of`).
    """
    return reason_of(interpret_result)


def error_tag(interpret_result):
    """Which way the run stopped (`$not_implemented_err`, `$viba_program_err`, …), or None."""
    node = _member(interpret_result, "$err")
    if node is None:
        return None
    for tag in ("$viba_program_err", "$underlying_viba_op_err", "$not_implemented_err",
                "$environment_api_invalid_argument_err"):
        if _member(node, tag) is not None:
            return tag
    return None


def error_of_kind(interpret_result, tag: str):
    """The branch of that kind as viba data, or None when the error is another kind."""
    node = _member(interpret_result, "$err")
    if node is None:
        return None
    return _member(node, tag)


def field_of(interpret_result, field: str):
    """One field of the stored error (`$msg`, `$module_path`, `$full_qualified_func_name`, …)."""
    node = _member(interpret_result, "$err")
    if node is None:
        return None
    for tag in ("$viba_program_err", "$underlying_viba_op_err", "$not_implemented_err",
                "$environment_api_invalid_argument_err"):
        branch = _member(node, tag)
        if branch is None:
            continue
        return _leaf_or_none(_member(branch, field))
    return None


def stack_of(interpret_result) -> List["Frame"]:
    """The `$stack` of a `$viba_program_err`: the calls the run was in, outermost first.

    A stack is a `list[Frame]` (the declared `ProgramErr`), so it is read by position, element
    by element — each element a product of `$file_path` and `$lineno`, the two members
    `Frame` has. A stop of another kind keeps no stack, and a stack nobody wrote is
    empty: both read as `[]`, because "this stop was in no call" is what an empty stack
    says. A `$stack` that is no list of frames reads as `[]` too: reading a stop is never
    an error, the way `_member` and `_leaf_or_none` read the rest of it.
    """
    branch = error_of_kind(interpret_result, "$viba_program_err")
    if branch is None:
        return []
    node = _member(branch, "$stack")
    if node is None:
        return []
    try:
        return [Frame(_leaf_or_none(_member(node.at_index(index), "$file_path")),
                      _leaf_or_none(_member(node.at_index(index), "$lineno")))
                for index in range(len(node))]
    except Exception:                      # a `$stack` that is no list of frames
        return []


def call_of(interpret_result):
    """The call the stop was about, in the runnable form the error carried, or None."""
    node = _member(interpret_result, "$err")
    if node is None:
        return None
    for tag in ("$underlying_viba_op_err", "$not_implemented_err"):
        branch = _member(node, tag)
        if branch is not None:
            return _member(branch, "$call")
    return None


def reason_of(interpret_result) -> str:
    """A stop as one sentence: the tag that says which way, then its `$msg`."""
    tag = error_tag(interpret_result)
    if tag is None:
        return None
    message = field_of(interpret_result, "$msg")
    return f"{tag}: {message}" if message is not None else tag


def _member(interpret_result, tag: str):
    """One branch of a result: the node, or None when the data has no such branch."""
    if interpret_result is None:
        return None
    try:
        node = interpret_result.by_tag(tag)
    except Exception:                  # a branch this viba data does not hold
        return None
    return node


def _leaf_or_none(node):
    """The leaf a branch holds, or None when it holds nothing (`nil`) or no value."""
    try:
        return node.leaf
    except Exception:                  # `nil`, or a piece that is no value
        return None


# ----------------------------------------------------------------------
# The log on disk
# ----------------------------------------------------------------------


def write_stage(tickets_path, stage: "TicketStage") -> Path:
    """Append one stage to the ticket's log, under a name nobody else writes.

    The name carries the writing time and the handler's name; a second attempt by
    the same handler gets a different name, and so does every other handler's.
    """
    name = stage_name(stage.handler_name)
    write_snapshot(_stage_environ(tickets_path, stage.ticket_uid),
                   the_product(stage.as_fields()), name)
    return stage_path(tickets_path, stage.ticket_uid, name)


def read_stages(tickets_path, uid: str) -> List["TicketStage"]:
    """Every attempt at this ticket, oldest first.

    The order is the file name order, which starts with the writing time: the
    names are stamps, so the log reads in the order it was appended. A file that
    cannot be read is skipped — one half-written or hand-broken stage is no reason
    to lose the log around it.
    """
    directory = progress_dir(tickets_path, uid)
    if not directory.is_dir():
        return []
    stages = []
    for path in sorted(directory.glob("*.viba")):
        try:
            stored = read_snapshot(_stage_environ(tickets_path, uid), path.stem)
        except Exception:
            continue
        if stored is None:
            continue
        try:
            stages.append(stage_of_node(stored))
        except Exception:
            continue
    return stages


def stage_of_node(node) -> "TicketStage":
    """Stage viba data as a `TicketStage`."""
    fields = {}
    for tag in STAGE_TAGS:
        got = node.by_tag(tag)
        if tag == "$interpret_result":
            fields["interpret_result"] = got
        else:
            leaf = reflect_access.leaf(got)
            if isinstance(leaf, VibaProgramErr):
                raise RuntimeError(f"{tag} is not a value: {leaf.msg}")
            fields[tag[1:]] = leaf.ok_value
    return TicketStage(ticket_uid=fields["ticket_uid"],
                       handler_name=fields["handler_name"],
                       interpret_result=fields["interpret_result"],
                       time=fields["time"])


def a_stage(ticket_uid: str, handler_name: str, interpret_result,
            when: Optional[datetime] = None) -> "TicketStage":
    """One stage, ready to be written."""
    return TicketStage(ticket_uid=ticket_uid, handler_name=handler_name,
                       interpret_result=interpret_result, time=a_time(when))


# ----------------------------------------------------------------------
# What the log says about one ticket
# ----------------------------------------------------------------------


def latest(tickets_path, uid: str) -> Optional["TicketStage"]:
    """The newest attempt at this ticket, or None when nobody tried yet."""
    stages = read_stages(tickets_path, uid)
    return stages[-1] if stages else None


def answered(tickets_path, uid: str) -> bool:
    """Does this ticket's log hold a `$ok`? That is a finished ticket.

    The whole system stops on this (`finished`), and it is a latch on purpose: the log is
    append-only, so "the ticket has been answered" is a fact that only ever becomes true.
    A process that read the log a moment before a `$ok` landed writes its stop after it —
    that stage says what **that** process found, and it cannot take the answer back.
    Reading the newest stage instead would let whoever wrote last decide whether the
    ticket is finished, and a ticket both answered and stopped would never settle:
    neither process attempts a ticket twice (`viba-ticket.md` 第 5 节).
    """
    return any(stage.is_ok() for stage in read_stages(tickets_path, uid))


def latest_ok(tickets_path, uid: str) -> bool:
    """Is the newest attempt at this ticket a `$ok`? The report's reading, not the rule.

    The stop condition is `answered`; this says which attempt was the last one written,
    which is what `the_state` reports.
    """
    stage = latest(tickets_path, uid)
    return stage is not None and stage.is_ok()


def finished(tickets_path) -> bool:
    """Is every ticket under this tickets path finished — every log holding a `$ok`?"""
    return all(answered(tickets_path, uid) for uid in ticket_uids(tickets_path))


def the_state(tickets_path) -> list:
    """One line per ticket: what the log says about it right now.

    A report of `unfinished` says which tickets are not finished; this says what each
    ticket's log looked like when that was decided — how many attempts it holds, whether
    one of them answered (`answered`, the rule), which attempt was the latest, who made
    it, and what that one said. A reader of the report then has the evidence of the run
    it is reading about, not just this machine's state afterwards.
    """
    out = []
    for uid in ticket_uids(tickets_path):
        stages = read_stages(tickets_path, uid)
        last = stages[-1] if stages else None
        out.append({"ticket": uid, "stages": len(stages),
                    "ok": answered(tickets_path, uid),
                    "answers": sum(1 for one in stages if one.is_ok()),
                    "handlers": [one.handler_name for one in stages],
                    "latest_handler": last.handler_name if last else None,
                    "latest_time": last.time if last else None,
                    "latest_answer": result_of(last.interpret_result)[1] if last else None,
                    "latest_stop": (error_of(last.interpret_result) if last else None),
                    "latest_stop_kind": (error_tag(last.interpret_result)
                                         if last else None),
                    "latest_at": (field_of(last.interpret_result, "$full_qualified_func_name")
                                  if last else None),
                    "latest_stack": (["%s:%s" % (frame.file_path, frame.lineno)
                                      for frame in stack_of(last.interpret_result)]
                                     if last else None)})
    return out
