"""`distributed/service.py`：一套服务那一侧 —— 能力表、补账、跑一遍。

实现拿到的实参是这一次调用的一个个实参，环境排在第一位，和运行那一侧一样（`_call_host` 一个实参
交一份）。工单里留得下只有可序列化数据，几个实参写成一份带 tag 的积（`$call($x 1 * $y 2)`），一个
实参就是那个值本身。补账时按实现自己的参数个数交：一个参数交整份 `$call`（它本身是个积也一样），
几个参数就按书写次序拆开交 —— 实参里有宿主值的调用交不出那么多份，当场报错，而不是少交一份。

`arguments_taken` 与 `the_arguments` 是这条规矩的两半；最后一个用例把它放回调度里跑一遍：两个实参
的调用被别人停下、留成工单交回来，补账那一次必须交到两份实参。

    python3 tests/test_distributed_service.py
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from interpreter_support import Checks

from distributed import service
from distributed.service import Service, arguments_taken, the_arguments

from viba import viba_ast
from compliance import measured_of, prepare_path, read_prepare
from viba.interpret import snapshot_path, viba_data

checks = Checks("distributed_service")
check = checks.check

REPO_ROOT = Path(__file__).resolve().parent.parent

# 一份两个实参的程序：`draw` 归 left，`combine` 归 right，而且 `combine` 的实参是 `draw` 的结果 ——
# 所以 `combine` 一定先被别人停下、留成工单。
TWO_ARGUMENT_PROGRAM = """\
__decl__ = int <- $env Env

args = __get_args__ << __decl__

import two_api

c1 = two_api.draw << $env ($sub_env << args.env << "c1") << $x 4
c0 = two_api.combine << $env ($sub_env << args.env << "c0") << $x c1 << $y 2

__impl__ = c0
"""

TWO_ARGUMENT_API = """\
draw =
    int
  <- $env Env
  <- $x int
  <- { answer the argument itself }

combine =
    int
  <- $env Env
  <- $x int
  <- $y int
  <- { add the two arguments }
"""

LEFT_SERVICE = """\
import sys

from distributed.service import Service, run_service


def the_api(service: Service):
    def draw(environ, x):
        return service.recorded(environ, lambda: int(x.value))

    return {"draw": draw}


def main(argv=None) -> int:
    return run_service("left", the_api, argv)


if __name__ == "__main__":
    sys.exit(main())
"""

RIGHT_SERVICE = """\
import sys

from distributed.service import Service, run_service


def the_api(service: Service):
    def combine(environ, x, y):
        return service.recorded(environ, lambda: int(x.value) + int(y.value))

    return {"combine": combine}


def main(argv=None) -> int:
    return run_service("right", the_api, argv)


if __name__ == "__main__":
    sys.exit(main())
