"""A scripted ACP agent: the agent side of the wire, with no model behind it.

`acp_client.py` is the client side; this file is what it talks to in the demo and in
the suite. It serves the three calls a client makes, and while serving a prompt it
runs the same tool-and-permission dance a real agent runs, so the client is exercised
the way it would be against one:

    session/update            tool_call
    session/request_permission
    <the client's decision>
    session/update            tool_call_update
    session/update            agent_message_chunk   (twice)
    <the prompt's response>   stopReason

The response is the prompt with its whitespace collapsed: the same prompt always gets
the same response, which is what the demo's suite asserts.

    python3 viba_acp/scripted_agent.py            # speak ACP on stdin/stdout
    python3 viba_acp/scripted_agent.py --mode hang --stop cancelled

`--mode hang` never responds to a prompt until `session/cancel` arrives: that is how the
client's timeout path is exercised. `--stop` makes the prompt response carry another
stop reason, to check that the client refuses a reason ACP does not define. `--protocol`
reports another version in `initialize`, to check that the client refuses that too.
`--tool-call` makes each turn run one tool call and ask the client to authorize it;
without it a turn is text only, which is the demo's default.
"""

import argparse
import json
import sys


def send(message) -> None:
    """One ACP message, one line: the stdio transport's whole framing."""
    sys.stdout.write(json.dumps(message, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def respond(message_id, result) -> None:
    send({"jsonrpc": "2.0", "id": message_id, "result": result})


def fail(message_id, code, text) -> None:
    send({"jsonrpc": "2.0", "id": message_id, "error": {"code": code, "message": text}})


class Agent:
    """One scripted agent process: the sessions it has, the prompt it is on."""

    def __init__(self, name, mode, stop, protocol, tool_call):
        self.name = name
        self.mode = mode
        self.stop = stop
        self.protocol = protocol
        self.tool_call = tool_call
        self.sessions = 0
        self.next_request = 1000
        self.pending = None

    # ---- what the client sends ----

    def handle(self, message) -> None:
        method = message.get("method")
        if method is None:
            self._decision(message)
        elif method == "initialize":
            self._initialize(message)
        elif method == "session/new":
            self._new_session(message)
        elif method == "session/prompt":
            self._prompt(message)
        elif method == "session/cancel":
            self._cancel()
        else:
            fail(message.get("id"), -32601, f"{method} is not a method of this agent")

    def _initialize(self, message) -> None:
        respond(message["id"], {
            "protocolVersion": self.protocol,
            "agentCapabilities": {},
            "agentInfo": {"name": self.name, "title": "a scripted ACP agent",
                          "version": "1"},
            "authMethods": [],
        })

    def _new_session(self, message) -> None:
        self.sessions += 1
        respond(message["id"], {"sessionId": f"sess-{self.sessions}"})

    def _prompt(self, message) -> None:
        params = message.get("params") or {}
        text = "".join(block.get("text") or "" for block in params.get("prompt") or []
                       if block.get("type") == "text")
        if self.mode == "hang":
            # The question is on the table; the agent just does not get to it. The
            # client's `session/cancel` is what ends this turn.
            self.pending = {"id": message["id"], "session": params.get("sessionId"),
                            "text": text, "permission": None}
            return
        self.pending = {"id": message["id"], "session": params.get("sessionId"),
                        "text": text, "permission": None}
        if not self.tool_call:
            # No tool in this turn: stream the response and end the turn.
            self._finish(allowed=True)
            return
        send({"jsonrpc": "2.0", "method": "session/update", "params": {
            "sessionId": params.get("sessionId"),
            "update": {"sessionUpdate": "tool_call", "toolCallId": "call-1",
                       "title": "look up the workspace", "kind": "read",
                       "status": "pending"}}})
        self.next_request += 1
        self.pending["permission"] = self.next_request
        send({"jsonrpc": "2.0", "id": self.next_request,
              "method": "session/request_permission",
              "params": {"sessionId": params.get("sessionId"),
                         "toolCall": {"toolCallId": "call-1"},
                         "options": [
                             {"optionId": "allow-once", "name": "Allow once",
                              "kind": "allow_once"},
                             {"optionId": "reject-once", "name": "Reject",
                              "kind": "reject_once"}]}})

    def _decision(self, message) -> None:
        """The client's decision on our permission request."""
        if self.pending is None or message.get("id") != self.pending["permission"]:
            return
        outcome = (message.get("result") or {}).get("outcome") or {}
        allowed = (outcome.get("outcome") == "selected"
                   and str(outcome.get("optionId") or "").startswith("allow"))
        self._finish(allowed)

    def _cancel(self) -> None:
        if self.pending is None:
            return
        pending, self.pending = self.pending, None
        if self.tool_call:
            send({"jsonrpc": "2.0", "method": "session/update", "params": {
                "sessionId": pending["session"],
                "update": {"sessionUpdate": "tool_call_update", "toolCallId": "call-1",
                           "status": "cancelled"}}})
        respond(pending["id"], {"stopReason": "cancelled"})

    def _finish(self, allowed: bool) -> None:
        pending, self.pending = self.pending, None
        if self.tool_call:
            send({"jsonrpc": "2.0", "method": "session/update", "params": {
                "sessionId": pending["session"],
                "update": {"sessionUpdate": "tool_call_update", "toolCallId": "call-1",
                           "status": "completed" if allowed else "failed",
                           "content": [{"type": "content", "content": {
                               "type": "text",
                               "text": ("the tool ran" if allowed
                                        else "the tool did not run: no permission")}}]}}})
        response = f"{self.name}: {' '.join(pending['text'].split())}"
        middle = len(response) // 2
        for chunk in (response[:middle], response[middle:]):
            send({"jsonrpc": "2.0", "method": "session/update", "params": {
                "sessionId": pending["session"],
                "update": {"sessionUpdate": "agent_message_chunk",
                           "content": {"type": "text", "text": chunk}}}})
        respond(pending["id"], {"stopReason": self.stop})


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="a scripted ACP agent")
    parser.add_argument("--name", default="scripted-agent")
    parser.add_argument("--mode", choices=("normal", "hang"), default="normal",
                        help="hang: wait for session/cancel before answering")
    parser.add_argument("--stop", default="end_turn",
                        help="the stopReason a prompt response carries")
    parser.add_argument("--protocol", type=int, default=1,
                        help="the protocol version to report in `initialize`")
    parser.add_argument("--tool-call", action="store_true",
                        help="run one tool call per turn, and ask the client to "
                             "authorize it")
    options = parser.parse_args(argv)
    agent = Agent(options.name, options.mode, options.stop, options.protocol,
                  options.tool_call)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            # Not an ACP message: the client broke the transport, so there is nobody
            # to answer. Say so on stderr and stop.
            print(f"not an ACP message: {line[:200]}", file=sys.stderr, flush=True)
            return 2
        agent.handle(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
