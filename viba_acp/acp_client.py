"""One ACP client over stdio: launch an agent, send it one prompt, take the response.

The protocol this file speaks is ACP v1
(https://agentclientprotocol.com/protocol/v1/overview): JSON-RPC 2.0 messages, one per
line, over the agent's stdin and stdout (the stdio transport,
https://agentclientprotocol.com/protocol/v1/transports).

    client -> agent   initialize                  protocol version and capabilities
                      session/new                 cwd, no MCP servers
                      session/prompt              one text content block
    agent -> client   session/update              notifications: agent_message_chunk ...
                      session/request_permission  a request: this side responds to it
                      (session/prompt result)     stopReason

    client -> agent   session/cancel              a notification, sent when the prompt
                                                  outlives its timeout

This client advertises no `fs` and no `terminal` capability, so the agent may not ask
this process to read or write files, or to run a command. It responds to permission
requests by policy: nobody is sitting in front of this process to be asked, so the
default is to reject. `permissions="allow"` is the caller saying it has decided, for
this whole run, that the agent may go ahead.

One `Conversation` is one agent process and one ACP session: `initialize` and
`session/new` happen once, and every `prompt` is one more turn on that session.
`run_turn` is the one-shot form, for trying an agent by hand.

    python3 viba_acp/scripted_agent.py     # the scripted agent used by the demo
"""

import json
import os
import queue
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field

PROTOCOL_VERSION = 1

# ACP v1 `StopReason`: the only values a `session/prompt` response may carry.
STOP_REASONS = ("end_turn", "max_tokens", "max_turn_requests", "refusal", "cancelled")

# How long one `session/prompt` may take. The scheduler kills a service process after
# 60 s, so a prompt gives up (and cancels) before that, and the step can still complete.
DEFAULT_TIMEOUT = float(os.environ.get("VIBA_AGENT_TIMEOUT", "30"))

# After `session/cancel`, how long to wait for the agent to say `cancelled`.
CANCEL_GRACE = 5.0

# How much agent stderr to keep for error messages.
STDERR_LINES = 40


class AcpError(RuntimeError):
    """The agent side of the wire broke the contract, or went away."""


class _TimedOut(Exception):
    """One wait expired; the caller decides what to do about it."""


@dataclass
class AgentInfo:
    """What the agent called itself in its `initialize` response."""

    name: str = ""
    title: str = ""
    version: str = ""


@dataclass
class Response:
    """What one call to an agent produced."""

    text: str
    session: str
    stop: str
    agent: AgentInfo
    updates: int = 0
    permissions: list = field(default_factory=list)


