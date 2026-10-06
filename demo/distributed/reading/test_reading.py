"""分布式 viba 的第三个 demo：五套服务，一套服务只做一件事。

前两份 demo 里，一套服务实现一两个 api、几步；这一份是五套服务、五个 api，一套一个 —— 程序
`demo/distributed/reading/reading.viba` 把五步串起来，每一步的实参是上一步的结果，而且五步换了
五种类型：int（`gauge.take`，不纯：读数当场抽）→ float（`factor.times`，换算成标签的单位）→
str（`label.write`，写成文本）→ int（`length.count`，数文本多少字符）→ bool（`check.over`，有没有
超限）。五步的数据路径都是程序自己那一层下面的一个子环境，名字就是这一步是什么：`root/taken`、
`root/factored`……

它比前两份多验证一件事：`reading.viba` 里还有一个 `spare` 定义，谁都不需要它（`__impl__` 是
`checked`），所以五套服务里没有任何一套会走到它，store 里也不会出现 `root/spare` —— viba 只在
有人要的时候才算一个定义。

跑它的还是 `distributed` 这个包，命令的写法与前两份一样，`--service` 的条数和
`--store`、`--program` 的值各按这一份填：

    python3 -m distributed.scheduler --store <目录> --program <程序> \
        --service gauge=demo.distributed.reading.gauge \
        --service factor=demo.distributed.reading.factor \
        --service label=demo.distributed.reading.label \
        --service length=demo.distributed.reading.length \
        --service check=demo.distributed.reading.check

预期与前两份相同：最后一轮某个进程上得到 OK；在那之前的每一轮五套服务都停下，而且同一处数据路径
从不重复；每一步只算一次，之后都从 store 里回放。

    python3 demo/distributed/reading/test_reading.py
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

from demo.distributed.reading import PROGRAM, SERVICES
from demo.distributed.reading.check import THE_LIMIT
from demo.distributed.reading.factor import THE_FACTOR

checks = Checks("distributed/reading")
check = checks.check

SCHEDULER = [sys.executable, "-m", "distributed.scheduler"]

# 这条链上的五次调用，按书写次序：数据路径就是它们各自跑在的那个子环境。
CALLS = ["root/taken", "root/factored", "root/labelled", "root/counted", "root/checked"]
LAST_CALL = "root/checked"

# 写下来、谁都不需要的那一次调用，它不该出现在任何一轮里。
SPARE = "root/spare"

# 每一轮至少有一处新数据路径停下，最后一轮得到 OK，所以这条链最多六轮。
MOST_ROUNDS = 6

# 五套服务各自的 api，一套一个：谁也不会停在自己这一个上。
OWNS = {"gauge": {"take"}, "factor": {"times"}, "label": {"write"},
        "length": {"count"}, "check": {"over"}}


def run(tmp: Path):
    store = tmp / "store"
    first = schedule(store)
    if not first["rounds"]:
        return
    _every_service_takes_its_turn(first)
    _the_front_moves(first)
    _each_step_runs_once(first, store)
    _an_unneeded_call_is_never_taken(first, store)
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
    """1) 最后一轮某个进程上得到 OK；在那之前的每一轮，五套服务都停在别处。"""
    last = scheduled["rounds"][-1]
    finished = [name for name, report in last["runs"].items()
                if report["result"] == "ok"]
    check(scheduled["outcome"].get("outcome") == "ok" and finished,
          f"the last round answers OK on a service: {scheduled['outcome']!r}")
    check(all(set(round_report["runs"]) == set(OWNS)
              for round_report in scheduled["rounds"]),
          f"every round starts all five services: "
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

    五套服务是同时在跑的，所以同一处数据路径上可以同时停下几套（它们都不实现那一步）——
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


def _an_unneeded_call_is_never_taken(scheduled, store: Path):
    """3) 谁都不需要的那一次调用不算：没有任何一轮走到它，store 里也没有它。"""
    named = [(one["service"], one["path"]) for round_report in scheduled["rounds"]
             for one in round_report["deferred"] if one["path"] == SPARE]
    check(named == [], f"no service ever stops at the unneeded call: {named!r}")
    check(not (store / SPARE).exists(),
          f"and nothing is written under it: {store / SPARE}")


def _the_chain_adds_up(store: Path):
    """这一链算得对，五步换了五种类型之后还是同一份结果。"""
    reading = _the_answer(store, "root/taken")
    factored = _the_answer(store, "root/factored")
    labelled = _the_answer(store, "root/labelled")
    counted = _the_answer(store, "root/counted")
    checked = _the_answer(store, LAST_CALL)
    check(isinstance(reading, int) and reading >= 5,
          f"the gauge drew a reading at or above the minimum it was given: {reading!r}")
    check(isinstance(factored, float) and factored == reading * THE_FACTOR,
          f"the factor wrote that reading in the label's unit: {factored!r}")
    check(labelled == f"{factored} units",
          f"the label wrote that number as text: {labelled!r}")
    check(counted == len(labelled),
          f"the length counted the characters of that text: {counted!r}")
    check(isinstance(checked, bool) and checked == (counted > THE_LIMIT),
          f"and the check says whether that count is over the limit: {checked!r}")


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
    check(again["outcome"].get("value") == _the_answer(store, LAST_CALL)
          and isinstance(again["outcome"].get("value"), bool),
          f"the answer is the bool the store holds: {again['outcome']!r}")


def _the_answer(store: Path, module_path: str):
    """store 里某个数据路径上落下的结果。"""
    return service.leaf_value(service.read_snapshot(service.environ_at(module_path, store)))


if __name__ == "__main__":
    scratch = Path(tempfile.mkdtemp(prefix="viba-reading-"))
    try:
        run(scratch)
    finally:
        for leftover in sorted(scratch.rglob("*"), reverse=True):
            leftover.unlink() if leftover.is_file() else leftover.rmdir()
    sys.exit(checks.report())