"""


def run(tmp: Path):
    _how_many_arguments_an_implementation_takes()
    _the_call_split_in_written_order()
    _a_call_that_cannot_be_answered()
    _a_call_with_no_arguments(tmp)
    _a_single_argument_stays_one(tmp)
    _a_work_order_is_answered(tmp)
    _a_two_argument_call_kept_whole(tmp)


def the_work_order(store: Path, module_path: str, func_name: str, call):
    """把一份还没人补的工单写进 store —— 调度写它的那两行（`save_the_failure`）。"""
    environ = service.environ_at(module_path, store)
    environ.storage.write_text(snapshot_path(environ, prepare_path(func_name)),
                               service.prepare_text(call))


def _how_many_arguments_an_implementation_takes():
    """实现的签名说它要几个实参；说不出来的（没有签名，或者收可变个数的）交整份 `$call`。"""

    def only_the_environment(environ):
        return 0

    def one(environ, x):
        return x

    def two(environ, x, y):
        return x

    def varying(environ, *args):
        return args

    check(arguments_taken(only_the_environment) == 0,
          f"an implementation of the environment alone takes nothing: "
          f"{arguments_taken(only_the_environment)}")
    check(arguments_taken(one) == 1, f"one argument: {arguments_taken(one)}")
    check(arguments_taken(two) == 2,
          f"the environment is not counted: {arguments_taken(two)}")
    check(arguments_taken(varying) == -1,
          f"a varying number of arguments leaves the `$call` whole: "
          f"{arguments_taken(varying)}")
    check(arguments_taken(len) == 0,
          f"one positional parameter is the environment, not an argument: "
          f"{arguments_taken(len)}")
    check(arguments_taken(dict.update) == -1,
          f"and a callable whose signature cannot be read leaves the `$call` whole: "
          f"{arguments_taken(dict.update)}")


def _the_call_split_in_written_order():
    """几个实参写成一份带 tag 的积：按书写次序拆开，tag 只说明它去了哪个位置。"""
    call = viba_data(viba_ast.ProductChain([
        viba_ast.Tagged("$x", viba_ast.Constant(1)),
        viba_ast.Tagged("$y", viba_ast.Constant(2)),
        viba_ast.Tagged("$z", viba_ast.Constant(3))]))
    arguments = the_arguments(call, 3, "combine")
    check([one.value for one in arguments] == [1, 2, 3],
          f"the pieces come out in written order: {[one.value for one in arguments]!r}")

    # 括号里写出来的分组是这一份积自己的结构（一个实参），不是两个实参：它留在原地。
    grouped = viba_data(viba_ast.Product(
        viba_ast.Tagged("$x", viba_ast.Constant(1)),
        viba_ast.Product(viba_ast.Tagged("$y", viba_ast.Constant(2)),
                         viba_ast.Tagged("$z", viba_ast.Constant(3)))))
    pieces = the_arguments(grouped, 2, "combine")
    check(len(pieces) == 2 and pieces[0].value == 1,
          f"a branch stays one piece: {[len(pieces), pieces[0].value]!r}")


def _a_call_that_cannot_be_answered():
    """实参里有宿主值的调用留不了工单：当场报错，不少交一个实参。"""
    call = viba_data(viba_ast.Constant(9))
    try:
        the_arguments(call, 2, "combine")
    except ValueError as problem:
        check("takes 2 arguments" in str(problem) and "holds 1" in str(problem),
              f"too few arguments for the implementation is refused: {problem}")
    else:
        check(False, "a call with one argument for a two-argument implementation "
                     "was handed over anyway")


def _a_call_with_no_arguments(tmp: Path):
    """只有环境的调用：`$call` 是 nil，实现就收一个环境，不多收一个 nil。"""
    store = tmp / "none"
    the_work_order(store, "root/c0", "now", None)
    seen = []

    def the_api(owner: Service):
        def now(environ):
            seen.append("called")
            return owner.recorded(environ, lambda: 11)

        return {"now": now}

    the_service = Service("right", the_api, store, str(tmp / "program.viba"))
    answered = the_service.answer_pending()
    check(seen == ["called"],
          f"an implementation of the environment alone is called with it: {seen!r}")
    check(answered == [{"path": "root/c0", "func_name": "now", "value": 11}],
          f"and its answer is the one reported: {answered!r}")


def _a_single_argument_stays_one(tmp: Path):
    """一个实参的调用交整份 `$call`：哪怕它本身是个带 tag 的积，也不按积的大小拆开。"""
    store = tmp / "single"
    pair = viba_data(viba_ast.ProductChain([
        viba_ast.Tagged("$left", viba_ast.Constant(1)),
        viba_ast.Tagged("$right", viba_ast.Constant(4))]))
    the_work_order(store, "root/c0", "join", pair)
    seen = []

    def the_api(owner: Service):
        def join(environ, pair_value):
            try:
                seen.append(("leaf", pair_value.value))
            except Exception:
                seen.append(("no leaf", None))
            return owner.recorded(environ, lambda: 7)

        return {"join": join}

    the_service = Service("right", the_api, store, str(tmp / "program.viba"))
    answered = the_service.answer_pending()
    check(seen and seen[0][0] == "no leaf",
          f"the one-argument implementation is handed the product itself: {seen!r}")
    check(answered == [{"path": "root/c0", "func_name": "join", "value": 7}],
          f"and its answer is the one reported: {answered!r}")


def _a_work_order_is_answered(tmp: Path):
    """两个实参的工单：补账时两份实参都交到，结果落在这个数据路径下。"""
    store = tmp / "two"
    call = viba_data(viba_ast.ProductChain([
        viba_ast.Tagged("$x", viba_ast.Constant(4)),
        viba_ast.Tagged("$y", viba_ast.Constant(2))]))
    the_work_order(store, "root/c0", "combine", call)
    seen = []

    def the_api(owner: Service):
        def combine(environ, x, y):
            seen.append((x.value, y.value))
            return owner.recorded(environ, lambda: int(x.value) + int(y.value))

        return {"combine": combine}

    the_service = Service("right", the_api, store, str(tmp / "program.viba"))
    answered = the_service.answer_pending()
    check(seen == [(4, 2)], f"the implementation is handed both arguments: {seen!r}")
    check(answered == [{"path": "root/c0", "func_name": "combine", "value": 6}],
          f"and the answer is the one reported: {answered!r}")
    check(service.leaf_value(service.read_snapshot(
              service.environ_at("root/c0", store))) == 6,
          "and the answer is recorded where the call ran")
    measured, it_is_measured = measured_of(
        read_prepare(service.environ_at("root/c0", store), "combine"))
    check(it_is_measured and measured == 6,
          f"and the work order carries the measurement: {measured!r}")


def _a_two_argument_call_kept_whole(tmp: Path):
    """走一遍真正的调度：两个实参的调用被别人停下，留成工单，下一轮补上。"""
    home = tmp / "two_arguments"
    home.mkdir()
    (home / "program.viba").write_text(TWO_ARGUMENT_PROGRAM)
    (home / "two_api.viba").write_text(TWO_ARGUMENT_API)
    (home / "left_service.py").write_text(LEFT_SERVICE)
    (home / "right_service.py").write_text(RIGHT_SERVICE)
    path = [str(REPO_ROOT), str(home)]
    if os.environ.get("PYTHONPATH"):
        path.append(os.environ["PYTHONPATH"])
    done = subprocess.run(
        [sys.executable, "-m", "distributed.scheduler",
         "--store", str(tmp / "two_arguments_store"),
         "--program", str(home / "program.viba"),
         "--service", "left=left_service", "--service", "right=right_service"],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=300,
        env=dict(os.environ, PYTHONPATH=os.pathsep.join(path)))
    lines = [json.loads(one) for one in done.stdout.splitlines()
             if one.strip().startswith("{")]
    check(done.returncode == 0 and lines and lines[-1].get("outcome") == "ok",
          f"a call with two arguments is answered from its work order: exit "
          f"{done.returncode}, {done.stdout[-200:]!r} {done.stderr[-300:]!r}")
    check(bool(lines) and lines[-1].get("value") == 6,
          f"and both arguments arrived: {lines[-1] if lines else None!r}")


if __name__ == "__main__":
    scratch = Path(tempfile.mkdtemp(prefix="viba-distributed-service-"))
    try:
        run(scratch)
    finally:
        for leftover in sorted(scratch.rglob("*"), reverse=True):
            leftover.unlink() if leftover.is_file() else leftover.rmdir()
    sys.exit(checks.report())
