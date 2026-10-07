"""Rule/Witness 用 interpret 重做的第一批：跑规则、调用与回放。

一个规则是程序（环境进、`bool` 出），判定就是跑它；witness 是它判的可序列化数据。
不纯的那一步（量距离）走 `measure`：记录下来的是那次调用本身（可执行的那份）加它给出的值，
放在 storage 里——运行之前就备份好的那份直接回放，没有的才当场量、写进本轮 store。

    python3 tests/test_compliance.py
"""

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "viba"))

from viba import viba_ast, serialize
from compliance import (CallStorage, call_of, given_of, is_compliant, result_of,
                             call_path, record_run, read_call, record_call)
from compliance.demo.host import RULE, DistanceHost
from viba.interpret import Environment, EnvironmentCompute
from viba.reflect import access as reflect_access
from viba.type import (Err, FAILURE_TAG, NOT_IMPLEMENTED_TAG, Ok,
                       UnderlyingOpErr, VibaProgramErr)

COMPLIANCE = Path(__file__).resolve().parent / "data" / "compliance"
BACKUP = COMPLIANCE / "backup"


def case_file(name: str) -> str:
    """One `.viba` case under `tests/data/compliance/`."""
    return str(COMPLIANCE / f"{name}.viba")

PASS = FAIL = 0


def check(ok: bool, label: str):
    global PASS, FAIL
    if ok:
        PASS += 1
    else:
        FAIL += 1
        print(f"FAIL: {label}")


def _not_implemented(result):
    """The stop that says this step has no implementation."""
    return isinstance(result, UnderlyingOpErr) and result.tag == NOT_IMPLEMENTED_TAG


def labelled(result, want, label: str):
    if want is None:
        check(isinstance(result, Ok), f"{label}: {result!r}")
    else:
        check(isinstance(result, VibaProgramErr) and want in result.msg,
              f"{label}: expected VibaProgramErr({want!r}), got {result!r}")


def case_environ(env, name="case_at_1230"):
    """The environment a case's evidence lives under: its own storage path."""
    return Environment(env.storage.sub(name), env.compute)


def environ_for(store, backup=None, host=None):
    host = host or DistanceHost()
    storage = CallStorage("root", None, str(store),
                              None if backup is None else str(backup))
    return Environment(storage, EnvironmentCompute(host.get_func)), host


def run(tmp: Path):
    _judge(tmp)
    _call_and_record(tmp)
    _replay_from_a_shipped_backup(tmp)
    _the_store_wins(tmp)
    _storage(tmp)
    _refusals(tmp)
    _deferral(tmp)
    _a_deferral_carries_the_work(tmp)


def _deferral(tmp: Path):
    """规则里那一步没人实现：判定是递延，不是失败。

    一条没跑完的规则不产生判定，所以 `record_run` 什么都不记进备份——案子不会
    被一个没发生的判定"准备"掉。
    """

    class Partial(DistanceHost):
        """同一个宿主，少一件差事。"""

        def get_func(self, module, func_name):
            if func_name == "distance_ge":
                return None
            return DistanceHost.get_func(self, module, func_name)

    env, host = environ_for(tmp / "deferral-store", tmp / "deferral-backup",
                            host=Partial())
    verdict = is_compliant(str(RULE), env)
    check(_not_implemented(verdict),
          f"a rule whose predicate nobody implements answers the deferral: {verdict!r}")
    check(verdict.full_qualified_func_name == "rule_distance.distance_ge"
          and verdict.module_path == "/rule_distance",
          f"the step names the module and the whole name that stopped: {verdict!r}")
    check(verdict.msg == "no implementation", f"and why: {verdict.msg!r}")
    check(host.measured == [((0, 0), (3, 4))],
          f"the measurement before it still happened: {host.measured}")

    stopped = record_run(str(RULE), env)
    check(_not_implemented(stopped),
          f"record_run answers the deferral too: {stopped!r}")
    backup = tmp / "deferral-backup"
    check(not backup.exists() or not any(backup.rglob("*")),
          "and a judgment that never happened records no call")