class _Trace:
    """One JSON line per message, in the order they crossed the wire.

    The demo writes this file so that a person can see the call without reading the
    client; the suite reads it to check the same thing.
    """

    def __init__(self, path):
        self.path = path
        self._file = open(path, "a", encoding="utf-8") if path else None

    def record(self, direction: str, message) -> None:
        if self._file is None:
            return
        self._file.write(json.dumps({"dir": direction, "message": message},
                                    ensure_ascii=False) + "\n")
        self._file.flush()

    def close(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None


class Client:
    """One connection: the agent subprocess, the messages, and the policy."""

    def __init__(self, command, cwd, *, permissions="reject", timeout=None, trace=None):
        if permissions not in ("reject", "allow"):
            raise ValueError(f"permissions is 'reject' or 'allow', not {permissions!r}")
        self.command = [str(one) for one in command]
        self.cwd = str(cwd)
        self.permissions = permissions
        self.timeout = DEFAULT_TIMEOUT if timeout is None else float(timeout)
        self.trace = _Trace(trace)
        self.agent_info = AgentInfo()
        self.decisions = []
        self._incoming = queue.Queue()
        self._responses = {}
        self._next_id = 0
        self._text = []
        self._updates = 0
        self._on_update = None
        self._stderr = []
        self._process = subprocess.Popen(
            self.command, cwd=self.cwd,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", bufsize=1)
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()

    # ---- the three calls this client makes ----

    def initialize(self) -> dict:
        """`initialize`: say what this client is and which version it speaks."""
        result = self.request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "clientCapabilities": {
                "fs": {"readTextFile": False, "writeTextFile": False},
                "terminal": False,
            },
            "clientInfo": {"name": "viba_acp", "title": "the viba ACP demo",
                           "version": "1"},
        })
        version = result.get("protocolVersion")
        if version != PROTOCOL_VERSION:
            raise AcpError(f"the agent reported protocolVersion {version!r}; "
                           f"this client speaks {PROTOCOL_VERSION}")
        info = result.get("agentInfo") or {}
        self.agent_info = AgentInfo(
            name=str(info.get("name") or ""),
            title=str(info.get("title") or ""),
            version=str(info.get("version") or ""))
        return result

    def new_session(self) -> str:
        """`session/new`: one conversation, at the working directory this side gives."""
        result = self.request("session/new", {"cwd": self.cwd, "mcpServers": []})
        session = result.get("sessionId")
        if not isinstance(session, str) or not session:
            raise AcpError("session/new reported no sessionId")
        return session

    def prompt(self, session: str, blocks: list, on_update=None) -> tuple:
        """`session/prompt`: content blocks in, the chunks and the stop reason out.

        Each block is one ACP content block, already in the wire form
        (`{"type": "text", "text": …}`). The response's text is the
        `agent_message_chunk` notifications joined in the order they arrived; every
        other update (tool calls, plans, thoughts) is counted and left out.
        """
        self._text = []
        self._updates = 0
        self._on_update = on_update
        self._next_id += 1
        message_id = self._next_id
        self._send({"jsonrpc": "2.0", "id": message_id, "method": "session/prompt",
                    "params": {"sessionId": session, "prompt": blocks}})
        try:
            result = self._response_to(message_id)
        except _TimedOut:
            result = self._cancel_the_prompt(message_id, session)
        finally:
            self._on_update = None
        stop = result.get("stopReason")
        if stop not in STOP_REASONS:
            raise AcpError(f"the agent stopped with {stop!r}, "
                           f"which is not an ACP stop reason")
        return "".join(self._text), stop

    def resume_session(self, session: str, cwd: str) -> None:
        """`session/resume`: reconnect to a session the agent already has."""
        self.request("session/resume", {"sessionId": session, "cwd": cwd,
                                        "mcpServers": []})

    def load_session(self, session: str, cwd: str, on_update=None) -> None:
        """`session/load`: reconnect to a session, replaying its history.

        The agent sends the history as `session/update` notifications before the
        response; `on_update`, when given, is called with each of them.
        """
        self._on_update = on_update
        try:
            self.request("session/load", {"sessionId": session, "cwd": cwd,
                                          "mcpServers": []})
        finally:
            self._on_update = None

    def cancel_session(self, session: str) -> None:
        """`session/cancel`: a notification, not a request."""
        self.notify("session/cancel", {"sessionId": session})

    def close_session(self, session: str) -> None:
        self.request("session/close", {"sessionId": session})

    def delete_session(self, session: str) -> None:
        self.request("session/delete", {"sessionId": session})

    def archive_session(self, session: str) -> None:
        self.request("session/archive", {"sessionId": session})

    def unarchive_session(self, session: str) -> None:
        self.request("session/unarchive", {"sessionId": session})

    def set_session_title(self, session: str, title: str) -> None:
        self.request("session/set_title", {"sessionId": session, "title": title})

    # ---- the wire ----

    def notify(self, method: str, params: dict) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def request(self, method: str, params: dict, timeout=None) -> dict:
        self._next_id += 1
        message_id = self._next_id
        self._send({"jsonrpc": "2.0", "id": message_id, "method": method,
                    "params": params})
        return self._response_to(message_id, timeout)

    def _response_to(self, message_id: int, timeout=None) -> dict:
        """Wait for this request's response, serving the agent's traffic meanwhile."""
        deadline = time.monotonic() + (self.timeout if timeout is None else timeout)
        while True:
            if message_id in self._responses:
                message = self._responses.pop(message_id)
                if "error" in message:
                    error = message.get("error") or {}
                    raise AcpError(f"the agent refused {message.get('id')}: "
                                   f"{error.get('message')} "
                                   f"(code {error.get('code')})")
                return message.get("result") or {}
            message = self._next(deadline)
            if "method" in message:
                if "id" in message:
                    self._respond(message)
                else:
                    self._note(message)
            elif "id" in message:
                self._responses[message["id"]] = message

    def _next(self, deadline: float) -> dict:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise _TimedOut()
        try:
            kind, payload = self._incoming.get(timeout=remaining)
        except queue.Empty:
            raise _TimedOut() from None
        if kind == "error":
            raise payload
        if kind == "eof":
            raise AcpError(self._why_it_ended())
        return payload

    def _send(self, message) -> None:
        self.trace.record("client->agent", message)
        line = json.dumps(message, ensure_ascii=False) + "\n"
        try:
            self._process.stdin.write(line)
            self._process.stdin.flush()
        except (BrokenPipeError, ValueError) as problem:
            raise AcpError(f"the agent stopped reading its stdin ({problem}); "
                           f"{self._why_it_ended()}") from problem

    def _cancel_the_prompt(self, message_id: int, session: str) -> dict:
        """The prompt outlived its timeout: cancel it and take the stop reason.

        ACP says the agent must answer the prompt with `cancelled` after
        `session/cancel`, so this is a wait for that response, not a failure yet.
        """
        self._send({"jsonrpc": "2.0", "method": "session/cancel",
                    "params": {"sessionId": session}})
        try:
            return self._response_to(message_id, CANCEL_GRACE)
        except _TimedOut:
            raise AcpError(f"the agent neither finished within {self.timeout:g} s "
                           f"nor stopped after session/cancel") from None

    # ---- what arrives from the agent ----

    def _note(self, message) -> None:
        """A notification: the response being streamed, tool calls, plans."""
        if message.get("method") != "session/update":
            return
        update = (message.get("params") or {}).get("update") or {}
        self._updates += 1
        if self._on_update is not None:
            self._on_update(message.get("params") or {})
        if update.get("sessionUpdate") != "agent_message_chunk":
            return
        content = update.get("content") or {}
        if content.get("type") == "text":
            self._text.append(content.get("text") or "")

    def _respond(self, message) -> None:
        """A request from the agent: permission, or a capability this side lacks."""
        method = message.get("method")
        if method == "session/request_permission":
            result = self._permission(message.get("params") or {})
            self._send({"jsonrpc": "2.0", "id": message["id"], "result": result})
            return
        self._send({"jsonrpc": "2.0", "id": message["id"],
                    "error": {"code": -32601,
                              "message": f"{method} is not offered by this client"}})

    def _permission(self, params: dict) -> dict:
        """Response one permission request by policy, never by asking a person.

        `reject` picks the agent's own `reject_once` (or `reject_always`) option;
        `allow` picks `allow_once` (or `allow_always`). With neither on offer the
        decision is `cancelled`, which ACP defines as "no decision was made".
        """
        tool = (params.get("toolCall") or {}).get("toolCallId") or ""
        options = params.get("options") or []
        wanted = (("reject_once", "reject_always") if self.permissions == "reject"
                  else ("allow_once", "allow_always"))
        chosen = next((one for kind in wanted for one in options
                       if one.get("kind") == kind), None)
        if chosen is None:
            self.decisions.append({"tool": tool, "kind": "cancelled"})
            return {"outcome": {"outcome": "cancelled"}}
        self.decisions.append({"tool": tool, "kind": chosen["kind"]})
        return {"outcome": {"outcome": "selected", "optionId": chosen["optionId"]}}

    # ---- the two threads that read the agent's output ----

    def _read_stdout(self) -> None:
        try:
            for line in self._process.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    message = json.loads(line)
                except json.JSONDecodeError as problem:
                    self._incoming.put((
                        "error",
                        AcpError(f"the agent wrote a line that is not JSON "
                                 f"({problem}): {line[:200]}")))
                    return
                self.trace.record("agent->client", message)
                self._incoming.put(("message", message))
        finally:
            self._incoming.put(("eof", None))

    def _read_stderr(self) -> None:
        for line in self._process.stderr:
            self._stderr.append(line.rstrip("\n"))
            del self._stderr[:-STDERR_LINES]

    def _why_it_ended(self) -> str:
        code = self._process.poll()
        where = (f"the agent exited with {code}" if code is not None
                 else "the agent closed its stdout")
        if self._stderr:
            return f"{where}; its stderr ends: {self._stderr[-1]}"
        return where

    # ---- shutting the subprocess down ----

    def close(self) -> None:
        """Close the agent's stdin, and make sure the process is gone."""
        if self._process.poll() is None:
            try:
                self._process.stdin.close()
            except OSError:
                pass
            try:
                self._process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._process.terminate()
                try:
                    self._process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self._process.kill()
                    self._process.wait()
        self.trace.close()

    def __enter__(self):
        return self

    def __exit__(self, *_problem):
        self.close()


