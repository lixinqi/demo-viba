"""Tickets: one call to run, written on the file system, and the log of the attempts.

A **ticket** is one call some process is to run, written down as viba code under the
tickets path. It carries

- `$ticket_uid`: the name of the directory it lives in, which is also the name its
  progress belongs to;
- `$call`: the call itself, in viba's runnable form (a function of type `Any <- Env`,
  its environment left out) — `ticket_system.handler.answer` is what runs it;
- `$viba_interpreter_repo_commit_id` and `$viba_interpreter_repo_path`: the viba
  **interpreter** — the package that reads and runs programs. A run is made by one
  interpreter, and the ticket says which;
- `$norm_repo_commit_id` and `$norm_repo_path`: the **norm repo** — the viba code the call is
  written in, and the version of it the ticket names (`ticket_system/repo.py` says how the
  two are read and how the code is run);
- `$VIBA_PATH`: the directories a run of the call looks its modules up in, as a real
  `list[str]` — the member is `list[str]`, and what is written for it is the list value
  `ListLiteral["/a", "/b"]` (`the_paths` reads it back by position). viba's
  `Environment.viba_path` wants one string, so `handler.answer` joins the list with
  `os.pathsep` where it hands the environment over;
- `$handler_name2api_repo_commit_id`: one commit per handler — **the commit that handler's
  capability table is at**, when this ticket was written. A handler that finds itself in
  here runs the call only at that commit, and writes a record of the stop when it is at
  another one: the answer to a call is the host's code, so which host is being asked is
  as much part of the ticket as which viba is;
- `$storage_path`: the root of the viba environment the call runs in — every snapshot
  the call writes lands under it;
- `$time`: when the ticket was written, `datetime.isoformat()`, `$time` being the
  `datetime` of the table at the top of `ticket_system/README.md`.

The layout on disk, under one tickets path:

    <tickets path>/<uid>/ticket.viba            the ticket, one definition `value`
    <tickets path>/<uid>/progress/<stage>.viba  one attempt at the ticket

A ticket is a file, and a file is read fresh on every poll: a ticket is settled when a
process writes it, and no process has to be told about it.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from viba import serialize, viba_ast
from viba.interpret import (Environment, EnvironmentStorage, read_snapshot,
                            viba_data)
from viba.reflect import access as reflect_access
from viba.type import Err, UnderlyingOpErr, VibaProgramErr

# The file names: one ticket per directory, every attempt under `progress/`.
TICKET_NAME = "ticket"
TICKET_FILE = TICKET_NAME + ".viba"
PROGRESS_SEGMENT = "progress"

# The tags of the ticket, in the order they are written.
TICKET_TAGS = ("$ticket_uid", "$viba_interpreter_repo_commit_id",
               "$viba_interpreter_repo_path", "$VIBA_PATH", "$norm_repo_commit_id",
               "$norm_repo_path", "$call", "$storage_path",
               "$handler_name2api_repo_commit_id", "$time")

# The name of the member that says which commit each handler's api is at.
HANDLER_COMMIT_IDS_TAG = "$handler_name2api_repo_commit_id"


def a_time(when: Optional[datetime] = None) -> str:
    """A moment as the text a ticket keeps of it."""
    return (when or datetime.now(timezone.utc)).isoformat()


def the_product(fields) -> viba_ast.ProductChain:
    """(tag, value) pairs as one product: the piece a ticket is written as.

    A member that is already viba data keeps it; a `str` becomes the literal it is.
    Every string goes through `viba.builder`, the writer every snapshot goes
    through, so what is written is what reads back.
    """
    return viba_ast.ProductChain(
        [viba_ast.Tagged(tag, _piece(value)) for tag, value in fields])


def a_result(result, value):
    """An `InterpretResult` as the piece of viba code a stage keeps of it.

    A sum is written as **the branch that is there**: `$ok <value>` when the call
    answered, `$err <an InterpretError>` when it stopped. Both branches at once would be
    no resident of the sum at all.

        InterpretResult =
            Oneof
          | $ok VibaNode
          | $err InterpretError

        InterpretError =
            Oneof
          | $viba_program_err ProgramErr
          | $underlying_viba_op_err UnderlyingOpErr
          | $not_implemented_err UnderlyingOpErr
          | $environment_api_invalid_argument_err EnvironmentApiInvalidArgumentErr

    The error is written with the fields the type names (`an_error` below), so a stage
    says which kind of stop it was, which step it was about, and what the call was — not
    just a sentence.
    """
    if isinstance(result, viba_ast.AST):
        return result
    if isinstance(result, Err):
        return viba_ast.Tagged("$err", an_error(result.error))
    return viba_ast.Tagged("$ok", _piece(value))


def an_error(error) -> viba_ast.AST:
    """An `InterpretError` as the tagged product the type says it is.

    One branch per kind, each with the fields of its own product:

    - `$not_implemented_err` / `$underlying_viba_op_err` (`UnderlyingOpErr`): `$msg`,
      `$module_path`, `$full_qualified_func_name`, `$call` — which way it stopped, at which
      step (the module the step is declared in, as a path, and its whole name there), and
      the call itself in the runnable form the error carries;
    - `$viba_program_err` (`ProgramErr`): `$msg` and `$stack` — the calls the run was in,
      as the `list[Frame]` the type names (`_stack_piece`);
    - `$environment_api_invalid_argument_err`: `$msg`, `$api_name`, `$args`.
    """
    from viba.type import (EnvironmentApiInvalidArgumentErr, Err as _Err,
                           FAILURE_TAG, NOT_IMPLEMENTED_TAG, VibaProgramErr)

    if isinstance(error, _Err):              # a result that was not unwrapped
        error = error.error
    if isinstance(error, UnderlyingOpErr):
        tag = ("$not_implemented_err" if error.tag == NOT_IMPLEMENTED_TAG
               else "$underlying_viba_op_err" if error.tag == FAILURE_TAG
               else str(error.tag or FAILURE_TAG))
        return viba_ast.Tagged(tag, _a_product([
            ("$msg", viba_ast.Constant(str(error.msg))),
            ("$module_path", viba_ast.Constant(str(error.module_path))),
            ("$full_qualified_func_name",
             viba_ast.Constant(str(error.full_qualified_func_name))),
            ("$call", _piece(error.call) if error.call is not None else viba_ast.Nil()),
        ]))
    if isinstance(error, EnvironmentApiInvalidArgumentErr):
        return viba_ast.Tagged("$environment_api_invalid_argument_err", _a_product([
            ("$msg", viba_ast.Constant(str(error.msg))),
            ("$api_name", viba_ast.Constant(str(error.api_name))),
            ("$args", _piece(error.arguments) if error.arguments is not None
             else viba_ast.Nil()),
        ]))
    if isinstance(error, VibaProgramErr):
        return viba_ast.Tagged("$viba_program_err", _a_product([
            ("$msg", viba_ast.Constant(str(error.msg))),
            ("$stack", _stack_piece(error.stack)),
        ]))
    return viba_ast.Tagged("$viba_program_err", _a_product([
        ("$msg", viba_ast.Constant(f"{type(error).__name__}: {error}")),
        ("$stack", _stack_piece([])),
    ]))


def _a_product(fields) -> viba_ast.ProductChain:
    """(tag, piece) pairs as one product."""
    return viba_ast.ProductChain([viba_ast.Tagged(tag, piece) for tag, piece in fields])


def _stack_piece(stack) -> viba_ast.TypeApp:
    """`Stack` (`list[Frame]`) as the list value viba writes a list as.

    A frame is a product of the two members the type names, and the list is
    `ListLiteral[…]` with one element per frame — the container literal written where a
    value goes (`viba-interpreter.md`「容器字面量」). The stack of a run that never
    entered a call is empty, and `ListLiteral[]` is how viba writes an empty list.
    """
    return viba_ast.TypeApp("ListLiteral", [
        _a_product([("$file_path", viba_ast.Constant(str(frame.file_path))),
                    ("$lineno", viba_ast.Constant(int(frame.lineno)))])
        for frame in stack])


def why_it_stopped(error) -> str:
    """One sentence for a stop: the tag that says which way, then the message.

    Still used for the one-line reading of a stop (`progress.reason_of` builds the same
    sentence out of the stored error)."""

    tag = getattr(error, "tag", None) or "$viba_program_err"
    msg = getattr(error, "msg", None) or str(error)
    return f"{tag}: {msg}"


def _piece(value) -> viba_ast.AST:
    """A host value as the piece of viba data it is written as."""
    if isinstance(value, viba_ast.AST):
        return value
    if hasattr(value, "data"):               # already viba data
        return value.data
    if isinstance(value, list):
        return viba_ast.TypeApp("ListLiteral", [_piece(one) for one in value])
    if isinstance(value, dict):
        return _dict_piece(value)
    return viba_ast.Constant(value)


def _dict_piece(entries) -> viba_ast.AST:
    """A dict as the piece viba writes a dict as: `DictLiteral[(k, v), ...]`.

    The pairs are written in the order the caller gave them, not sorted: a ticket
    that says the same thing twice has to be the same file twice.
    """
    return viba_ast.TypeApp("DictLiteral", [
        viba_ast.Tuple([_piece(key), _piece(value)])
        for key, value in entries.items()])


def a_dict(node) -> dict:
    """A `DictLiteral` member as the python dict it stands for.

    The keys are the written ones (`VibaNode.keys`), and each value is read by its key
    (`VibaNode.at_key`) — the same two steps `$__getitem__` takes for a dict
    (`viba-interpreter.md`「按地址读元素」), which is what a written `DictLiteral` is
    addressed by.
    """
    kind = reflect_access.container_kind(reflect_access.unfold(node.descriptor))
    if kind != "dict":
        raise RuntimeError(f"this member is a dict, and this is no dict: {node!r}")
    return {key: _leaf(node.at_key(key)) for key in node.keys()}


def a_list(node) -> list:
    """A `ListLiteral` member as the python list it stands for, element by element."""
    kind = reflect_access.container_kind(reflect_access.unfold(node.descriptor))
    if kind != "list":
        raise RuntimeError(f"this member is a list, and this is no list: {node!r}")
    return [_leaf(node.at_index(index)) for index in range(len(node))]


def _ticket_environ(tickets_path, uid: str = "") -> Environment:
    """The viba environment the ticket's own snapshot is at.

    Nothing runs in it: it is the pair (tickets path, `<uid>/ticket`) the snapshot
    helpers take, which is what makes a ticket the same kind of thing as every
    other stored viba data.
    """
    root = str(Path(tickets_path))
    return Environment(EnvironmentStorage(uid, None, root), None)


@dataclass
class Ticket:
    """One call to run, and the environment it is to run in."""

    ticket_uid: str
    call: object                      # the viba data of a runnable call
    viba_interpreter_repo_commit_id: str
    viba_interpreter_repo_path: str
    viba_path: List[str]
    norm_repo_commit_id: str
    norm_repo_path: str
    handler_name2api_repo_commit_id: dict    # {handler name: the commit its api is at}
    storage_path: str
    time: str

    @property
    def uid(self) -> str:
        return self.ticket_uid

    def api_commit_id_of(self, handler_name: str):
        """The commit this ticket was written against for that handler, or None.

        None is not "this one is welcome": it is "this ticket names no commit for
        that handler", which is what a handler reads before it decides whether it
        is the one being asked.
        """
        return self.handler_name2api_repo_commit_id.get(handler_name)

    def as_fields(self):
        """The members, in the order `TICKET_TAGS` names them."""
        return (("$ticket_uid", self.ticket_uid),
                ("$viba_interpreter_repo_commit_id", self.viba_interpreter_repo_commit_id),
                ("$viba_interpreter_repo_path", self.viba_interpreter_repo_path),
                ("$VIBA_PATH", self.viba_path),
                ("$norm_repo_commit_id", self.norm_repo_commit_id),
                ("$norm_repo_path", self.norm_repo_path),
                ("$call", self.call),
                ("$storage_path", self.storage_path),
                (HANDLER_COMMIT_IDS_TAG, self.handler_name2api_repo_commit_id),
                ("$time", self.time))

    def write(self, tickets_path) -> Path:
        """Write this ticket under the tickets path; answer where it landed."""
        return write_ticket(self, tickets_path)


# ----------------------------------------------------------------------
# The tickets path
# ----------------------------------------------------------------------


def ticket_dir(tickets_path, uid: str) -> Path:
    """The directory of one ticket."""
    return Path(tickets_path) / uid


def ticket_path(tickets_path, uid: str) -> Path:
    """The file of one ticket."""
    return ticket_dir(tickets_path, uid) / TICKET_FILE


def progress_dir(tickets_path, uid: str) -> Path:
    """The directory every attempt at one ticket is written under."""
    return ticket_dir(tickets_path, uid) / PROGRESS_SEGMENT


def stage_path(tickets_path, uid: str, name: str) -> Path:
    """One attempt's file."""
    return progress_dir(tickets_path, uid) / (name + ".viba")


