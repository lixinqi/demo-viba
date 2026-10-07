"""ticket_system 与 viba_ticket 的套件：票据读写、三个版本、角色能力表、norm 代码、调度。

    python3 tests/test_ticket_system.py

套件跑七件事：

1. 票据的读写：两个 repo（解释器、norm）、`$VIBA_PATH`、每个角色的版本，写下去读回来一样；
2. 三个版本都**读出来对一遍**：正在跑的解释器、norm repo 的那份 checkout、这个角色加载到的代码；
3. 一个角色一张能力表：一段跨两个服务的程序里，`service_a:the_api` 只做 a 那几步、
   `service_b:the_api` 只做 b 那几步（两个模块、两个文件、两个进程），做不到的那一步停下来交给
   另一个（轮着来才做得完）；
4. norm repo 的代码真被跑：名字 → `repo.run_definition` → 解释器跑一段 viba 程序，程序里每一步
   各在自己的存储路径下记一次，后来的人从那儿回放；
5. 也有角色自己答的名字：能力表里那一项就是一份 python 实现，norm repo 不参与；
6. 票据的存储是那次调用的答案落在的地方：同一张票据第二次被尝试时，答案从那份快照里回放；
7. 调度起两个真正的处理进程，在 norm repo 上跑完一批票据，并且「有跟进来的停下记录」不会把一张
   已经做完的票据重新变成没做完。

计数的 `Checks` 用 `tests/interpreter_support.py` 那一套 —— 仓库里的套件都这么报数。
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "viba"))
sys.path.insert(0, str(ROOT))
# The handler processes this suite starts must find the viba package too — and the viba
# package is the submodule's `viba/`, so that directory comes first: the repository root
# holds a directory of the same name, and a namespace package found there would shadow the
# real one.
os.environ["PYTHONPATH"] = os.pathsep.join(
    [str(ROOT / "viba"), str(ROOT)]
    + ([os.environ["PYTHONPATH"]] if os.environ.get("PYTHONPATH") else []))

from interpreter_support import Checks

from compliance import the_call
from ticket_system import code, handler, progress, repo, tickets
from viba.interpret import Environment, EnvironmentStorage, read_snapshot
from viba.type import Err, VibaProgramErr

checks = Checks("ticket_system")
check = checks.check

# 两个角色各自的模块与名字：能力表就写在角色自己的模块里 —— 一个服务一个文件，一个进程一份。
ROLE_A = "demo.ticket_examples.service_a:the_api"
ROLE_B = "demo.ticket_examples.service_b:the_api"

# 票据 `$call` 里的那个名字：norm repo 里那段程序。它的每一步都跑在自己的存储路径下，
# 两个角色轮流做 —— 这一步是谁的，看的是它记在哪儿。
THE_PROGRAM = "the_program"
CHAIN = ("norm/run/c0", "norm/run/c1", "norm/run/c2", "norm/run/c3")
UPPER = "demo.ticket_examples.upper:the_api"
LENGTH = "demo.ticket_examples.length:the_api"
ADD_ONE = "demo.ticket_examples.add_one:the_api"

# 两个示例各自的 norm repo：示例里的 `.viba` 文件就是 norm 代码。
NORM_CODE = {"two_handlers": ROOT / "viba_ticket" / "two_handlers",
             "add_one": ROOT / "viba_ticket" / "add_one"}

FIRST = "2024-01-02T03:04:05+00:00"
# 一次调度最多跑多久。两三个进程、每轮一个新的进程（每个都要 import viba、读三次提交），
# 机器忙的时候一轮要好几秒；这个数是「跑不完就报 unfinished」的上限，不是期望耗时。
MOST_SECONDS = 180


def the_viba() -> str:
    """工作区里那份 viba（解释器）现在在哪一个提交上。"""
    return code.git_commit(ROOT / "viba", "the viba submodule", "the suite")


def our_code() -> str:
    """这份仓库（角色模块的代码所在）现在在哪一个提交上。

    每次问的时候现读一次：跑测试这一会儿要是正好有一次提交，票据上写的和进程读到的就会差一版 ——
    那正是这一层要拦的事，不该变成测试的偶然失败。
    """
    return code.git_commit(ROOT, "the role's api", "the suite")


def the_norm_code(example: str = "two_handlers") -> Path:
    """这个示例的 norm 代码在哪儿：它就在本项目里，`$norm_repo_path` 指到它那个目录。

    它不需要是单独一份 repo：`$norm_repo_commit_id` 就是这个项目的提交（`the_norm_commit`），
    读它的那一层从那个路径往上找到 repo（`ticket_system/repo.py` 的 `NormRepo`）。
    """
    return NORM_CODE[example]


def the_norm_commit(example: str = "two_handlers") -> str:
    """norm repo 的提交：本项目自己的提交 —— norm 代码就是这个 repo 的一份。"""
    return code.git_commit(ROOT, "the norm repo", example)


def a_committed_norm_repo(tmp: Path) -> Path:
    """另造一份真的 git repo，并把代码提交进去：测「提交的树 vs 有人正在改的工作树」用。

    示例自己的 norm 代码就在本 repo 里，走的是「就地读」那条路；要测抽一份出来跑，得先有一个
    提交 —— 而本项目这会儿还全是未提交的改动（`tests/test_ticket_system.py` 的
    `the_committed_tree_is_what_runs`）。
    """
    place = tmp / "norm-repo"
    place.mkdir(parents=True, exist_ok=True)
    for source in sorted(the_norm_code().glob("*.viba")):
        shutil.copy(source, place / source.name)
    _git(place, "init", "-q")
    _git(place, "add", "-A")
    _git(place, "-c", "user.email=a@b", "-c", "user.name=t", "commit", "-qm",
         "the norm code")
    return place


def _git(place: Path, *arguments: str) -> None:
    done = subprocess.run(["git", "-C", str(place), *arguments],
                          capture_output=True, text=True, timeout=120)
    if done.returncode != 0:
        raise RuntimeError(f"git {arguments} in {place} failed: {done.stderr.strip()}")


def the_roles() -> dict:
    """`$handler_name2api_repo_commit_id`：每个角色各自的代码现在在哪一个提交上。"""
    return {"a": our_code(), "b": our_code(), "upper": our_code(),
            "length": our_code(), "add_one": our_code()}


def the_ticket(uid, name, given, storage, viba_paths=None, handler_commit_ids=None,
               viba_commit_id=None, norm_repo=None, norm_commit_id=None):
    """一张票据：解释器、norm repo、调用、存储、每个角色的版本，都齐。"""
    norm = norm_repo if norm_repo is not None else the_norm_code()
    if norm_commit_id is None:
        norm_commit_id = code.git_commit(norm, "the norm repo", uid)
    paths = list(viba_paths) if viba_paths is not None else [str(ROOT / "viba")]
    return tickets.Ticket(
        ticket_uid=uid, call=the_call(name, given),
        viba_interpreter_repo_commit_id=the_viba() if viba_commit_id is None else viba_commit_id,
        viba_interpreter_repo_path=str(ROOT / "viba"),
        viba_path=paths,
        norm_repo_commit_id=str(norm_commit_id), norm_repo_path=str(norm),
        handler_name2api_repo_commit_id=dict(the_roles() if handler_commit_ids is None
                                          else handler_commit_ids),
        storage_path=str(storage), time=FIRST)


def a_role(spec: str, name: str, tickets_path, interval=0.0, again=False):
    """一个处理进程：它的名字、角色模块、票据目录。"""
    return handler.Handler(name, handler.load_api(spec), tickets_path, interval=interval,
                           again=again, api_path=_the_role_file(spec))


def the_two_roles(path, uids=("t1",), rounds=8) -> list:
    """两个角色轮着跑这些票据，直到都做完（或者轮数用光）：一次调度就是这么转的。

    两个处理进程从头到尾是同一个对象：它记着自己试过哪几张（`Handler.done`），norm repo 也只读
    一次。轮数是上限，不是期望。
    """
    a, b = a_role(ROLE_A, "a", path), a_role(ROLE_B, "b", path)
    notes = []
    for _ in range(rounds):
        for one in (a, b):
            notes += one.tick()
        if all(progress.answered(path, uid) for uid in uids):
            break
    return notes


def the_store(ticket) -> dict:
    """这次调用每一步记下来的答案：`{存储路径: 值}`。

    程序在自己的子环境里跑，每个调用各有一个子环境（`c0`、`c1`、……），答那一步的服务把答案写在
    那个路径下（`replayed`）。所以「每一步只算了一次、后来的人从这儿回放」看的就是这份东西。
    """
    root = Path(ticket.storage_path)
    out = {}
    for one in sorted(root.rglob("value.viba")):
        where = one.parent.relative_to(root).as_posix()
        out[where] = read_snapshot(Environment(
            EnvironmentStorage(where, None, str(root)), None)).leaf
    return out


def _the_role_file(spec: str) -> Path:
    module = spec.split(":")[0].replace(".", "/")
    return ROOT / f"{module}.py"


def repo_of(ticket, place) -> "repo.NormRepo":
    """这张票据的 norm repo，就是处理进程会拿到的那个。"""
    return repo.NormRepo(ticket.norm_repo_path, ticket.norm_repo_commit_id, place)


# ----------------------------------------------------------------------
# 1) 票据：写下去、读回来
# ----------------------------------------------------------------------


def the_files(tmp: Path):
    """写在文件系统上的票据：两个 repo、每个角色的版本、调用，读回来还是同一张。"""
    path = tmp / "tickets"
    storage = tmp / "storage"
    norm = the_norm_code()
    norm_commit_id = code.git_commit(norm, "the norm repo", "t1")
    ticket = the_ticket("t1", THE_PROGRAM, 21, storage, norm_repo=norm,
                        norm_commit_id=norm_commit_id)
    written = ticket.write(path)
    check(written == tickets.ticket_path(path, "t1") and written.is_file(),
          f"the ticket lands under the tickets path: {written}")
    text = written.read_text()
    for member in ("$viba_interpreter_repo_commit_id", "$viba_interpreter_repo_path",
                   "$VIBA_PATH", "$norm_repo_commit_id", "$norm_repo_path", "$call",
                   "$storage_path", "$handler_name2api_repo_commit_id", "$time"):
        check(member in text, f"the ticket carries {member}: {text!r}")

    back = tickets.read_ticket(path, "t1")
    check(back is not None and back.ticket_uid == "t1" and back.time == FIRST,
          f"the ticket reads back: {back!r}")
    check(back.viba_interpreter_repo_commit_id == the_viba()
          and back.viba_interpreter_repo_path == str(ROOT / "viba"),
          f"the interpreter it names reads back: {back.viba_interpreter_repo_path!r}")
    check(back.viba_path == [str(ROOT / "viba")],
          f"$VIBA_PATH reads back as the list of directories it is: {back.viba_path!r}")
    check(f'* $VIBA_PATH ListLiteral["{ROOT / "viba"}"]' in text,
          f"and it is written as that list value, not as a joined string: {text!r}")
    check(back.norm_repo_commit_id == norm_commit_id and back.norm_repo_path == str(norm),
          f"the norm repo it names reads back: {back.norm_repo_path!r}")
    check(back.handler_name2api_repo_commit_id == the_roles(),
          f"每个角色的版本读回来是那张表: {back.handler_name2api_repo_commit_id!r}")
    check(back.api_commit_id_of("a") == our_code() and back.api_commit_id_of("nobody") is None,
          "and the ticket can say which commit it asks a role at")

    check(tickets.read_ticket(path, "nobody") is None,
          "a ticket nobody wrote is None, not an error")
    check(tickets.ticket_uids(path) == ["t1"], "the tickets path lists its tickets")


# ----------------------------------------------------------------------
# 2) 结果的写法：和只写选中的那一支
# ----------------------------------------------------------------------


def the_result_is_one_branch(tmp: Path):
    """`$interpret_result` 是 `$ok … | $err …` 的居民：只写一支，两支都写不是居民。"""
    path = tmp / "branch-tickets"
    norm = the_norm_code()
    for uid, name, given in [("t1", "a_add", 21), ("t2", "nobody.knows", 7)]:
        the_ticket(uid, name, given, tmp / "s" / uid, norm_repo=norm).write(path)
    a_role(ROLE_A, "a", path).run(ticks=1)

    answered = _the_stage_text(path, "t1")
    stopped = _the_stage_text(path, "t2")
    check("$ok" in answered and "$err" not in answered,
          f"an attempt that answered writes $ok and nothing else: {answered!r}")
    check("$err" in stopped and "$ok" not in stopped,
          f"an attempt that stopped writes $err and nothing else: {stopped!r}")
    check("nil" not in answered.split("$interpret_result", 1)[1].split("$time")[0],
          f"and neither writes the branch that did not happen: {answered!r}")


def the_error_keeps_its_fields(tmp: Path):
    """`$err` 里装的是 `InterpretError` 的那一支：哪一种停法、哪一步、那次调用，都在。"""
    from viba.type import (EnvironmentApiInvalidArgumentErr, FAILURE_TAG, Frame,
                           UnderlyingOpErr, VibaProgramErr)

    path = tmp / "error-tickets"
    norm = the_norm_code()
    the_ticket("t1", "nobody.knows", 7, tmp / "s", norm_repo=norm).write(path)
    a_role(ROLE_A, "a", path).run(ticks=1)
    stage = progress.latest(path, "t1")
    result = stage.interpret_result

    check(progress.error_tag(result) == "$not_implemented_err",
          f"the stored error is the branch that happened: "
          f"{progress.error_tag(result)!r}")
    check(progress.error_of_kind(result, "$ok") is None,
          "and the error is no `$ok`")
    check(progress.field_of(result, "$full_qualified_func_name") == "nobody.knows",
          f"which step it was about: {progress.field_of(result, '$full_qualified_func_name')!r}")
    check(progress.field_of(result, "$msg") == "no implementation",
          f"and why: {progress.field_of(result, '$msg')!r}")
    check(progress.call_of(result) is not None,
          "the call itself is kept in the runnable form the error carries")

    # 一段跨两个服务的程序：一个角色只做得到自己那几步，停的那一步也在日志里
    the_ticket("t2", THE_PROGRAM, 1, tmp / "s2", norm_repo=norm).write(path)
    a_role(ROLE_A, "a", path).run(ticks=1)
    stop = progress.latest(path, "t2").interpret_result
    check(progress.field_of(stop, "$full_qualified_func_name") == "service_b.b_scale"
          and progress.field_of(stop, "$module_path") == "/service_b",
          f"and a deferral names the step it stopped at, module and whole name: "
          f"{progress.field_of(stop, '$module_path')!r} "
          f"{progress.field_of(stop, '$full_qualified_func_name')!r}")

    # 四种停法各写各的那一支，字段都留得住
    cases = {
        "$not_implemented_err": UnderlyingOpErr("no implementation", "t1", "double",
                                                the_call("double", 21),
                                                tag="$not_implemented_err"),
        "$underlying_viba_op_err": UnderlyingOpErr("raised: boom", "t1", "double",
                                                   the_call("double", 21),
                                                   tag=FAILURE_TAG),
        "$viba_program_err": VibaProgramErr("broken program", [Frame("main.viba", 0)]),
        "$environment_api_invalid_argument_err": EnvironmentApiInvalidArgumentErr(
            "raised: no such root", "Environment.get_root", the_call("f", 1)),
    }
    for wanted, error in cases.items():
        written = progress.a_stage("t1", "a", tickets.a_result(Err(error), None))
        place = tmp / f"one-{wanted.strip('$')}"
        place.mkdir(parents=True, exist_ok=True)
        progress.write_stage(place, written)
        read = progress.latest(place, "t1").interpret_result
        check(progress.error_tag(read) == wanted,
              f"{wanted} keeps its branch: {progress.error_tag(read)!r}")
        check(progress.field_of(read, "$msg") == error.msg,
              f"{wanted} keeps its $msg: {progress.field_of(read, '$msg')!r}")
        if isinstance(error, UnderlyingOpErr):
            check(progress.field_of(read, "$module_path") == error.module_path
                  and progress.field_of(read, "$full_qualified_func_name") == error.full_qualified_func_name,
                  f"{wanted} keeps the step it was about")
        if isinstance(error, VibaProgramErr):
            check(progress.stack_of(read) == error.stack,
                  f"{wanted} keeps its $stack frame by frame: "
                  f"{progress.stack_of(read)!r}")

    # `$stack` 记的是这次运行当时在哪些调用里：两个框，最外那一帧的行号是 0
    stack = [Frame("main.viba", 0), Frame(str(norm / "simple.viba"), 12)]
    written = progress.a_stage(
        "t1", "a",
        tickets.a_result(Err(VibaProgramErr("broken program", stack)), None))
    progress.write_stage(path, written)
    read = progress.latest(path, "t1").interpret_result
    check(progress.stack_of(read) == stack,
          f"a two-frame $stack reads back: {progress.stack_of(read)!r}")
    check("$stack ListLiteral[" in _the_stage_text(path, "t1"),
          f"and it is written as the list value it is: "
          f"{_the_stage_text(path, 't1')!r}")
    check(progress.the_state(path)[0]["latest_stack"] == ["main.viba:0",
                                                          f"{norm / 'simple.viba'}:12"],
          "the state report names the calls the stop was in")


def the_containers_are_values(tmp: Path):
    """容器字面量是值：`$VIBA_PATH` 是一个真的 `list[str]`，`$stack` 是一个真的 `list[Frame]`。

    这一条盯住这一层依赖的几件事：`ListLiteral` / `DictLiteral` 写在值的位置上就是那个容器，能按地址
    取、能原样写回去；`[]` 不是 viba 的写法；python 的 list 仍然不是 viba data（所以宿主给值的时候要
    走 `tickets._piece`）。viba 哪一头退回去，这几条里的哪一条就红。
    """
    from viba import serialize, viba_ast
    from viba.interpret import (Environment, EnvironmentStorage, read_snapshot,
                                write_snapshot, viba_data)

    # 1) `[]` 不是 viba 的写法；`ListLiteral[]` 才是
    try:
        viba_ast.parse("x = []")
        check(False, "`[]` is not viba's spelling of a list")
    except SyntaxError as problem:
        check("unexpected '['" in str(problem),
              f"`[]` does not parse: {problem}")
    for spelling in ("x = ListLiteral[]", "x = ListLiteral[1]"):
        try:
            viba_ast.parse(spelling)
            check(True, f"{spelling} parses")
        except SyntaxError as problem:
            check(False, f"{spelling} parses: {problem}")

    # 2) 手写的 ListLiteral 读得回来，元素也按位置取得到
    place = tmp / "list-read"
    place.mkdir(parents=True, exist_ok=True)
    (place / "v.viba").write_text("value =\n  ListLiteral[1, 2]\n")
    environ = Environment(EnvironmentStorage("list-read", None, str(tmp)), None)
    back = read_snapshot(environ, "v")
    check(back is not None and len(back) == 2,
          f"a written ListLiteral reads back with its two elements: {back!r}")
    check(back[0].leaf == 1 and back[1].leaf == 2,
          f"and its elements are read by position: {back[0].leaf!r}, {back[1].leaf!r}")

    # 3) 宿主造的 ListLiteral 写得出，写成什么样读回来还是什么样
    node = viba_ast.TypeApp("ListLiteral", [viba_ast.Constant(1)])
    written = serialize.serialize("value", viba_data(node))
    check(not isinstance(written, VibaProgramErr)
          and written.ok_value == 'value =\n  ListLiteral[1]\n',
          f"a host-built ListLiteral has a spelling: {written!r}")
    write_snapshot(environ, node, "host-list")
    check(read_snapshot(environ, "host-list")[0].leaf == 1,
          "and what the host wrote is what reads back")

    # 4) DictLiteral 一样：键是写下来的那些键，值按键取
    dic = viba_ast.TypeApp("DictLiteral", [
        viba_ast.Tuple([viba_ast.Constant("a"), viba_ast.Constant("1")]),
        viba_ast.Tuple([viba_ast.Constant("b"), viba_ast.Constant("2")])])
    write_snapshot(environ, dic, "dic")
    back = read_snapshot(environ, "dic")
    check(back.keys() == ["a", "b"] and back.at_key("b").leaf == "2",
          f"a DictLiteral is read by its keys: {back.keys()!r}")

    # 5) 一个 python list 连 viba data 都不是：宿主给值要先写成 AST（`tickets._piece`）
    try:
        write_snapshot(environ, ["/a", "/b"], "python-list")
        check(False, "a python list is no viba data")
    except RuntimeError as problem:
        check("cannot take list as viba data" in str(problem),
              f"a python list is no viba data: {problem}")

    # 6) 票据上的 `$VIBA_PATH` 就是一个列表值，读回来是那份目录表
    path = tmp / "list-tickets"
    norm = the_norm_code()
    directories = [str(ROOT / "viba"), str(norm)]
    the_ticket("t1", THE_PROGRAM, 21, tmp / "s", viba_paths=directories,
               norm_repo=norm).write(path)
    text = tickets.ticket_text(path, "t1")
    check(f"* $VIBA_PATH ListLiteral[\"{directories[0]}\", \"{directories[1]}\"]" in text,
          f"$VIBA_PATH is written as the list value it is: {text!r}")
    check(tickets.read_ticket(path, "t1").viba_path == directories,
          "and it reads back as that same list, in order")


def _the_stage_text(path: Path, uid: str) -> str:
    files = sorted((path / uid / "progress").glob("*.viba"))
    return files[-1].read_text() if files else ""


# ----------------------------------------------------------------------
# 3) 三个版本都读出来对一遍
# ----------------------------------------------------------------------


def the_versions(tmp: Path):
    """解释器、norm repo、这个角色的代码：三样都读，对不上就不跑。"""
    path = tmp / "version-tickets"
    norm = the_norm_code()
    ticket = the_ticket("t1", THE_PROGRAM, 21, tmp / "s", norm_repo=norm)
    ticket.write(path)
    back = tickets.read_ticket(path, "t1")
    mine = str(_the_role_file(ROLE_A))
    running = handler.the_running_interpreter()

    check(running == the_viba(), f"the running interpreter reads out: {running!r}")
    check(handler.the_commit_id_problem(back, "a", mine, running, repo_of(back, tmp)) is None,
          "the three versions line up, so the call may run")

    elsewhere = the_ticket("t2", THE_PROGRAM, 21, tmp / "s2", norm_repo=norm,
                           viba_commit_id="a-viba-from-elsewhere")
    check("a-viba-from-elsewhere" in (handler.the_commit_id_problem(
        elsewhere, "a", mine, running, repo_of(elsewhere, tmp)) or ""),
        "an interpreter that is not the one the ticket names does not run it")

    wrong_norm = the_ticket("t3", THE_PROGRAM, 21, tmp / "s3", norm_repo=norm,
                            norm_commit_id="a-norm-commit-from-elsewhere")
    check("a-norm-commit-from-elsewhere" in (handler.the_commit_id_problem(
        wrong_norm, "a", mine, running, repo_of(wrong_norm, tmp)) or ""),
        "a norm repo with no such commit does not run it")

    wrong_role = the_ticket("t4", THE_PROGRAM, 21, tmp / "s4", norm_repo=norm,
                            handler_commit_ids={"a": "a-role-commit-from-elsewhere"})
    check("a-role-commit-from-elsewhere" in (handler.the_commit_id_problem(
        wrong_role, "a", mine, running, repo_of(wrong_role, tmp)) or ""),
        "a role whose code is at another commit does not run it")

    check(handler.the_commit_id_problem(back, "a", None, running, repo_of(back, tmp))
          is not None,
          "code whose commit cannot be read anywhere cannot be pinned")
    check(handler.the_commit_id_problem(back, "another-role", None, running,
                                     repo_of(back, tmp)) is None,
          "a role the ticket names no commit for is left free")


# ----------------------------------------------------------------------
# 4) 一个角色一张能力表：谁认哪个名字
# ----------------------------------------------------------------------


def the_roles_serve(tmp: Path):
    """一段跨两个服务的程序：两个角色各做自己那一步，做不到的那一步停下来交给另一个。

    `the_program.viba` 是四个步子串成的链（a、b、a、b），所以这张票据只有两个角色轮着来才做得完：
    每一步的答案都记在自己的存储路径下，后一个角色回放前面几步，只做自己那一步。
    """
    path = tmp / "role-tickets"
    norm = the_norm_code()
    the_ticket("t1", THE_PROGRAM, 1, tmp / "s" / "t1", norm_repo=norm).write(path)

    check(_the_role_file(ROLE_A) != _the_role_file(ROLE_B),
          f"两个角色是两个模块：{_the_role_file(ROLE_A)} 与 {_the_role_file(ROLE_B)}")
    check(handler.where_the_api_is(ROLE_A) == str(_the_role_file(ROLE_A)),
          "每个角色的提交写在它自己那个文件上")

    a, b = a_role(ROLE_A, "a", path), a_role(ROLE_B, "b", path)
    turns = []
    for one in (a, b, a, b):
        one.tick()
        last = progress.latest(path, "t1")
        turns.append((last.handler_name,
                      progress.result_of(last.interpret_result)[1]
                      or progress.field_of(last.interpret_result, "$full_qualified_func_name"),
                      progress.answered(path, "t1")))
    check(turns == [("a", "service_b.b_scale", False), ("b", "service_a.a_add", False),
                    ("a", "service_b.b_scale", False), ("b", True, True)],
          f"each role does its own steps and hands the rest over: {turns!r}")
    check(progress.answered(path, "t1"), "the ticket is finished once the chain is run")
    check(progress.result_of(progress.latest(path, "t1").interpret_result)[0]
          == the_store(tickets.read_ticket(path, "t1"))[CHAIN[-1]],
          "and its answer is the last step of the chain")

    # 轮不到自己的时候不再写一篇：上一篇是谁的，下一手就是别人的
    check(a.tick() == [] and b.tick() == [],
          "a finished ticket is left alone by both roles")


def the_norm_code_runs(tmp: Path):
    """norm repo 里的程序真被跑：每一步都只算一次，答案落在票据自己的存储里。"""
    path = tmp / "runs-tickets"
    storage = tmp / "runs-storage"
    norm = the_norm_code()
    the_ticket("t1", THE_PROGRAM, 1, storage / "t1", norm_repo=norm).write(path)
    notes = the_two_roles(path)
    check(progress.answered(path, "t1"), f"the program ran to its end: {notes!r}")

    ticket = tickets.read_ticket(path, "t1")
    store = the_store(ticket)
    check(tuple(store) == CHAIN,
          f"每一步都在自己的存储路径下记了一次：{store!r}")
    values = [store[where] for where in CHAIN]
    check(values[0] > 1,
          f"a 把抽到的数加在票据给的那个 1 上：{values[0]!r}")
    check(values == sorted(values) and len(set(values)) == 4,
          f"每一步都建立在上一步的答案上，四个值一路变大：{store!r}")
    answer = progress.result_of(progress.latest(path, "t1").interpret_result)[0]
    check(answer == store[CHAIN[-1]],
          f"票据的答案就是链末尾那一步记下来的那个值：{answer!r}")

    at = repo_of(ticket, path)
    check(at.has("the_program") and at.has("service_a") and not at.has("nope"),
          "the repo says which modules it has")


def the_committed_tree_is_what_runs(tmp: Path):
    """norm 代码的提交与工作树是两件事：有人正在改时，跑的是那个提交的树。

    这条要一份**代码真的进了提交**的 norm repo —— `a_committed_norm_repo` 就是为它造的：示例自己
    的代码就在本项目里，而本项目这会儿还全是未提交的改动，那段代码还不在任何提交里。那个 repo 一个
    字节都不写（改的是它自己的工作树，跑的是它提交的树）。
    """
    path = tmp / "dirty-tickets"
    norm = a_committed_norm_repo(tmp)
    commit = code.git_commit(norm, "the norm repo", "t1")
    module = norm / "the_program.viba"
    module.write_text(module.read_text().replace("__impl__ = c3", "__impl__ = c1"))
    before = _git_status(norm)

    the_ticket("t1", THE_PROGRAM, 1, tmp / "s" / "t1", norm_repo=norm,
               norm_commit_id=commit).write(path)
    the_two_roles(path)
    store = the_store(tickets.read_ticket(path, "t1"))
    check(tuple(store) == CHAIN,
          f"the committed four-step program ran, not the two-step edit: {store!r}")
    check(_git_status(norm) == before,
          f"and the norm repo is not written to at all: {_git_status(norm)!r}")
    check(any(one.is_dir() for one in (path / "_norm").iterdir()),
          "the commit's tree is read out under the tickets path instead")


def _git_status(place: Path) -> str:
    done = subprocess.run(["git", "-C", str(place), "status", "--porcelain"],
                          capture_output=True, text=True, timeout=60)
    return done.stdout


def the_handler_only_role(tmp: Path):
    """也有角色自己答的名字：能力表里那一项就是一份普通 python 函数，norm repo 不参与。

    这两张票据的 `$call` 名字（`upper`、`length`）不是 norm repo 里的代码，是两个角色自己算的：
    一个角色答一个名字，另一个名字落在它那儿就是一条停下的记录。
    """
    path = tmp / "python-tickets"
    norm = the_norm_code()
    for uid, name, given in [("t1", "upper", "abc"), ("t2", "length", "abcd")]:
        the_ticket(uid, name, given, tmp / "s" / uid, norm_repo=norm).write(path)

    one = a_role(UPPER, "upper", path)
    report = one.run(ticks=1)
    check([note["ticket"] for note in report["notes"] if note["result"] == "ok"] == ["t1"],
          f"upper 这个角色答它自己那一项: {report['notes']!r}")
    check(progress.result_of(progress.latest(path, "t1").interpret_result) == ("ABC", True),
          "upper(\"abc\") 是 \"ABC\"")

    a_role(LENGTH, "length", path).run(ticks=1)
    check(progress.result_of(progress.latest(path, "t2").interpret_result) == (4, True),
          "length(\"abcd\") 是 4")
    check(not list((tmp / "s").rglob("value.viba")),
          "这两个名字都是纯 python 算的，票据的存储里没有东西")


# ----------------------------------------------------------------------
# 6) 票据的存储：答案落在那儿，第二次从那儿回放
# ----------------------------------------------------------------------


def the_answer_is_kept(tmp: Path):
    """同一张票据被尝试两次：第二次不再跑那段 norm 代码，答案从票据自己的存储里回放。"""
    path = tmp / "kept-tickets"
    storage = tmp / "kept-storage"
    norm = the_norm_code("add_one")
    the_ticket("a1", "add_one", 41, storage / "a1", norm_repo=norm).write(path)

    one = a_role(ADD_ONE, "add_one", path, again=True)
    report = one.run(ticks=1)
    check(report["finished"] and len(report["notes"]) == 2,
          f"one process attempts the ticket twice: {report!r}")
    stages = progress.read_stages(path, "a1")
    check(len(stages) == 2, f"both attempts are in the log: {len(stages)}")
    check(all(stage.is_ok(42) for stage in stages),
          f"both answer the same thing: "
          f"{[progress.result_of(one.interpret_result) for one in stages]!r}")
    snapshot = storage / "a1" / "value.viba"
    check(snapshot.is_file() and "42" in snapshot.read_text(),
          f"the answer is stored at the call's own storage path: {snapshot}")


# ----------------------------------------------------------------------
# 7) 调度：两个真正的处理进程，在 norm repo 上跑
# ----------------------------------------------------------------------


def the_answer_is_a_latch(tmp: Path):
    """一张票据做完了没有，看的是进度里**有没有**一条 `$ok`，不是最新那一条。

    两个进程同时轮询时，一个进程读到的东西可能是旧的：它那条停下的记录会落在别人那条 `$ok` 之后。
    进度只增，答案写进去就一直在，所以票据还是做完了。
    """
    from viba.type import Err, UnderlyingOpErr

    path = tmp / "latch-tickets"
    norm = the_norm_code()
    the_ticket("t1", "a_add", 21, tmp / "s", norm_repo=norm).write(path)
    a_role(ROLE_A, "a", path).run(ticks=1)
    check(progress.answered(path, "t1") and progress.latest_ok(path, "t1"),
          f"the one stage there answered: {progress.the_state(path)!r}")

    # 另一个进程拿的是旧状态，它那条「做不了」落在 `$ok` 后面
    progress.write_stage(path, progress.a_stage(
        "t1", "b", tickets.a_result(
            Err(UnderlyingOpErr("no implementation", "", "a_add")), None)))
    check(not progress.latest_ok(path, "t1"),
          "a stop written after it is now the latest stage")
    check(progress.answered(path, "t1") and progress.finished(path),
          f"and the ticket is finished all the same: {progress.the_state(path)!r}")
    check(progress.the_state(path)[0]["answers"] == 1,
          "the state report says how many stages answered")


def the_schedule(tmp: Path):
    """调度起两个处理进程跑完一批票据：能力表是角色自己的，代码是 norm repo 的。"""
    path = tmp / "scheduled-tickets"
    norm = the_norm_code()
    for uid, given in [("t1", 1), ("t2", 5)]:
        the_ticket(uid, THE_PROGRAM, given, tmp / "s" / uid, norm_repo=norm).write(path)

    first = schedule(path)
    if first["outcome"].get("outcome") != "ok":
        for line in first["outcome"].get("tickets", []):
            print("   state:", line)
    check(first["exit"] == 0 and first["outcome"].get("outcome") == "ok",
          f"the schedule finishes with every ticket finished: {first['outcome']!r}")
    check(first["outcome"].get("rounds", 0) >= 2,
          f"the schedule polls more than once: {first['outcome'].get('rounds')!r}")

    answers = {uid: the_store(tickets.read_ticket(path, uid))[CHAIN[-1]]
               for uid in ("t1", "t2")}
    for uid, answer in answers.items():
        stages = progress.read_stages(path, uid)
        check(any(one.is_ok(answer) for one in stages),
              f"{uid} answers {answer!r} somewhere in its log: "
              f"{[progress.result_of(one.interpret_result) for one in stages]!r}")
    handlers = {one.handler_name for uid in answers
                for one in progress.read_stages(path, uid)}
    check(handlers == {"a", "b"}, f"both roles wrote into the same log: {handlers!r}")

    # 一个进程可能在另一个已经答完之后才把「做不了」写下去：它读到的东西旧了。进度只增，一条答过的
    # 记录就在里面了，后来那条停下的记录顶不掉它 —— 票据还是做完了（`viba-ticket.md` 第 5 节）。
    stale = [(uid, [one.handler_name for one in stages[answered_at + 1:]])
             for uid in answers
             for stages in [progress.read_stages(path, uid)]
             for answered_at in [max([index for index, one in enumerate(stages) if one.ok],
                                     default=None)]
             if answered_at is not None and answered_at + 1 < len(stages)]
    check(progress.finished(path),
          f"a stop written after another handler's $ok does not unfinish the ticket: "
          f"{stale!r}")
    check(all(progress.answered(path, uid) for uid in answers),
          f"and every ticket's log holds a $ok: "
          f"{ {uid: progress.answered(path, uid) for uid in answers}!r}")

    before = {uid: len(progress.read_stages(path, uid)) for uid in answers}
    second = schedule(path)
    check(second["exit"] == 0 and second["outcome"].get("outcome") == "ok"
          and second["outcome"].get("rounds") == 1,
          f"a second schedule over finished tickets is over at once: "
          f"{second['outcome']!r}")
    check(all(len(progress.read_stages(path, uid)) == before[uid] for uid in answers),
          "and appends nothing: answered tickets are left alone")


def schedule(path: Path) -> dict:
    """跑一次 `ticket_system.scheduler`：两个角色各一个进程，谁都不报自己的版本。"""
    done = subprocess.run(
        [sys.executable, "-m", "ticket_system.scheduler",
         "--tickets", str(path), "--handler", f"a={ROLE_A}", "--handler", f"b={ROLE_B}",
         "--interval", "1", "--seconds", str(MOST_SECONDS)],
        cwd=str(ROOT), capture_output=True, text=True, timeout=300)
    lines = [json.loads(line) for line in done.stdout.splitlines()
             if line.strip().startswith("{")]
    check(bool(lines), f"the scheduler reports an outcome: exit {done.returncode}, "
                       f"{done.stderr.strip()[-400:]!r}")
    return {"outcome": lines[-1] if lines else {}, "exit": done.returncode}


def main() -> int:
    scratch = Path(tempfile.mkdtemp(prefix="viba-tickets-"))
    try:
        the_files(scratch / "files")
        the_result_is_one_branch(scratch / "branch")
        the_error_keeps_its_fields(scratch / "errors")
        the_containers_are_values(scratch / "containers")
        the_versions(scratch / "versions")
        the_roles_serve(scratch / "roles")
        the_norm_code_runs(scratch / "runs")
        the_committed_tree_is_what_runs(scratch / "dirty")
        the_handler_only_role(scratch / "plain")
        the_answer_is_kept(scratch / "kept")
        the_answer_is_a_latch(scratch / "latch")
        the_schedule(scratch / "schedule")
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return checks.report()


if __name__ == "__main__":
    sys.exit(main())
