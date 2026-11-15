"""viba_acp 的套件：一份程序、一个模块 `acp.viba`、一个真正说 ACP 的 agent。

这个套件跑 `run.py`（和读它的人跑的是同一条命令），然后读它留下的两样东西：调度每一轮那行
JSON，和 `--trace` 里一行一条的 ACP 消息。预期：

1) 程序得到 `ok`：trace 里一次 `session/prompt`，带 `session/update` 的文本与一个 `end_turn`；
2) 一个服务进程只 `initialize` 一次、只开一个会话；
3) 会话编号记在 `root/c0`，这一轮的响应记在 `root/c1`；
4) 同一个 store 再跑一次，一个 prompt 都不发：每一步都在 store 里回放了；
5) 客户端自己的几条边角：工具调用与权限、提问超时会发 `session/cancel` 并拿到 `cancelled`；
   agent 报一个 ACP 没有的 stopReason，客户端拒绝它；agent 起不来，客户端报错而不是挂住。

    python3 demo/viba_acp/test_agent.py
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent        # demo/viba_acp
ROOT = HERE.parent.parent                     # the repository root
LAYER = ROOT / "viba_acp"                     # the interface, the service, the ACP client
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "viba"))
sys.path.insert(0, str(LAYER))
sys.path.insert(0, str(HERE))

from interpreter_support import Checks

from distributed import service
from viba.interpret import get_snapshot

import acp_client
from run import module_source

checks = Checks("viba_acp")
check = checks.check

RUN = [sys.executable, str(HERE / "run.py")]
SCRIPTED_AGENT = [sys.executable, str(LAYER / "scripted_agent.py")]


def run_demo(store: Path, trace: Path, *extra: str):
    """Run the demo once; read its JSON lines (one per round, the last the outcome)."""
    result = subprocess.run(
        RUN + ["--store", str(store), "--trace", str(trace), "--fresh", *extra],
        capture_output=True, text=True, timeout=120)
    lines = [json.loads(one) for one in result.stdout.splitlines()
             if one.strip().startswith("{")]
    return result, lines


def messages(trace: Path) -> list:
    """Every ACP message in the trace, as (direction, message)."""
    if not trace.exists():
        return []
    lines = [line for line in trace.read_text(encoding="utf-8").splitlines()
             if line.strip()]
    return [(one["dir"], one["message"]) for one in map(json.loads, lines)]


def requests(trace: Path, method: str, direction="client->agent") -> list:
    """Every request of one method the given side sent, in order."""
    return [message for one_direction, message in messages(trace)
            if one_direction == direction and message.get("method") == method]


def responses_to(trace: Path, request_id, direction="agent->client") -> list:
    """Every response carrying this id, in the direction the request went."""
    return [message for one_direction, message in messages(trace)
            if one_direction == direction and message.get("id") == request_id]


def snapshot(store: Path, path: str):
    """The value recorded under one call's path."""
    return get_snapshot(service.environ_at(path, store))


def stop_reason_of(response) -> str:
    return response.by_tag("$stop_reason").value


def run(tmp: Path):
    _one_schedule_runs_the_agent(tmp)
    _the_sources_are_documents(tmp)
    _the_same_store_asks_nothing(tmp)
    _the_permission_path()
    _the_update_callback()
    _the_client_edges()