def ticket_uids(tickets_path) -> List[str]:
    """Every ticket under this tickets path, in name order.

    A directory under the tickets path is one ticket; anything else there is not.
    A directory whose ticket file is not written yet is no ticket: a writer makes
    the directory first, so a reader skips it until the file is there.
    """
    root = Path(tickets_path)
    if not root.is_dir():
        return []
    return sorted(one.name for one in root.iterdir()
                  if one.is_dir() and (one / TICKET_FILE).is_file())


def ticket_source(ticket: "Ticket") -> str:
    """A ticket as the viba code it is written as: one definition, `value`.

    The text is the product chain viba writes a product as — the unit `Object`, then
    `* $member <piece>` for every member in order — so what a person reads on disk
    is the chain the readers here walk.
    """
    body = the_product(ticket.as_fields())
    lines = [r"value =", "  Object"]
    for name, piece in _chain(body):
        lines += _member(name, piece)
    return "\n".join(lines) + "\n"


def _member(name: str, piece: viba_ast.AST) -> list:
    """One member as the lines it is written on: `* $name <piece>`.

    A call is written as a group — `$call (__dyn_call__ << "f" << 5)` — because `*`
    binds looser than `<<`: without the parentheses the next member would be read as
    another argument of this call. A piece written on more than one line continues
    under its own member, indented by the two spaces the member itself is.
    """
    written = _written(name, piece)
    if " << " in written:
        written = f"({written})"
    lines = written.splitlines()
    return [f"  * {name} {lines[0]}"] + [f"    {line}" for line in lines[1:]]


