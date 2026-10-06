"""分布式 viba 的第二个 demo：三套服务、一份程序、一份共享的 store。

与 `demo/distributed/naive/` 那份的区别不只是名字：那里两套服务实现同一对 api、传的全是 int；
这里是三套服务，名字、个数、类型都不同 —— parcels 两个（`read_scale` 不纯：重量在这一刻从秤上
取；`add_handling` 纯：加包装重量），couriers 一个（`days_for`），notices 两个（`announce`、
`emphasize`，都是 str）。程序 `demo/distributed/delivery/estimate.viba` 把每一步放在
`root/order/` 下的一个子环境里，数据路径因此是 `root/order/weight`、`root/order/handling`……
而不是 naive 那份的 `root/c0`。

跑它的还是 `distributed` 这个包（[`distributed/scheduler.py`](../../../distributed/scheduler.py) 是
每一轮的调度，[`distributed/service.py`](../../../distributed/service.py) 是一个服务进程那一侧）。
这一份套件验证的是「调度不认任何具体的服务」：换一套服务数、换一批名字、换一批类型、换一份程序，
同一个 `python3 -m distributed.scheduler` 照样跑：

    python3 -m distributed.scheduler --store <目录> --program <程序> \
        --service parcels=demo.distributed.delivery.parcels \
        --service couriers=demo.distributed.delivery.couriers \
        --service notices=demo.distributed.delivery.notices

预期与 naive 那份相同：最后一轮某个进程上得到 OK；在那之前的每一轮三套服务都停下，而且同一处
数据路径从不重复；每一步只算一次，之后都从 store 里回放。调度能报的四种结局（`ok`、`stuck`、
`unfinished`、`broken`）里，后三种由 naive 那份套件逐条验证。

    python3 demo/distributed/delivery/test_delivery.py
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "tests"))
sys.path.insert(0, str(REPO_ROOT))

from interpreter_support import Checks

from distributed import service

from demo.distributed.delivery import PROGRAM, SERVICES
from demo.distributed.delivery.couriers import KG_PER_DAY
from demo.distributed.delivery.parcels import THE_PACKING, THE_SCALE

checks = Checks("distributed/delivery")
check = checks.check

SCHEDULER = [sys.executable, "-m", "distributed.scheduler"]

# 这条链上的五次调用，按书写次序：数据路径就是它们各自跑在的那个子环境。
CALLS = ["root/order/weight", "root/order/handling", "root/order/days",
         "root/order/notice", "root/order/title"]
LAST_CALL = "root/order/title"

# 每一轮至少有一处新数据路径停下，最后一轮得到 OK，所以这条链最多六轮。
MOST_ROUNDS = 6

# 三套服务各自的 api：谁也不会停在自己这一组上。
OWNS = {"parcels": {"read_scale", "add_handling"},
        "couriers": {"days_for"},
        "notices": {"announce", "emphasize"}}


def run(tmp: Path):
    store = tmp / "store"
    first = schedule(store)
    if not first["rounds"]:
        return
    _every_service_takes_its_turn(first)
    _the_front_moves(first)
    _each_step_runs_once(first, store)
    _the_chain_adds_up(store)
    _the_failure_state_is_in_the_store(store, first)
    _the_store_is_the_memory(store)


def schedule(store: Path):
    """跑一次调度：它每轮各一行 JSON，最后一行是整次的结局。"""
    command = SCHEDULER + ["--store", str(store), "--program", PROGRAM]
    for one in SERVICES:
        command += ["--service", one]
    done = subprocess.run(command, cwd=str(REPO_ROOT), capture_output=True, text=True,
                          timeout=300)
    lines = [json.loads(line) for line in done.stdout.splitlines()
             if line.strip().startswith("{")]
    rounds = [line for line in lines if isinstance(line, dict) and "runs" in line]
    check(done.returncode == 0 and bool(rounds) and bool(lines),
          f"the scheduler finishes within its rounds: exit {done.returncode}, "
          f"{done.stderr.strip()[-400:]!r}")
    return {"outcome": lines[-1] if lines else {}, "rounds": rounds,
            "exit": done.returncode}


def _every_service_takes_its_turn(scheduled):
    """1) 最后一轮某个进程上得到 OK；在那之前的每一轮，三套服务都停在别处。"""
    last = scheduled["rounds"][-1]
    finished = [name for name, report in last["runs"].items()
                if report["result"] == "ok"]
    check(scheduled["outcome"].get("outcome") == "ok" and finished,
          f"the last round answers OK on a service: {scheduled['outcome']!r}")
    check(all(set(round_report["runs"]) == set(OWNS)
              for round_report in scheduled["rounds"]),
          f"every round starts all three services: "
          f"{[sorted(one['runs']) for one in scheduled['rounds']]!r}")
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

    三套服务是同时在跑的，所以同一处数据路径上可以同时停下两套（它们都不实现那一步）——
    一轮里几套停在同一个调用上不算重复；同一个调用在两轮里各停一次才算。
    """
    stopped_before = set()
    for number, round_report in enumerate(scheduled["rounds"]):
        deferred = round_report["deferred"]
        if number < len(scheduled["rounds"]) - 1:
            check(len(deferred) == len(round_report["runs"]),
                  f"round {round_report['round']} stops every service: {deferred!r}")
        this_round = set()
        for one in deferred:
            check(one["path"] in CALLS and one["func_name"] not in OWNS[one["service"]],
                  f"{one['service']} stops at another service's call: {one!r}")
            check((one["path"], one["func_name"]) not in stopped_before,
                  f"round {round_report['round']} stops at {one['path']} "
                  f"({one['func_name']}), where an earlier round stopped already")
            this_round.add((one["path"], one["func_name"]))
        stopped_before |= this_round


def _each_step_runs_once(scheduled, store: Path):
    """每一步只算一次，不纯的那一步也一样：算过的数据路径，之后每一轮都回放。"""
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


def _the_chain_adds_up(store: Path):
    """这一链算得对：秤上的那个重量一步步推到最后那张通知。"""
    weight = _the_answer(store, "root/order/weight")
    handling = _the_answer(store, "root/order/handling")
    days = _the_answer(store, "root/order/days")
    notice = _the_answer(store, "root/order/notice")
    title = _the_answer(store, LAST_CALL)
    check(weight in THE_SCALE and weight >= 2,
          f"the scale drew one of its weights, none below the given least: {weight!r}")
    check(handling == weight + THE_PACKING,
          f"the packing weight was added once: {handling!r}")
    check(days == 1 + handling // KG_PER_DAY, f"the days follow that weight: {days!r}")
    check(notice == f"{days} days", f"the notice writes those days: {notice!r}")
    check(isinstance(title, str) and title == notice.upper(),
          f"and the last leaf writes that notice in upper case: {title!r}")


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
            order = store / one["path"] / "prepare" / f"{one['func_name']}.viba"
            check(order.is_file(), f"and the work order is where it stopped: {order}")


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


def _the_answer(store: Path, module_path: str):
    """store 里某个数据路径上落下的结果。"""
    return service.leaf_value(service.read_snapshot(service.environ_at(module_path, store)))


if __name__ == "__main__":
    scratch = Path(tempfile.mkdtemp(prefix="viba-delivery-"))
    try:
        run(scratch)
    finally:
        for leftover in sorted(scratch.rglob("*"), reverse=True):
            leftover.unlink() if leftover.is_file() else leftover.rmdir()
    sys.exit(checks.report())