def _a_deferral_carries_the_work(tmp: Path):
    """递延里那份调用就是工单要的东西：不必再跑一次，就能写出一份合法记录。"""
    # 一条跑完的规则：它记下的那次调用带着它量过的那份案子数据
    env, host = environ_for(tmp / "work-store")
    check(isinstance(is_compliant(str(RULE), env), Ok), "the rule judges when it can")
    recorded = read_call(case_environ(env), "measure_distance")
    check(recorded is not None, f"and records its call: {recorded!r}")
    wanted = _written(given_of(call_of(recorded)))

    # 少掉量距离那一手：结果里带着同一次调用，可执行的写法
    class NoMeasure(DistanceHost):
        def get_func(self, module, func_name):
            if func_name == "measure_distance":
                return None
            return DistanceHost.get_func(self, module, func_name)

    env, host = environ_for(tmp / "work-deferred", host=NoMeasure())
    duty = is_compliant(str(RULE), env)
    check(_not_implemented(duty), f"the rule defers: {duty!r}")
    check(_written(given_of(duty.call)) == wanted,
          f"the deferral carries the same case data:\n"
          f"{_written(given_of(duty.call))}\n{wanted}")

    # 拿它手写一份记录：$call 就是这份可执行的调用，$result 空着
    hands = case_environ(env)
    record_call(hands, "measure_distance", duty.call, None)
    written = read_call(hands, "measure_distance")
    check(_written(call_of(written)) == _written(duty.call),
          f"a record written from the deferral names the same call: "
          f"{_written(call_of(written))}")
    check(result_of(written) == (None, False),
          f"with no answer yet: {result_of(written)!r}")


def _written(node):
    """One piece of viba data as viba source, laying out flattened away."""
    text = serialize.serialize("call", node)
    if not isinstance(text, Ok):
        return repr(node)
    return " ".join(text.ok_value.split())


def _judge(tmp: Path):
    """跑一个规则：判定就是 __impl__，可序列化数据是 witness 那个程序问来的。"""
    store = tmp / "judge-store"
    env, host = environ_for(store)
    verdict = is_compliant(str(RULE), env)
    check(isinstance(verdict, Ok) and verdict.ok_value is True,
          f"the rule answered true: {verdict!r}")
    check(host.witnessed == ["12:30"],
          f"the witness asked the host for its facts, it did not write them in: "
          f"{host.witnessed}")
    check(host.judged == [5], f"its predicate saw the measured value: {host.judged}")
    check(host.measured == [((0, 0), (3, 4))],
          f"and the measurement ran once: {host.measured}")

    # 另一个案子：12:10 那一刻嫌疑人只在 (0,3)，量出来 3，判定为假
    near_rule = case_file("rule_distance_at_1210")
    env, host = environ_for(tmp / "near-store")
    verdict = is_compliant(near_rule, env)
    check(isinstance(verdict, Ok) and verdict.ok_value is False,
          f"a case 3 apart answers false: {verdict!r}")
    check(host.judged == [3], f"and the predicate saw 3: {host.judged}")


def _call_and_record(tmp: Path):
    """记录：本轮量出来的那份写进 store；record_run 再把它记进备份。"""
    store = tmp / "record-store"
    backup = tmp / "record-backup"
    env, host = environ_for(store, backup)
    check(isinstance(is_compliant(str(RULE), env), Ok), "the run judges")
    check(host.measured == [((0, 0), (3, 4))], "and measures")

    # 本轮 store 里那份：调用的参数定了、结果也写上了；它落在案子自己的数据路径下面
    stored = read_call(case_environ(env), "measure_distance")
    value, has_answer = result_of(stored)
    check(has_answer and value == 5, f"the run's own call carries the answer: {stored!r}")

    check(isinstance(record_run(str(RULE), env), Ok), "record_run judges too")
    check(host.measured == [((0, 0), (3, 4))],
          f"and replays the value it just measured: {host.measured}")
    recorded_file = backup / "root" / "case_at_1230" / "call" / "measure_distance.viba"
    check(recorded_file.is_file(), f"the backup now holds the call: {recorded_file}")
    text = recorded_file.read_text()
    check(text.startswith("value ="), f"as viba source: {text!r}")
    check("* $result 5" in text, f"carrying what it answered: {text!r}")


