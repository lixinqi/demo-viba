# demo/viba_acp

示例程序 `explain_then_shorten.viba` 调用 `viba_acp` 的接口：建立一个会话，提交一个问题，返回响应。
程序只使用 `open_session` 与 `send_prompt`，不依赖 agent 的启动命令；服务一侧见
[`viba_acp/README.md`](../viba_acp/README.md)。

章节按步骤命名；每个 `viba` 代码块按顺序拼成 `explain_then_shorten.viba`。

## 声明与参数

```viba
import acp

__decl__ = acp.PromptResponse <- $env Env

args = __get_args__ << __decl__
```

## 开会话

会话编号是数据，提交问题时带上它。

```viba
session = acp.open_session << $env ($sub_env << args.env << "c0")
```

## 提问

一块文本，在该会话上执行一轮；`__impl__` 是本轮的响应。

```viba
question =
    $TextContent nil
  * $text "Explain in one sentence what a type class is."

__impl__ =
     acp.send_prompt << $env ($sub_env << args.env << "c1")
  << $session session
  << $prompt (ListLiteral[question])
  << $on_update nil
```
