"""The service side of the `viba_acp` interface: two ACP operations over one session.

`open_session` opens the conversation this process will use and answers its session id;
`send_prompt` runs one prompt turn on it and answers the `PromptResponse`. Both go through
`service.recorded`, so every call is recorded under its storage path and a later run on
the same store replays it instead of prompting the agent again.

The conversation — one agent process, one ACP session — lives in this process and is
closed when the process exits. `SessionId` is data: it names the session the calls use.

The agent command is `AGENT`. To call another agent, replace that line; the interface,
the program and the entry do not change.
"""

import atexit
import os
import sys
from pathlib import Path

from viba import viba_ast
from viba.interpret import viba_data
from viba.reflect import VObject, VibaReflectError

import acp_client
from distributed.service import leaf_value, run_service

HERE = Path(__file__).resolve().parent    # viba_acp
WORKSPACE = HERE.parent                   # the repository root

# What this service starts. To call another agent, replace this line.
AGENT = [sys.executable, str(HERE / "scripted_agent.py")]

# One conversation per agent command, for the life of this service process.
_CONVERSATIONS = {}


def the_api(service):
    """The interface's table: the two ACP operations the module declares."""

    def open_session(environ):
        return service.recorded(environ, lambda: the_conversation().session)

    def send_prompt(environ, session, prompt_blocks, on_update):
        session = leaf_value(session)
        blocks = [the_block(block) for block in prompt_blocks]
        handler = the_handler(on_update, environ)

        def turn():
            conversation = the_conversation()
            if session != conversation.session:
                raise RuntimeError(
                    f"the request names session {session!r}, but this process "
                    f"is in {conversation.session!r}")
            return the_response(conversation, blocks, handler)

        return service.recorded(environ, turn)

    def resume_session(environ, session, cwd):
        session = leaf_value(session)
        cwd = leaf_value(cwd)

        def resume():
            the_conversation().resume_session(session, cwd)
            return viba_data(viba_ast.Nil())

        return service.recorded(environ, resume)

    def load_session(environ, session, cwd, on_update):
        session = leaf_value(session)
        cwd = leaf_value(cwd)
        handler = the_handler(on_update, environ)

        def load():
            the_conversation().load_session(session, cwd, handler)
            return viba_data(viba_ast.Nil())

        return service.recorded(environ, load)

    def cancel_session(environ, session_id):
        the_conversation().cancel_session(leaf_value(session_id))
        return viba_data(viba_ast.Nil())

    def close_session(environ, session_id):
        the_conversation().close_session(leaf_value(session_id))
        return viba_data(viba_ast.Nil())

    def delete_session(environ, session_id):
        the_conversation().delete_session(leaf_value(session_id))
        return viba_data(viba_ast.Nil())

    def archive_session(environ, session_id):
        the_conversation().archive_session(leaf_value(session_id))
        return viba_data(viba_ast.Nil())

    def unarchive_session(environ, session_id):
        the_conversation().unarchive_session(leaf_value(session_id))
        return viba_data(viba_ast.Nil())

    def set_session_title(environ, session_id, title):
        the_conversation().set_session_title(leaf_value(session_id),
                                             leaf_value(title))
        return viba_data(viba_ast.Nil())

    return {"open_session": open_session, "send_prompt": send_prompt,
            "resume_session": resume_session, "load_session": load_session,
            "cancel_session": cancel_session, "close_session": close_session,
            "delete_session": delete_session, "archive_session": archive_session,
            "unarchive_session": unarchive_session,
            "set_session_title": set_session_title}


def the_conversation():
    """The conversation this process has with that agent, made on first use."""
    key = tuple(AGENT)
    conversation = _CONVERSATIONS.get(key)
    if conversation is None:
        conversation = acp_client.Conversation(
            AGENT, WORKSPACE,
            permissions=os.environ.get("VIBA_AGENT_PERMISSION", "reject"),
            trace=the_trace())
        _CONVERSATIONS[key] = conversation
        atexit.register(conversation.close)
    return conversation