class Conversation:
    """One agent process, one ACP session, and as many prompt turns as needed.

    ACP is a session protocol: `initialize` and `session/new` happen once, and each
    turn is one `session/prompt` on that session. The agent's context and tool state
    therefore carry from one turn to the next.
    """

    def __init__(self, command, cwd, *, permissions="reject", timeout=None,
                 trace=None):
        self.client = Client(command, cwd, permissions=permissions,
                             timeout=timeout, trace=trace)
        self.client.initialize()
        self.session = self.client.new_session()

    @property
    def agent(self) -> AgentInfo:
        return self.client.agent_info

    def prompt(self, text: str) -> tuple:
        """One more turn on this session: one text block in, the response out."""
        return self.prompt_blocks([{"type": "text", "text": text}])

    def prompt_blocks(self, blocks: list, on_update=None) -> tuple:
        """One more turn on this session: content blocks in, the response out."""
        return self.client.prompt(self.session, blocks, on_update)

    def resume_session(self, session: str, cwd: str) -> None:
        """`session/resume`: reconnect to a session the agent already has."""
        self.client.resume_session(session, cwd)

    def load_session(self, session: str, cwd: str, on_update=None) -> None:
        """`session/load`: reconnect to a session, replaying its history."""
        self.client.load_session(session, cwd, on_update)

    def cancel_session(self, session: str) -> None:
        self.client.cancel_session(session)

    def close_session(self, session: str) -> None:
        self.client.close_session(session)

    def delete_session(self, session: str) -> None:
        self.client.delete_session(session)

    def archive_session(self, session: str) -> None:
        self.client.archive_session(session)

    def unarchive_session(self, session: str) -> None:
        self.client.unarchive_session(session)

    def set_session_title(self, session: str, title: str) -> None:
        self.client.set_session_title(session, title)

    def close(self) -> None:
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *_problem):
        self.close()