def _replay_from_a_shipped_backup(tmp: Path):
    """仓库里备份好的那份调用：读它，不重量。"""
    env, host = environ_for(tmp / "replay-store", BACKUP)
    verdict = is_compliant(str(RULE), env)
    check(isinstance(verdict, Ok) and verdict.ok_value is True,
          f"a backed-up call answers the verdict: {verdict!r}")
    check(host.measured == [],
          f"and the impure step is not taken: {host.measured}")
    check(host.judged == [5],
          f"the pure part still runs, on the replayed value: {host.judged}")
    value, has_answer = result_of(read_call(case_environ(env), "measure_distance"))
    check(has_answer and value == 5, f"the call it read carries the answer: {value!r}")

    # 备份是只读的：本轮的目录里没有那份调用，备份文件也没被动过
    check(not (tmp / "replay-store" / "root" / "case_at_1230" / "call"
               / "measure_distance.viba").exists(),
          "a replayed run writes no call of its own")
    check((BACKUP / "root" / "case_at_1230" / "call" / "measure_distance.viba").is_file(),
          "and the backup is still there")


def _the_store_wins(tmp: Path):
    """本轮写的那份压过备份：先看自己，再看备份。"""
    store = tmp / "own-store"
    env, host = environ_for(store, BACKUP)
    case = case_environ(env)
    record_call(case, "measure_distance", viba_ast.Constant(0), 7)
    value, has_answer = result_of(read_call(case, "measure_distance"))
    check(has_answer and value == 7, f"the run's own call is what is read: {value!r}")

    # 备份里还是原来那份
    backup_disk = (BACKUP / "root" / "case_at_1230" / "call"
                   / "measure_distance.viba").read_text()
    check("* $result 5" in backup_disk, "the backup is untouched by the run")


def _storage(tmp: Path):
    """storage 的规矩：哪条路径算一份调用，子 storage 带着两个根。"""
    store = tmp / "plain-store"
    backup = tmp / "plain-backup"
    storage = CallStorage("root", None, str(store), str(backup))
    check(storage.is_call("root/case_at_1230/call/measure_distance.viba") and
          not storage.is_call("root/case_at_1230/measure_distance.viba"),
          "a call is what sits under a `call` segment")
    child = storage.sub("a")
    check(child.call_root_dir == str(backup) and
          child.store_root_dir == str(store) and
          child.is_call("a/call/x.viba"),
          "a child storage keeps both roots, and still knows a call")

    # 不是一份调用的路径：照旧读写自己的 store，备份那边不沾
    storage.write_text("notes.txt", "hello")
    check(storage.read_text("notes.txt") == "hello", "an ordinary file reads back")
    check(storage.read_text("call/absent.viba") is None,
          "a call that neither side has answers None")
    check(not backup.exists() or not any(backup.rglob("*")),
          "and nothing was written into the backup")

    # 没有备份的 storage：那条路径就是普通路径
    plain = CallStorage("root", None, str(tmp / "plain-only"))
    plain.write_text("call/x.viba", "value = 1\n")
    check(plain.read_text("call/x.viba") == "value = 1\n",
          "without a backup a call is just a file in the store")


def _refusals(tmp: Path):
    """判定与调用的错：不是 bool、没有 __impl__、编不过、记不进备份。"""
    env, host = environ_for(tmp / "refuse-store")

    not_a_verdict = case_file("not_a_verdict")
    labelled(is_compliant(not_a_verdict, env), "a verdict is a bool",
             "a rule that answers a string -> VibaProgramErr")

    design = case_file("design_only")
    labelled(is_compliant(design, env), "has no __impl__",
             "a rule that is not a program -> VibaProgramErr")

    broken = case_file("broken")
    labelled(is_compliant(broken, env), "cannot parse",
             "a rule that does not compile -> VibaProgramErr")

    boom_rule = case_file("boom_rule")
    failed_verdict = is_compliant(boom_rule, env)
    check(isinstance(failed_verdict, UnderlyingOpErr)
          and failed_verdict.tag == FAILURE_TAG and "raised" in failed_verdict.msg,
          f"a measurement that blows up -> UnderlyingOpErr: {failed_verdict!r}")
    check(failed_verdict.full_qualified_func_name.endswith(".measure_distance"),
          f"and the failure names the step: {failed_verdict!r}")

    plain = CallStorage("root", None, str(tmp / "no-backup-store"))
    no_backup = Environment(plain, EnvironmentCompute(DistanceHost().get_func))
    labelled(record_run(str(RULE), no_backup), "cannot record a call",
             "record_run without a backup to write -> VibaProgramErr")


if __name__ == "__main__":
    scratch = Path(tempfile.mkdtemp(prefix="viba-compliance-"))
    try:
        run(scratch)
    finally:
        for leftover in sorted(scratch.rglob("*"), reverse=True):
            leftover.unlink() if leftover.is_file() else leftover.rmdir()
    print(f"compliance: {PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)