def _one_schedule_runs_the_agent(tmp: Path):
    store, trace = tmp / "one", tmp / "one.jsonl"
    result, lines = run_demo(store, trace)
    check(result.returncode == 0, f"the schedule exits 0: {result.stderr[-800:]!r}")
    check(bool(lines) and lines[-1].get("outcome") == "ok",
          f"the schedule reaches ok: {lines[-1] if lines else None!r}")

    prompts = requests(trace, "session/prompt")
    check(len(prompts) == 1, f"the agent is prompted once: {len(prompts)} turns")
    check(len(requests(trace, "initialize")) == 1,
          f"the service process initializes once: "
          f"{len(requests(trace, 'initialize'))}")
    check(len(requests(trace, "session/new")) == 1,
          f"and keeps one session: {len(requests(trace, 'session/new'))}")
    session_ids = {(message.get("params") or {}).get("sessionId")
                   for message in prompts}
    check(session_ids == {"sess-1"}, f"the turn runs on sess-1: {session_ids!r}")

    inits = [message for message in messages(trace)
             if message[0] == "client->agent" and message[1].get("method") == "initialize"]
    params = inits[0][1]["params"] if inits else {}
    check(params.get("protocolVersion") == 1,
          f"the client speaks ACP v1: {params.get('protocolVersion')!r}")
    capabilities = params.get("clientCapabilities") or {}
    check(capabilities.get("terminal") is False
          and (capabilities.get("fs") or {}).get("readTextFile") is False,
          f"and offers no fs / terminal: {capabilities!r}")

    for message in prompts:
        prompt_id = message["id"]
        response = responses_to(trace, prompt_id)
        check(bool(response) and (response[-1].get("result") or {}).get("stopReason")
              == "end_turn",
              f"prompt {prompt_id} ends with end_turn: {response[-1] if response else None!r}")

    check(len(requests(trace, "session/request_permission", "agent->client")) == 0,
          "a text-only turn asks for no permission")

    first = snapshot(store, "root/c1")
    check(first is not None, "the response is recorded under its call's path")
    if first is not None:
        check(stop_reason_of(first) == "end_turn",
              f"the response ends with end_turn: {stop_reason_of(first)!r}")



def _the_sources_are_documents(tmp: Path):
    """源码是两份文档；`run.py` 把每份文档的 `viba` 代码块按顺序拼成一个模块再跑。"""
    documents = (
        (ROOT / "viba_acp.viba.md",
         {"open_session", "send_prompt", "resume_session", "load_session",
          "cancel_session", "close_session", "delete_session", "archive_session",
          "unarchive_session", "set_session_title",
          "SessionId", "MessageId", "SessionNotification", "session_update_handler",
          "UserMessageChunk",
          "AgentMessageChunk", "AgentThoughtChunk", "ContentBlock",
          "TextContent", "ImageContent", "AudioContent", "ResourceLink",
          "EmbeddedResource", "TextResourceContents", "BlobResourceContents",
          "StopReason", "PromptResponse", "Usage", "Annotations", "Role"}),
        (ROOT / "demo" / "viba_acp.viba.md",
         {"声明与参数", "开会话", "提问"}),
    )
    for document, headings in documents:
        found = {line.lstrip("#").strip()
                 for line in document.read_text(encoding="utf-8").splitlines()
                 if line.startswith("## ")}
        check(found == headings,
              f"{document.name} has these sections: {sorted(found)}")

    built = tmp / "one" / "source" / "viba_acp"
    for document, name in ((ROOT / "viba_acp.viba.md", "acp.viba"),
                           (ROOT / "demo" / "viba_acp.viba.md",
                            "explain_then_shorten.viba")):
        written = built / name
        check(written.is_file(), f"the build has {name}: {written}")
        if written.is_file():
            check(written.read_text(encoding="utf-8") == module_source(document),
                  f"and it is the document's viba blocks, in order: {name}")


def _the_same_store_asks_nothing(tmp: Path):
    """Same store, no --fresh: every call is replayed, none is asked again."""
    store = tmp / "one"
    if not store.exists():
        return
    trace = tmp / "second.jsonl"
    result = subprocess.run(
        RUN + ["--store", str(store), "--trace", str(trace)],
        capture_output=True, text=True, timeout=120)
    lines = [json.loads(one) for one in result.stdout.splitlines()
             if one.strip().startswith("{")]
    check(result.returncode == 0 and lines and lines[-1].get("outcome") == "ok",
          f"the second schedule still reaches ok: {lines[-1] if lines else None!r}")
    check(len(requests(trace, "session/prompt")) == 0,
          "a recorded call is not asked again")
    rounds = [one for one in lines if "round" in one]
    computed = [note for note in (rounds[-1]["runs"]["acp"].get("api") or [])
                if note.get("computed")]
    check(not computed, f"the second run computed nothing: {computed!r}")