def _written(name: str, piece: viba_ast.AST) -> str:
    """One member's piece as viba code.

    `viba.serialize` is the writer every piece goes through — it is what writes a call
    back as the call it is, and what writes a list or a dict member as the container
    literal it is (`ListLiteral["/a", "/b"]`, `DictLiteral[("a", "1")]`,
    `viba-interpreter.md`「容器字面量」).
    """
    written = serialize.serialize("value", viba_data(piece))
    if isinstance(written, VibaProgramErr):
        raise RuntimeError(f"cannot write {name} as viba code: {written.msg}")
    return _the_body(written.ok_value)


def _the_body(source: str) -> str:
    """The piece a written `value = …` definition holds, without the label."""
    lines = source.splitlines()
    head = lines[0].split("=", 1)[1].strip()
    tail = [line.strip() for line in lines[1:]]
    return "\n".join(([head] if head else []) + tail)


def _chain(body: viba_ast.AST):
    """[(member name, piece)] for a product chain, in written order."""
    pieces = getattr(body, "elements", None) or [body]
    out = []
    for piece in pieces:
        if isinstance(piece, viba_ast.Tagged):
            out.append((piece.tag, piece.type))
        else:
            out.append(("$value", piece))
    return out


def write_ticket(ticket: "Ticket", tickets_path) -> Path:
    """Write one ticket under the tickets path, and answer the file it landed in.

    The text is written whole and renamed onto the path, the way every snapshot is
    (`EnvironmentStorage.write_text`), so a reader never sees half a ticket.
    """
    path = ticket_path(tickets_path, ticket.uid)
    _ticket_environ(tickets_path, ticket.uid).storage.write_text(
        f"{ticket.uid}/{TICKET_FILE}", ticket_source(ticket))
    return path