def the_block(block):
    """One viba content block as the ACP wire form."""
    annotations = the_optional(block, "$annotations")
    if the_has(block, "$TextContent"):
        piece = {"type": "text", "text": leaf_value(block.by_tag("$text"))}
        if annotations is not None:
            piece["annotations"] = the_annotations(annotations)
        return piece
    if the_has(block, "$ImageContent"):
        piece = {"type": "image",
                 "data": leaf_value(block.by_tag("$data")),
                 "mimeType": leaf_value(block.by_tag("$mime_type"))}
        uri = the_optional(block, "$uri")
        if uri is not None:
            piece["uri"] = uri
        if annotations is not None:
            piece["annotations"] = the_annotations(annotations)
        return piece
    if the_has(block, "$AudioContent"):
        piece = {"type": "audio",
                 "data": leaf_value(block.by_tag("$data")),
                 "mimeType": leaf_value(block.by_tag("$mime_type"))}
        if annotations is not None:
            piece["annotations"] = the_annotations(annotations)
        return piece
    if the_has(block, "$ResourceLink"):
        piece = {"type": "resource_link",
                 "name": leaf_value(block.by_tag("$name")),
                 "uri": leaf_value(block.by_tag("$uri"))}
        for tag, key in (("$title", "title"), ("$description", "description"),
                         ("$mime_type", "mimeType"), ("$size", "size")):
            value = the_optional(block, tag)
            if value is not None:
                piece[key] = value
        if annotations is not None:
            piece["annotations"] = the_annotations(annotations)
        return piece
    if the_has(block, "$EmbeddedResource"):
        resource = block.by_tag("$resource")
        contents = {"uri": leaf_value(resource.by_tag("$uri"))}
        mime = the_optional(resource, "$mime_type")
        if mime is not None:
            contents["mimeType"] = mime
        blob = the_optional(resource, "$blob")
        if blob is not None:
            contents["blob"] = blob
        else:
            contents["text"] = leaf_value(resource.by_tag("$text"))
        piece = {"type": "resource", "resource": contents}
        if annotations is not None:
            piece["annotations"] = the_annotations(annotations)
        return piece
    raise RuntimeError("the content block is none of the five variants")


def the_has(block, tag) -> bool:
    """Whether this piece carries the member `tag`."""
    try:
        block.by_tag(tag)
        return True
    except VibaReflectError:
        return False


def the_annotations(value):
    """One `Annotations` as the ACP wire form."""
    piece = {}
    audience = the_optional(value, "$audience")
    if audience is not None:
        piece["audience"] = [leaf_value(role) for role in audience]
    last_modified = the_optional(value, "$last_modified")
    if last_modified is not None:
        piece["lastModified"] = last_modified
    priority = the_optional(value, "$priority")
    if priority is not None:
        piece["priority"] = priority
    return piece


def the_optional(block, tag):
    """One optional member: its leaf, or None when it is nil or absent."""
    try:
        return leaf_value(block.by_tag(tag))
    except VibaReflectError:
        return None


def the_handler(on_update, environ):
    """The viba function the client calls for each `session/update`, or None."""
    if isinstance(on_update, VObject) and isinstance(on_update.data, viba_ast.Nil):
        return None

    def handler(notification):
        piece = the_notification(notification)
        if piece is not None:
            on_update(environ, piece)

    return handler


_UPDATE_TAGS = {
    "user_message_chunk": "$UserMessageChunk",
    "agent_message_chunk": "$AgentMessageChunk",
    "agent_thought_chunk": "$AgentThoughtChunk",
}


def the_notification(notification):
    """One `session/update` notification as `SessionNotification`, or None."""
    update = notification.get("update") or {}
    tag = _UPDATE_TAGS.get(update.get("sessionUpdate"))
    if tag is None:
        return None
    piece = viba_ast.ProductChain([
        viba_ast.Tagged("$session_id",
                        viba_ast.Constant(notification.get("sessionId") or "")),
        viba_ast.Tagged("$update", viba_ast.ProductChain([
            viba_ast.Tagged(tag, viba_ast.Nil()),
            viba_ast.Tagged("$content", the_content(update.get("content") or {})),
            viba_ast.Tagged("$message_id",
                            viba_ast.Constant(update["messageId"])
                            if update.get("messageId") else viba_ast.Nil()),
        ])),
    ])
    return viba_data(piece)


def the_content(value):
    """One ACP content block (as JSON) as the interface's `ContentBlock`."""
    if value.get("type") == "text":
        return viba_ast.ProductChain([
            viba_ast.Tagged("$TextContent", viba_ast.Nil()),
            viba_ast.Tagged("$text", viba_ast.Constant(value.get("text") or "")),
            viba_ast.Tagged("$annotations", viba_ast.Nil()),
        ])
    raise RuntimeError(f"content type {value.get('type')!r} is not modeled")


def the_response(conversation, blocks, on_update=None):
    """One prompt turn, as the interface's `PromptResponse`."""
    try:
        _answer, stop = conversation.prompt_blocks(blocks, on_update)
    except acp_client.AcpError:
        # The conversation cannot be trusted after a protocol error; drop it so a
        # later call starts a new one.
        _CONVERSATIONS.pop(tuple(AGENT), None)
        conversation.close()
        raise
    return viba_data(viba_ast.ProductChain([
        viba_ast.Tagged("$stop_reason", viba_ast.Constant(stop)),
        viba_ast.Tagged("$usage", viba_ast.Nil()),
    ]))


def the_trace():
    """Where the ACP messages go, when `run.py` asked for a trace."""
    return os.environ.get("VIBA_AGENT_TRACE")


def main(argv=None) -> int:
    """This service's `__main__`: serve what is owed, or run the program once."""
    return run_service("acp", the_api, argv)


if __name__ == "__main__":
    raise SystemExit(main())
