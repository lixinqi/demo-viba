# viba_acp

模块 `acp.viba` 是 viba 调用 ACP agent 的客户端接口，由会话操作与 ACP 的类型组成。章节名即定义名；每个
`viba` 代码块按顺序拼成 `acp.viba`，章节标题与说明不进入文件。

ACP 是客户端与 agent 之间的会话协议。客户端启动 agent 进程；`session/new` 建立一个会话，
`session/load` 与 `session/resume` 接上已有会话，`session/prompt` 在该会话上执行一轮。

`PromptResponse` 由 `StopReason` 与 agent 的文本组成。这些操作由服务实现；工作目录与 MCP 服务器属于客户端的策略，由服务决定。会话保存在服务进程内，
`SessionId` 是它在数据中的编号。

# 需求背景

viba 程序要调用一个 ACP agent：开一个会话、提交一轮提示、必要时接回已有会话，同时能看到 agent 发回的
消息。接口要覆盖这些操作，类型要按 ACP 的 schema 命名，程序只依赖这一份文档导出的名字。

# public.viba

## open_session

`session/new` 的函数类型与服务实现。

```viba
open_session =
     SessionId
  <- $env Env
  <- { open a new ACP session and answer its id }
```

## send_prompt

`session/prompt` 的函数类型与服务实现。ACP 的响应只有 `stopReason`；agent 的文本由
`session/update` 的 `agent_message_chunk` 流式送达，`send_prompt` 按到达顺序拼接后放进 `$text`。
`$on_update` 在每条 `session/update` 到达时被调用，参数是这条通知；传 `nil` 表示不接收。

```viba
send_prompt =
     PromptResponse
  <- $env Env
  <- $session SessionId
  <- $prompt list[ContentBlock]
  <- $on_update Optional[session_update_handler]
  <- { run one prompt turn on that session, calling $on_update for each session/update, and answer its response }
```

## resume_session

`session/resume` 的函数类型与服务实现：接上一个已有会话，不重放历史。参数是会话编号与工作目录。

```viba
resume_session =
     void
  <- $env Env
  <- $session_id SessionId
  <- $cwd str
  <- { resume the session named by $session_id; the response's optional fields are not modeled, so this answers void }
```

## load_session

`session/load` 的函数类型与服务实现：载入一个已有会话，重放它的历史。参数是会话编号与工作目录；ACP 的
`mcpServers` 未建模，客户端发空列表。`$on_update` 在每条重放的 `session/update` 到达时被调用，参数与
`send_prompt` 的相同；传 `nil` 表示不接收。

```viba
load_session =
     void
  <- $env Env
  <- $session_id SessionId
  <- $cwd str
  <- $on_update Optional[session_update_handler]
  <- { load the session named by $session_id, calling $on_update for each replayed session/update; the response's optional fields are not modeled, so this answers void }
```

## cancel_session

`session/cancel`：取消会话里正在进行的轮次。它是通知，没有响应。

```viba
cancel_session =
     void
  <- $env Env
  <- $session_id SessionId
  <- { cancel the turn running in the session named by $session_id }
```

## close_session

`session/close`：取消该会话正在进行的工作，并释放它的资源。

```viba
close_session =
     void
  <- $env Env
  <- $session_id SessionId
  <- { close the session named by $session_id }
```

## delete_session

`session/delete`：删除该会话。

```viba
delete_session =
     void
  <- $env Env
  <- $session_id SessionId
  <- { delete the session named by $session_id }
```

## archive_session

`session/archive`：归档该会话。

```viba
archive_session =
     void
  <- $env Env
  <- $session_id SessionId
  <- { archive the session named by $session_id }
```

## unarchive_session

`session/unarchive`：取消归档。

```viba
unarchive_session =
     void
  <- $env Env
  <- $session_id SessionId
  <- { unarchive the session named by $session_id }
```

## set_session_title

`session/set_title`：设置该会话的标题。

```viba
set_session_title =
     void
  <- $env Env
  <- $session_id SessionId
  <- $title str
  <- { set the title of the session named by $session_id }
```

# types.viba

## SessionId

ACP 的会话编号。

```viba
SessionId = str
```

## MessageId

消息编号。

```viba
MessageId = str
```

## ContentBlock

ACP 的内容块：文本、图片、音频、资源链接与内嵌资源。五个变体以各自的 tag 区分。

```viba
ContentBlock =
    Oneof
  | TextContent
  | ImageContent
  | AudioContent
  | ResourceLink
  | EmbeddedResource
```