def read_ticket(tickets_path, uid: str) -> Optional["Ticket"]:
    """The ticket written under this tickets path, or None when there is none.

    The file is read as viba data — what `write_ticket` wrote, and what a person
    may write by hand. A ticket that cannot be read raises: a ticket nobody can
    read is not a ticket anybody can work on.
    """
    stored = read_snapshot(_ticket_environ(tickets_path, uid), TICKET_NAME)
    if stored is None:
        return None
    return ticket_of_node(stored)


def ticket_of_node(node) -> "Ticket":
    """Ticket viba data as a `Ticket`. Raises when the data is not one."""
    fields = {}
    for tag in TICKET_TAGS:
        got = node.by_tag(tag)
        if tag == "$call":
            fields["call"] = got
        elif tag == "$VIBA_PATH":
            fields["viba_path"] = the_paths(got)
        elif tag == HANDLER_COMMIT_IDS_TAG:
            fields["handler_name2api_repo_commit_id"] = a_dict(got)
        elif tag == "$time":
            fields["time"] = _leaf(got)
        else:
            fields[tag[1:]] = _leaf(got)
    return Ticket(ticket_uid=fields["ticket_uid"], call=fields["call"],
                  viba_interpreter_repo_commit_id=fields["viba_interpreter_repo_commit_id"],
                  viba_interpreter_repo_path=fields["viba_interpreter_repo_path"],
                  viba_path=fields["viba_path"],
                  norm_repo_commit_id=fields["norm_repo_commit_id"],
                  norm_repo_path=fields["norm_repo_path"],
                  handler_name2api_repo_commit_id=fields["handler_name2api_repo_commit_id"],
                  storage_path=fields["storage_path"], time=fields["time"])


def the_paths(member) -> List[str]:
    """The `$VIBA_PATH` member as the list of directories it stands for.

    The member is a `list[str]` (`viba_ticket/ticket_design.viba`), so this reads the list
    element by element (`a_list`) and refuses anything that is not a string: a member
    that has to be guessed at is worse than one that stops the reader. A directory
    named twice is kept twice here — it is what the ticket says; removing repeats is
    `handler.answer`'s business, which is the one that joins them for the run.
    """
    paths = a_list(member)
    for one in paths:
        if not isinstance(one, str):
            raise RuntimeError(f"$VIBA_PATH is a list[str], and this one is {one!r}")
    return paths


def _leaf(node):
    """The plain value a leaf member holds."""
    leaf = reflect_access.leaf(node)
    if isinstance(leaf, VibaProgramErr):
        raise RuntimeError(f"this member is not a value: {leaf.msg}")
    return leaf.ok_value


def ticket_text(tickets_path, uid: str) -> Optional[str]:
    """The ticket's own text, as it is on disk, or None when there is none."""
    path = ticket_path(tickets_path, uid)
    try:
        return path.read_text()
    except FileNotFoundError:
        return None
