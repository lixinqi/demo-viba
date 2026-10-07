"""分布式 viba 的 demo：一份程序、两套服务、一份共享的 store。

两套服务各是一组 api 加一个 python 进程（A 的 api 只跑在 A 的进程里，B 的只跑在 B 的
进程里）。`demo/distributed/naive/interleaved.viba` 是一份把两边 api 交错起来的程序：每一步的实参
是上一步的结果，所以两个服务进程只能轮流接。一个进程执行到不属于自己的一步就停下，结果是
`UnderlyingOpErr`（`tag` 是 `$not_implemented_err`，里面带着这一步声明在哪个模块、它的整名
（`$module_path`、`$full_qualified_func_name`）与这次调用本身 `$call`）；调度把这次停下
写进两个服务进程共享的 environment storage —— viba 代码落在这一步的数据路径下
（`<数据路径>/call/<api>.viba`），这一轮再记一份 `failure/round-<k>.viba`。下一轮那套服务先
把它补上，结果落进同一个数据路径；停下过的运行再从 store 里回放出来接着往下走：**重跑即续跑**。

跑它的是 `distributed` 这个包：[`distributed/service.py`](../../../distributed/service.py) 是一个服务
进程那一侧，[`distributed/scheduler.py`](../../../distributed/scheduler.py) 是每一轮的调度。这个套件跑：

    python3 -m distributed.scheduler --store <目录> --program <程序> \
        --service a=demo.distributed.naive.service_a \
        --service b=demo.distributed.naive.service_b

每次同时启动两个进程，重复跑这份程序，轮次之间共用同一个 store。预期：

    1) 最后一轮某个进程上最终得到 OK（`{"outcome": "ok", ...}`，退出码 0）；
    2) 最后一轮之前的每一轮，两个进程报的都是 `not_my_duty`，而且停下的数据路径从不重复 —— 前面停过的
       数据路径在下一轮开始前一定已经处理掉，所以再跑到那里只会回放，不会停第二次；
    3) 轮数有上限（`--rounds`，默认 1024），「已经停过的数据路径上又停一次」当场报成失败，服务进程
       起不来就报成 `broken` —— 不会死循环。

store 由这个套件造在临时目录里；计数的 `Checks` 还是用 `tests/interpreter_support.py`
那一套 —— 仓库里的套件都这么报数。

    python3 demo/distributed/naive/test_distributed.py
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "tests"))
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "viba"))
# The service processes this suite starts must find the viba package too.
os.environ["PYTHONPATH"] = os.pathsep.join(
    [str(REPO_ROOT / "viba")] + ([os.environ["PYTHONPATH"]]
                                 if os.environ.get("PYTHONPATH") else []))

from interpreter_support import Checks

from compliance import result_of, read_call

from demo.distributed.naive import PROGRAM, SERVICES
from distributed import service

checks = Checks("distributed/naive")
check = checks.check

SCHEDULER = [sys.executable, "-m", "distributed.scheduler"]

# 这条链上的五次调用，按书写次序：数据路径就是它们各自跑在的那个子环境。
CALLS = ["root/c0", "root/c1", "root/c2", "root/c3", "root/c4"]
LAST_CALL = "root/c4"

# 每一轮至少有一处新数据路径停下，最后一轮得到 OK，所以这条链最多六轮。
MOST_ROUNDS = 6

# 两套服务各自的 api：谁也不会停在自己这一组上。
OWNS = {"a": {"a_step", "a_scale"}, "b": {"b_step", "b_scale"}}


def run(tmp: Path):
    store = tmp / "store"
    first = schedule(store)
    if not first["rounds"]:
        return
    _the_last_round_answers(first)
    _the_front_moves(first)
    _an_impure_step_runs_once(first, store)
    _the_failure_state_is_in_the_store(store, first)
    _the_store_is_the_memory(store)
    _a_schedule_that_cannot_move(tmp)
    _a_schedule_that_breaks(tmp)


def run_scheduler(store: Path, *extra: str):
    """跑一次调度：退出码、它每轮各那一行 JSON、最后那行结局。"""
    command = SCHEDULER + ["--store", str(store), "--program", PROGRAM]
    for one in SERVICES:
        command += ["--service", one]
    done = subprocess.run(command + list(extra), cwd=str(REPO_ROOT),
                          capture_output=True, text=True, timeout=300)
    lines = [json.loads(line) for line in done.stdout.splitlines()
             if line.strip().startswith("{")]
    return {"exit": done.returncode, "stderr": done.stderr, "lines": lines,
            "outcome": lines[-1] if lines else {},
            "rounds": [line for line in lines
                       if isinstance(line, dict) and "runs" in line]}


def schedule(store: Path, *extra: str, want_ok=True):
    """跑一次调度，并且要求它把自己报全：每轮一行，最后一行是整次的结局。"""
    done = run_scheduler(store, *extra)
    if want_ok:
        check(done["exit"] == 0 and bool(done["rounds"]) and bool(done["lines"]),
              f"the scheduler finishes within its rounds: exit {done['exit']}, "
              f"{done['stderr'].strip()[-400:]!r}")
    else:
        check(bool(done["rounds"]) and bool(done["lines"]),
              f"the scheduler reports every round it ran: exit {done['exit']}, "
              f"{done['stderr'].strip()[-400:]!r}")
    return done


def _the_last_round_answers(scheduled):
    """1) 最后一轮某个进程上得到 OK；在那之前的每一轮，两边都停在别处。"""
    last = scheduled["rounds"][-1]
    finished = [name for name, report in last["runs"].items()
                if report["result"] == "ok"]
    check(scheduled["outcome"].get("outcome") == "ok" and finished,
          f"the last round answers OK on a service: {scheduled['outcome']!r}")
    check(scheduled["outcome"].get("rounds") == len(scheduled["rounds"])
          and scheduled["outcome"].get("service") in finished,
          f"the outcome names the round and the service that got there: "
          f"{scheduled['outcome']!r}")
    check(len(scheduled["rounds"]) <= MOST_ROUNDS,
          f"a chain of five calls takes at most {MOST_ROUNDS} rounds, not "
          f"{len(scheduled['rounds'])}")
    for round_report in scheduled["rounds"][:-1]:
        stopped = [report["result"] for report in round_report["runs"].values()]
        check(stopped == ["not_my_duty"] * len(stopped),
              f"round {round_report['round']} has no OK yet: {stopped!r}")


def _the_front_moves(scheduled):
    """2) 停下的数据路径从不重复：一轮的失败状态在下一轮开始前已经处理掉。

    两个进程是同时在跑的，所以一轮能往前挪多远看它们怎么交错 —— 这条链有时两三轮才走完，
    有时一轮就走完（互相都赶上了）。不变的是：没有哪个数据路径停下两次，没停过的那一轮就是
    已经 OK 的那一轮。
    """
    seen = []
    for number, round_report in enumerate(scheduled["rounds"]):
        deferred = round_report["deferred"]
        if number < len(scheduled["rounds"]) - 1:
            check(len(deferred) == len(round_report["runs"]),
                  f"round {round_report['round']} stops both services: {deferred!r}")
        for one in deferred:
            check(one["path"] in CALLS and one["func_name"] not in OWNS[one["service"]],
                  f"{one['service']} stops at another service's call: {one!r}")
            check((one["path"], one["func_name"]) not in seen,
                  f"round {round_report['round']} stops at {one['path']} "
                  f"({one['func_name']}), where an earlier round stopped already")
            seen.append((one["path"], one["func_name"]))


def _an_impure_step_runs_once(scheduled, store: Path):
    """不纯的那一步只跑一次：算过的数据路径，之后每一轮都回放。"""
    computed = []
    for scheduled_round in scheduled["rounds"]:
        reports = list(scheduled_round["runs"].values()) + \
            list(scheduled_round["answered"].values())
        for report in reports:
            for note in report["api"]:
                if note["computed"]:
                    computed.append(note["path"])
    check(sorted(computed) == sorted(CALLS),
          f"each api call of the chain is computed exactly once: {sorted(computed)!r}")
    check(all((store / path / "value.viba").is_file() for path in CALLS),
          f"and every answer is recorded where the call ran: "
          f"{sorted(str(one.relative_to(store)) for one in store.rglob('value.viba'))!r}")


def _the_failure_state_is_in_the_store(store: Path, scheduled):
    """调度每次执行都把这一轮的失败状态写进 environment storage。"""
    for round_report in scheduled["rounds"]:
        number = round_report["round"]
        record = store / "failure" / f"round-{number}.viba"
        check(record.is_file(), f"round {number} leaves its failure state: {record}")
        text = record.read_text() if record.is_file() else ""
        for one in round_report["deferred"]:
            check(one["func_name"] in text and one["path"] in text,
                  f"round {number} names the call it stopped at: {text!r}")
            order = store / one["path"] / "call" / f"{one['func_name']}.viba"
            check(order.is_file(), f"and the work order is where it stopped: {order}")
            if round_report is not scheduled["rounds"][-1]:
                answered, has_answer = result_of(
                    read_call(service.environ_at(one["path"], store), one["func_name"]))
                check(has_answer and answered == _the_answer(store, one["path"]),
                      f"the next round answered {one['path']}: {answered!r}")


def _the_store_is_the_memory(store: Path):
    """同一份 store 上再调度一次：一步不用算，一轮就 OK。"""
    again = schedule(store)
    check(again["outcome"].get("outcome") == "ok"
          and again["outcome"].get("rounds") == 1,
          f"a second schedule on the same store finishes at once: {again['outcome']!r}")
    computed = [note["path"] for scheduled_round in again["rounds"]
                for report in list(scheduled_round["runs"].values())
                + list(scheduled_round["answered"].values())
                for note in report["api"] if note["computed"]]
    check(computed == [], f"and computes nothing: {computed!r}")
    check(again["outcome"].get("value") == _the_answer(store, LAST_CALL),
          f"the answer is the one the store holds: {again['outcome']!r}")


def _the_answer(store: Path, path: str):
    """store 里某个数据路径上落下的结果（一个 int）。"""
    return service.leaf_value(service.read_snapshot(service.environ_at(path, store)))


# 一条谁都处理不了的链：只有一个调用，两个进程都不实现它。工单写下去也没人接，所以第二轮会
# 在同一个数据路径上再停一次 —— 调度当场把「状态没有动」报出来，而不是一轮一轮跑下去。
STUCK = """\
__decl__ = int <- $env Env