def _the_permission_path():
    """A turn that runs a tool: the agent asks, the client decides, the turn goes on."""
    with tempfile.TemporaryDirectory(prefix="viba-acp-permission-") as scratch:
        trace = Path(scratch) / "permission.jsonl"
        response = acp_client.run_turn(SCRIPTED_AGENT + ["--tool-call"], str(ROOT),
                                       "hello", timeout=10, trace=trace)
        check(response.stop == "end_turn" and response.text.startswith("scripted-agent:"),
              f"the turn ends with the response: {response!r}")
        permissions = requests(trace, "session/request_permission", "agent->client")
        check(len(permissions) == 1,
              f"the agent asks once before the tool: {len(permissions)}")
        for message in permissions:
            answer = responses_to(trace, message["id"], "client->agent")
            outcome = ((answer[-1].get("result") if answer else {}) or {}).get(
                "outcome") or {}
            check(outcome.get("optionId") == "reject-once",
                  f"the default policy rejects: {outcome!r}")
        updates = [message for _direction, message in messages(trace)
                   if message.get("params", {}).get("update", {}).get(
                       "sessionUpdate") == "tool_call_update"]
        check(len(updates) == 1 and updates[0]["params"]["update"]["status"] == "failed",
              f"the rejected tool call is reported failed: {updates!r}")


def _the_update_callback():
    """The client hands each session/update to the callback it was given."""
    with acp_client.Conversation(SCRIPTED_AGENT, str(ROOT)) as conversation:
        seen = []
        text, stop = conversation.prompt_blocks(
            [{"type": "text", "text": "hello"}], seen.append)
        check(stop == "end_turn" and text.startswith("scripted-agent:"),
              f"the turn still answers: {stop!r} {text!r}")
        kinds = [notice["update"].get("sessionUpdate") for notice in seen]
        check(kinds and all(kind == "agent_message_chunk" for kind in kinds),
              f"the callback sees the chunks: {kinds!r}")


def _the_client_edges():
    """The client's own edges, against the same scripted agent, by hand."""
    with tempfile.TemporaryDirectory(prefix="viba-acp-client-") as scratch:
        trace = Path(scratch) / "client.jsonl"
        response = acp_client.run_turn(SCRIPTED_AGENT, str(ROOT), "hi",
                                       timeout=5, trace=trace)
        check(response.stop == "end_turn" and response.text.startswith("scripted-agent:"),
              f"one call returns its response: {response!r}")
        check(response.agent.name == "scripted-agent",
              f"and says which agent responded: {response.agent!r}")

        hanging = SCRIPTED_AGENT + ["--mode", "hang"]
        outcome = acp_client.run_turn(hanging, str(ROOT), "hi", timeout=0.5)
        check(outcome.stop == "cancelled",
              f"a prompt past its timeout is cancelled: {outcome.stop!r}")

        unknown = SCRIPTED_AGENT + ["--stop", "paused"]
        try:
            acp_client.run_turn(unknown, str(ROOT), "hi", timeout=5)
            check(False, "a stop reason ACP does not define is refused")
        except acp_client.AcpError as problem:
            check("paused" in str(problem), f"and the error names it: {problem!r}")

        other_version = SCRIPTED_AGENT + ["--protocol", "2"]
        try:
            acp_client.run_turn(other_version, str(ROOT), "hi", timeout=5)
            check(False, "a protocol version this client does not speak is refused")
        except acp_client.AcpError as problem:
            check("protocolVersion 2" in str(problem),
                  f"and the error names the version: {problem!r}")

        dead = [sys.executable, "-c", "import sys; sys.exit(3)"]
        try:
            acp_client.run_turn(dead, str(ROOT), "hi", timeout=5)
            check(False, "an agent that dies before initialize is reported")
        except acp_client.AcpError as problem:
            check("exited with 3" in str(problem), f"and the error says so: {problem!r}")


if __name__ == "__main__":
    scratch = Path(tempfile.mkdtemp(prefix="viba-acp-"))
    try:
        run(scratch)
    finally:
        for leftover in sorted(scratch.rglob("*"), reverse=True):
            leftover.unlink() if leftover.is_file() else leftover.rmdir()
    sys.exit(checks.report())
