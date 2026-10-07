# viba_ticket —— 票据处理系统的 viba 定义与 norm 代码

这个目录有两种东西：

| 文件 | 写的是什么 |
|---|---|
| `ticket_design.viba` | 这两份数据的设计：`Ticket`（一次要跑的调用，连着它落在哪三个版本上）、`TicketStage` 与 `TicketProgress`（一张票据被处理过的每一次） |
| `two_handlers/`、`add_one/` | **norm 代码**：票据的 `$call` 要跑的 viba 代码写在这里 |

行为（轮询、执行 `$call`、追加进度、停下的条件）在 [`../ticket_system/`](../ticket_system/)
那份 python 里；这几份文件说的是那些 python 写出来的东西是**什么**，以及它跑的是哪份代码。

三样东西分清楚，这一层就不会乱：

- **解释器**：跑 viba 的 python 包。票据上 `$viba_interpreter_repo_commit_id` 说这次运行必须是哪一个；
- **norm repo**：**调用要跑的 viba 代码**所在的那个 git repo，`$norm_repo_path` 指到代码所在的那个
  目录（它可以就是这个 repo 里的一层目录），`$norm_repo_commit_id` 说读它的哪一个提交 —— 也就是那个
  repo 的提交。这个目录下面的子目录就是示例的 norm 代码；
- **角色**：一个处理进程的能力表（`{名字: 实现}`），写在 python 模块里
  （[`../demo/ticket_examples/`](../demo/ticket_examples/)）。哪个名字归哪个角色，是那个模块里的一行；
  程序里那几步（`a_add`、`b_scale`）就是宿主按名字实现的，norm repo 里只有它们的签名与提示。

一段 norm 程序就是一个普通的 viba 模块：`__decl__` 收 `$env Env` 与它自己的参数，`__impl__` 是它
答的东西。它的名字就是票据 `$call` 里那个名字（`the_program`）；它 import 的那些 api 文件只写签名与
提示，实现在角色那边。
`builtin.*` 那些算子解释器不带，由宿主补（[`../ticket_system/builtins.py`](../ticket_system/builtins.py)）。

一张票据做完了没有，读的是它这一整份进度里有没有 `$ok`：进度只增，所以「答过了」只会从没有变成
有，别的进程后来追一条停下的记录也顶不掉它（[`../viba-ticket.md`](../viba-ticket.md) 第 5 节）。

两张数据都写在文件系统上。一张票据落在它自己的目录里（`<票据路径>/<uid>/ticket.viba`），它的进度
是旁边那个目录（`<票据路径>/<uid>/progress/`）：**一次尝试一个文件**，文件名带写入时刻与处理进程的
名字。所以「只增不删」不需要锁 —— 两个进程同时追加就是两个文件，谁都不会覆盖谁。

`$time` 的类型 `datetime` 是 `datetime.isoformat()` 写下的那串文本，不是 viba 自带的一个类型：viba
里没有时钟，时刻由宿主写下来，读者只比较、只打印这串文本。`$VIBA_PATH` 是一个 `list[str]`：这次调用
找它 import 的模块时用的那些目录，盘上写的就是一个列表值（`ListLiteral["/a", "/b"]`）；把它连成
`os.pathsep` 那种写法是宿主跑之前的事（[`../ticket_system/README.md`](../ticket_system/README.md)
「两个容器成员」）。

怎么读三个版本、对不上时怎么办，见 [`../viba-ticket.md`](../viba-ticket.md) 第 3 节与
[`../ticket_system/code.py`](../ticket_system/code.py)；跑它们的套件是
[`../tests/test_ticket_system.py`](../tests/test_ticket_system.py)。

- [`two_handlers/`](two_handlers/)：一段跨两个服务的程序（`the_program.viba` 轮流调用
  `service_a` 与 `service_b` 那两个 api），两个角色各答其中一半，靠票据自己的存储回放轮流把它跑完；
  [`../viba-ticket.md`](../viba-ticket.md) 走的就是这一份。
- [`add_one/`](add_one/)：`$storage_path` 是那次调用的答案落在的地方：同一张票据被尝试第二次，
  那段 norm 代码不再进，答案从快照里回放。