args = __get_args__ << __decl__

c_step =
    int
  <- $env Env
  <- $x int
  <- { nobody implements this }

c0 = c_step << $env ($sub_env << args.env << "c0") << $x 1

__impl__ = c0
"""


def _a_schedule_that_cannot_move(tmp: Path):
    """3) 状态不动就报失败，轮数到了上限也报失败 —— 都不会死循环。"""
    program = tmp / "stuck.viba"
    program.write_text(STUCK)

    stuck = schedule(tmp / "stuck-store", "--program", str(program), want_ok=False)
    check(stuck["outcome"].get("outcome") == "stuck" and stuck["exit"] == 1,
          f"a call nobody answers stops the schedule instead of looping: "
          f"{stuck['outcome']!r}")
    check(len(stuck["rounds"]) == 2,
          f"and it takes one answered-nothing round to see it: {len(stuck['rounds'])}")

    capped = schedule(tmp / "capped-store", "--program", str(program), "--rounds", "1",
                      want_ok=False)
    check(capped["outcome"].get("outcome") == "unfinished" and capped["exit"] == 1,
          f"the round cap reports a schedule that did not finish: {capped['outcome']!r}")
    check(len(capped["rounds"]) == 1, f"the cap is the rounds it ran: {capped['rounds']!r}")


def _a_schedule_that_breaks(tmp: Path):
    """3) 服务进程起不来就报成 `broken`，而不是一轮一轮等下去。

    起不来也是一种坏：模块名给错、进程自己崩了，调度拿到的是没有那一行 JSON 的报告。这一支在打印
    任何一轮之前就结束这次调度，所以它只留下那行结局。
    """
    broken = run_scheduler(tmp / "broken-store",
                           "--service", "broken=no.such.service.module")
    check(broken["outcome"].get("outcome") == "broken"
          and broken["outcome"].get("round") == 1 and broken["exit"] == 1,
          f"a service that cannot start ends the schedule: {broken['outcome']!r}")
    check(not broken["rounds"], f"and no round is reported for it: {broken['rounds']!r}")
    reports = broken["outcome"].get("reports") or []
    check(bool(reports) and all(one["service"] == "broken"
                                and one["result"] == "crashed" for one in reports),
          f"the outcome names the service that could not start: {reports!r}")


if __name__ == "__main__":
    scratch = Path(tempfile.mkdtemp(prefix="viba-distributed-"))
    try:
        run(scratch)
    finally:
        for leftover in sorted(scratch.rglob("*"), reverse=True):
            leftover.unlink() if leftover.is_file() else leftover.rmdir()
    sys.exit(checks.report())