def run_turn(command, cwd, prompt: str, *, permissions="reject", timeout=None,
        trace=None) -> Response:
    """One call to an agent: `initialize`, one session, one prompt, close."""
    client = Client(command, cwd, permissions=permissions, timeout=timeout,
                    trace=trace)
    try:
        client.initialize()
        session = client.new_session()
        text, stop = client.prompt(session, [{"type": "text", "text": prompt}])
        return Response(text=text, session=session, stop=stop,
                      agent=client.agent_info, updates=client._updates,
                      permissions=list(client.decisions))
    finally:
        client.close()


def main(argv=None) -> int:
    """Try the client on an agent by hand: send one prompt and print the response."""
    import argparse
    parser = argparse.ArgumentParser(
        description="send one ACP agent one prompt")
    parser.add_argument("--agent", required=True,
                        help="the command that starts the agent, as one string")
    parser.add_argument("--cwd", default=os.getcwd())
    parser.add_argument("--trace", default=None)
    parser.add_argument("--permission", choices=("reject", "allow"), default="reject")
    parser.add_argument("question")
    options = parser.parse_args(argv)
    response = run_turn(options.agent.split(), options.cwd, options.question,
                 permissions=options.permission, trace=options.trace)
    print(json.dumps({"text": response.text, "session": response.session,
                      "stop": response.stop,
                      "agent": vars(response.agent)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
