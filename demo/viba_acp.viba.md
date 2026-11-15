# demo/viba_acp

这个示例用 `viba_acp` 的客户端接口调用一个 agent：开一个会话，提一个问题，拿回响应。

## explain_then_shorten.viba

```viba
import viba_acp.public as public

__decl__ = public.PromptResponse <- $env Env

args = __get_args__ << __decl__

session = public.open_session << $env ($sub_env << args.env << "c0")

question =
    $TextContent nil
  * $text "Explain in one sentence what a type class is."

__impl__ =
     public.send_prompt << $env ($sub_env << args.env << "c1")
  << $session session
  << $prompt (ListLiteral[question])
  << $on_update nil
```
