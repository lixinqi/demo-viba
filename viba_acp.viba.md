# viba_acp

## 需求背景

viba 程序要调用一个 ACP agent：开一个会话、提交一轮提示、必要时接回已有会话，同时能看到 agent 发回的
消息。接口要覆盖这些操作，类型要按 ACP 的 schema 命名，程序只依赖这一份文档导出的名字。

## public.viba

对外只露出这份文档导出的名字：`viba_acp.apis` 与 `viba_acp.types` 里的定义，在这里各转一次。

```viba public
import viba_acp.apis as apis
import viba_acp.types as types


open_session = apis.open_session
send_prompt = apis.send_prompt
resume_session = apis.resume_session
load_session = apis.load_session
cancel_session = apis.cancel_session
close_session = apis.close_session
delete_session = apis.delete_session
archive_session = apis.archive_session
unarchive_session = apis.unarchive_session
set_session_title = apis.set_session_title

SessionId = types.SessionId
MessageId = types.MessageId
ContentBlock = types.ContentBlock
Annotations = types.Annotations
Role = types.Role
TextContent = types.TextContent
ImageContent = types.ImageContent
AudioContent = types.AudioContent
ResourceLink = types.ResourceLink
EmbeddedResource = types.EmbeddedResource
TextResourceContents = types.TextResourceContents
BlobResourceContents = types.BlobResourceContents
StopReason = types.StopReason
PromptResponse = types.PromptResponse
Usage = types.Usage
SessionNotification = types.SessionNotification
session_update_handler = types.session_update_handler
UserMessageChunk = types.UserMessageChunk
AgentMessageChunk = types.AgentMessageChunk
AgentThoughtChunk = types.AgentThoughtChunk
```

## 基本操作

客户端→agent 的操作有十个：开会话、提交一轮、接回会话（load/resume）、取消、关闭、删除、归档与
取消归档、设置标题。它们由服务实现，参数按 ACP 的请求展开，结果按 ACP 的响应给出。

agent→客户端的通知通过 `session_update_handler` 交给调用方；当前建模三种消息块。

## apis.viba

每个操作一节；类型从 `viba_acp.types` 取。

```viba apis
import viba_acp.types as types
```

### open_session

`session/new`：开一个会话。工作目录与 MCP 服务器属于客户端的策略，由服务决定。

```viba apis
open_session =
     types.SessionId
  <- $env Env
  <- { open a new ACP session and answer its id }
```

### send_prompt

`session/prompt`：在一个会话上执行一轮。`$on_update` 在每条 `session/update` 到达时被调用，传 `nil` 表示不接收。

```viba apis
send_prompt =
     types.PromptResponse
  <- $env Env
  <- $session types.SessionId
  <- $prompt list[types.ContentBlock]
  <- $on_update Optional[types.session_update_handler]
  <- { run one prompt turn on that session, calling $on_update for each session/update, and answer its response }
```

### resume_session

`session/resume`：接上一个已有会话，不重放历史。

```viba apis
resume_session =
     void
  <- $env Env
  <- $session_id types.SessionId
  <- $cwd str
  <- { resume the session named by $session_id; the response's optional fields are not modeled, so this answers void }
```

### load_session

`session/load`：载入一个已有会话，重放它的历史。`$on_update` 接收重放出来的每条通知。

```viba apis
load_session =
     void
  <- $env Env
  <- $session_id types.SessionId
  <- $cwd str
  <- $on_update Optional[types.session_update_handler]
  <- { load the session named by $session_id, calling $on_update for each replayed session/update; the response's optional fields are not modeled, so this answers void }
```

### cancel_session

`session/cancel`：取消会话里正在进行的轮次。它是通知，没有响应。

```viba apis
cancel_session =
     void
  <- $env Env
  <- $session_id types.SessionId
  <- { cancel the turn running in the session named by $session_id }
```

### close_session

`session/close`：取消该会话正在进行的工作，并释放它的资源。

```viba apis
close_session =
     void
  <- $env Env
  <- $session_id types.SessionId
  <- { close the session named by $session_id }
```

### delete_session

`session/delete`：删除该会话。

```viba apis
delete_session =
     void
  <- $env Env
  <- $session_id types.SessionId
  <- { delete the session named by $session_id }
```

### archive_session

`session/archive`：归档该会话。

```viba apis
archive_session =
     void
  <- $env Env
  <- $session_id types.SessionId
  <- { archive the session named by $session_id }
```

### unarchive_session

`session/unarchive`：取消归档。

```viba apis
unarchive_session =
     void
  <- $env Env
  <- $session_id types.SessionId
  <- { unarchive the session named by $session_id }
```