## Annotations

内容块上的注释：面向谁、优先级、最后修改时间。

```viba
Annotations =
    Object
  * $audience Optional[list[Role]]
  * $last_modified Optional[str]
  * $priority Optional[float]
```

## Role

会话里的一方。

```viba
Role =
    Oneof
  | "assistant"
  | "user"
```

## TextContent

纯文本。

```viba
TextContent =
    tagged[__type__, Object]
  * $text str
  * $annotations Optional[Annotations]
```

## ImageContent

图片；`$data` 是 base64。

```viba
ImageContent =
    tagged[__type__, Object]
  * $data str
  * $mime_type str
  * $uri Optional[str]
  * $annotations Optional[Annotations]
```

## AudioContent

音频；`$data` 是 base64。

```viba
AudioContent =
    tagged[__type__, Object]
  * $data str
  * $mime_type str
  * $annotations Optional[Annotations]
```

## ResourceLink

指向客户端资源的链接。

```viba
ResourceLink =
    tagged[__type__, Object]
  * $name str
  * $uri str
  * $title Optional[str]
  * $description Optional[str]
  * $mime_type Optional[str]
  * $size Optional[int64_t]
  * $annotations Optional[Annotations]
```

## EmbeddedResource

内嵌在提示里的资源；内容要么是文本，要么是 base64 字节。

```viba
EmbeddedResource =
    tagged[__type__, Object]
  * $resource (TextResourceContents | BlobResourceContents)
  * $annotations Optional[Annotations]
```

## TextResourceContents

文本形式的资源内容。

```viba
TextResourceContents =
    Object
  * $uri str
  * $mime_type Optional[str]
  * $text str
```

## BlobResourceContents

字节形式的资源内容；`$blob` 是 base64。

```viba
BlobResourceContents =
    Object
  * $uri str
  * $mime_type Optional[str]
  * $blob str
```

## StopReason

一轮结束的原因，ACP v1 定义五个取值。其他取值不属于 ACP，实现遇到时报告错误，不作为响应接受。

```viba
StopReason =
    Oneof
  | "end_turn"
  | "max_tokens"
  | "max_turn_requests"
  | "refusal"
  | "cancelled"
```

## PromptResponse

`session/prompt` 的结果：结束原因，与可选的 token 用量。

```viba
PromptResponse =
    Object
  * $stop_reason StopReason              # why the turn ended
  * $usage Optional[Usage]               # the tokens the turn used, when reported
```

## Usage

`PromptResponse` 里的 token 用量；三个总数必填，其余可选。

```viba
Usage =
    Object
  * $total_tokens uint64_t
  * $input_tokens uint64_t
  * $output_tokens uint64_t
  * $thought_tokens Optional[uint64_t]
  * $cached_read_tokens Optional[uint64_t]
  * $cached_write_tokens Optional[uint64_t]
```

# 基本操作

客户端→agent 的操作有十三个：开会话、提交一轮、接回会话（load/resume）、取消、关闭、删除、归档与
取消归档、设置标题。它们由服务实现，参数按 ACP 的请求展开，结果按 ACP 的响应给出。

agent→客户端的通知通过 `session_update_handler` 交给调用方；当前建模三种消息块。

# apis.viba

## SessionNotification

`session/update` 的通知体：会话编号，与这次更新。更新当前建模三种消息块：用户消息、agent 消息、
agent 思考；工具调用、计划、模式与配置变更等其余变体不在接口内，客户端不把它们交给 `$on_update`。

```viba
SessionNotification =
    Object
  * $session_id SessionId
  * $update (UserMessageChunk | AgentMessageChunk | AgentThoughtChunk)
```

## session_update_handler

处理一条 `SessionNotification` 的函数类型：收到通知，返回 `void`。

```viba
session_update_handler =
     void
  <- $env Env
  <- $notification SessionNotification
```

## UserMessageChunk

用户消息的一块。

```viba
UserMessageChunk =
    tagged[__type__, Object]
  * $content ContentBlock
  * $message_id Optional[MessageId]
```

## AgentMessageChunk

agent 消息的一块。

```viba
AgentMessageChunk =
    tagged[__type__, Object]
  * $content ContentBlock
  * $message_id Optional[MessageId]
```

## AgentThoughtChunk

agent 思考的一块。

```viba
AgentThoughtChunk =
    tagged[__type__, Object]
  * $content ContentBlock
  * $message_id Optional[MessageId]
```