### set_session_title

`session/set_title`：设置该会话的标题。

```viba apis
set_session_title =
     void
  <- $env Env
  <- $session_id types.SessionId
  <- $title str
  <- { set the title of the session named by $session_id }
```
## types.viba

每个类型一节。

### SessionId

ACP 的会话编号，字符串。

```viba types
SessionId = str
```

### MessageId

消息编号；同一条消息分几次送达时用它归并。

```viba types
MessageId = str
```

### ContentBlock

ACP 的内容块：文本、图片、音频、资源链接、内嵌资源五支，变体由各自的 tag 区分。

```viba types
ContentBlock =
    Oneof
  | TextContent
  | ImageContent
  | AudioContent
  | ResourceLink
  | EmbeddedResource
```

### Annotations

内容块上的注释：面向谁、最后修改时间、优先级；三项都可空。

```viba types
Annotations =
    Object
  * $audience Optional[list[Role]]
  * $last_modified Optional[str]
  * $priority Optional[float]
```

### Role

会话里的一方：`assistant` 或 `user`。

```viba types
Role =
    Oneof
  | "assistant"
  | "user"
```

### TextContent

文本块；`$text` 是正文。

```viba types
TextContent =
    tagged[__type__, Object]
  * $text str
  * $annotations Optional[Annotations]
```

### ImageContent

图片块；`$data` 是 base64 的图片数据，`$mime_type` 是媒体类型，`$uri` 可选。

```viba types
ImageContent =
    tagged[__type__, Object]
  * $data str
  * $mime_type str
  * $uri Optional[str]
  * $annotations Optional[Annotations]
```

### AudioContent

音频块；`$data` 是 base64 的音频数据，`$mime_type` 是媒体类型。

```viba types
AudioContent =
    tagged[__type__, Object]
  * $data str
  * $mime_type str
  * $annotations Optional[Annotations]
```

### ResourceLink

指向客户端资源的链接；`$name` 与 `$uri` 必填，标题、描述、媒体类型、大小可选。

```viba types
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

### EmbeddedResource

内嵌在提示里的资源；`$resource` 是文本或字节形式的内容。

```viba types
EmbeddedResource =
    tagged[__type__, Object]
  * $resource (TextResourceContents | BlobResourceContents)
  * $annotations Optional[Annotations]
```

### TextResourceContents

文本形式的资源内容。

```viba types
TextResourceContents =
    Object
  * $uri str
  * $mime_type Optional[str]
  * $text str
```

### BlobResourceContents

字节形式的资源内容；`$blob` 是 base64。

```viba types
BlobResourceContents =
    Object
  * $uri str
  * $mime_type Optional[str]
  * $blob str
```

### StopReason

一轮结束的原因，ACP v1 定义五个取值；其他取值不合法。

```viba types
StopReason =
    Oneof
  | "end_turn"
  | "max_tokens"
  | "max_turn_requests"
  | "refusal"
  | "cancelled"
```

### PromptResponse

`session/prompt` 的结果：结束原因，与可选的 token 用量。

```viba types
PromptResponse =
    Object
  * $stop_reason StopReason              # why the turn ended
  * $usage Optional[Usage]               # the tokens the turn used, when reported
```

### Usage

token 用量；总数、输入、输出必填，思考与缓存读写可选。

```viba types
Usage =
    Object
  * $total_tokens uint64_t
  * $input_tokens uint64_t
  * $output_tokens uint64_t
  * $thought_tokens Optional[uint64_t]
  * $cached_read_tokens Optional[uint64_t]
  * $cached_write_tokens Optional[uint64_t]
```

### SessionNotification

`session/update` 的通知体：会话编号，与这次更新。

```viba types
SessionNotification =
    Object
  * $session_id SessionId
  * $update (UserMessageChunk | AgentMessageChunk | AgentThoughtChunk)
```

### session_update_handler

处理一条 `SessionNotification` 的函数类型：收到通知，返回 `void`。

```viba types
session_update_handler =
     void
  <- $env Env
  <- $notification SessionNotification
```

### UserMessageChunk

用户消息的一块。

```viba types
UserMessageChunk =
    tagged[__type__, Object]
  * $content ContentBlock
  * $message_id Optional[MessageId]
```

### AgentMessageChunk

agent 消息的一块。

```viba types
AgentMessageChunk =
    tagged[__type__, Object]
  * $content ContentBlock
  * $message_id Optional[MessageId]
```

### AgentThoughtChunk

agent 思考的一块。

```viba types
AgentThoughtChunk =
    tagged[__type__, Object]
  * $content ContentBlock
  * $message_id Optional[MessageId]
```

