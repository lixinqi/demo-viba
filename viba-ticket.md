# 票据处理系统

一批调用写在文件系统上，一批普通进程各按自己的角色去接。这个系统里没有派活的人，也没有等人的人：
一张票据就是一个文件，谁写下来就是谁的；一个角色做完一张就在票据旁边追加一篇记录。谁去干、干到
哪了，都从这两个目录里读得出来。

一套 python 在 [`ticket_system/`](ticket_system/)：命令、盘上的布局、`$VIBA_PATH` 与
`$handler_name2api_repo_commit_id` 这两个容器成员怎么写怎么读、几个进程怎么轮流推进同一张票据，
都在那份 [`ticket_system/README.md`](ticket_system/README.md) 里。票据与进度的 viba 定义在
[`viba_ticket/ticket_design.viba`](viba_ticket/ticket_design.viba)（票据与进度都在里面）；跑得通的例子是
[`viba_ticket/two_handlers/`](viba_ticket/two_handlers/)（一段跨两个服务的程序、两个角色）与
[`viba_ticket/add_one/`](viba_ticket/add_one/)（票据的存储）；角色模块在
[`demo/ticket_examples/`](demo/ticket_examples/)；套件是
[`tests/test_ticket_system.py`](tests/test_ticket_system.py)。

这一层里有三个词，后面一直用：

- **解释器**（viba interpreter repo）：读 viba、跑 viba 的那份 python 包。一个处理进程只跑一个
  解释器，票据上 `$viba_interpreter_repo_commit_id` 写的就是它必须是的那个提交；
- **norm repo**：一次调用要跑的 viba 代码在哪个 git repo、哪一个提交上。票据上 `$norm_repo_path` 指到
  代码所在的那个目录（它可以是这个 repo 里的一层，比如 `viba_ticket/two_handlers/`），`$norm_repo_commit_id`
  就是那个 repo 的提交；解释器按那个提交读它；
- **角色**（role）：一个处理进程的本事 —— 一张 `{名字: 实现}` 的能力表，写在自己的 python 模块里。
  哪个名字归哪个角色，是那个模块里的一行。

`TicketStage` 的 `$handler_name` 两种名字都写得下：ai agent 的名字，或者普通进程的名字。这一章讲的
都是后者 —— 这一层不引入任何 ai agent。

## 1. 一张票据是一次要跑的调用

票据就是一个 viba 数据，一个定义 `value`，装在它自己的目录里
（`<票据目录>/<uid>/ticket.viba`）：

```viba
value =
  Object
  * $ticket_uid "t1"
  * $viba_interpreter_repo_commit_id "feaea3794d777d793183893cc3f5845944e601f1"
  * $viba_interpreter_repo_path "/home/viba"
  * $VIBA_PATH ListLiteral["/home/norm", "/home/viba"]
  * $norm_repo_commit_id "88be2c1cd52118c6508b79766c19b3db3030eec4"
  * $norm_repo_path "/home/norm"
  * $call (__dyn_call__ << "the_program" << 1)
  * $storage_path "/var/tickets/storage/t1"
  * $handler_name2api_repo_commit_id DictLiteral[("a", "36d82da50193f1e538473b19a858ab4afeb9af73")]
  * $time "2024-01-02T03:04:05+00:00"
```

它的类型就是这一层说的第一样东西（[`viba_ticket/ticket_design.viba`](viba_ticket/ticket_design.viba)）：

```viba
Ticket =
    Object
  * $ticket_uid str
  * $viba_interpreter_repo_commit_id str
  * $viba_interpreter_repo_path str
  * $VIBA_PATH list[str]
  * $norm_repo_commit_id str
  * $norm_repo_path str
  * $call (Any <- Env)
  * $storage_path str
  * $handler_name2api_repo_commit_id dict[str, str]
  * $time datetime
```

`$call` 是 viba 里那种**能再跑一次**的形式：一次调用，环境还空着（`Any <- Env`，给它一个环境就是
跑它）。它的名字是 **norm repo 里的一段程序**：`the_program` 就是
[`viba_ticket/two_handlers/the_program.viba`](viba_ticket/two_handlers/the_program.viba)，`$call` 的
数据就是 `(__dyn_call__ << "the_program" << 1)` —— 名字当数据走，所以这份数据从任何模块都读得起来，
而答这个名字的是角色（第 2 节）。

那段程序是一次调用要跑的全部代码，它 import 两个 **api 文件**（服务各自的签名与提示），然后调用
它们：

```viba
__decl__ = int <- $env Env <- $x int

args = __get_args__ << __decl__

import service_a
import service_b

c0 = service_a.a_add << $env ($sub_env << args.env << "c0") << $x args.x
c1 = service_b.b_scale << $env ($sub_env << args.env << "c1") << $x c0
c2 = service_a.a_add << $env ($sub_env << args.env << "c2") << $x c1
c3 = service_b.b_scale << $env ($sub_env << args.env << "c3") << $x c2

__impl__ = c3
```

四个步子串成一条链：每一步的实参是上一步的答案，每一步跑在自己的子环境里（`c0`、`c1`、……，那个
路径就是这次调用的存储路径）。所以两个服务只能轮流来，**没有哪一个进程能自己跑完这段程序** —— 这
一层里「一次调用跨两个服务」说的就是这件事，下一节说谁做哪一步。

`service_a.a_add` 那样的名字是 **api 文件里的一个叶子**：一份签名，加一句 `{…}` 里的提示。实现不在
norm repo 里 —— 它是宿主的事，服务自己的那个处理进程
（[`service_a.py`](demo/ticket_examples/service_a.py) 与
[`service_b.py`](demo/ticket_examples/service_b.py)，一个服务一个文件）。`builtin.mul`
那种算子也一样：解释器自己不带库，由宿主来补（[`ticket_system/builtins.py`](ticket_system/builtins.py)）。

剩下几个成员说的是**这一次落在哪两个 repo 的哪个提交上**：

- `$viba_interpreter_repo_commit_id` 与 `$viba_interpreter_repo_path`：**哪个解释器**跑这次调用。票据
  是可以今天写、明天跑的，所以它把当时那一份钉在自己身上；
- `$norm_repo_commit_id` 与 `$norm_repo_path`：**哪一份 norm 代码**，以及它是哪一个提交。这是
  `$call` 里那些名字真正落在的代码；
- `$VIBA_PATH`：这次调用找它 import 的模块时用的那些目录，一个 `list[str]`。viba 的
  `Environment.viba_path` 收的是 `$PATH` 那种写法的一串，那一串是宿主跑之前用 `os.pathsep`
  连出来的，不是这张票据存的东西；
- `$handler_name2api_repo_commit_id`：**每个角色自己的模块在哪一个提交上**，一个角色一项 —— 因为
  「哪个名字归谁」是角色模块里的一行，那一行也是代码；
- `$storage_path`：这次调用跑在的那个 viba 环境的**存储根** —— 第 6 节说它是干什么的；
- `$time`：写下这张票据的时刻，`datetime.isoformat()` 的那串文本。

`datetime` 不是 viba 里现成的东西：`$time` 就是 `datetime.isoformat()` 写下的那串文本（viba 里
没有时钟，时刻由宿主写下来）。

上面那两个容器成员（`$VIBA_PATH` 与 `$handler_name2api_repo_commit_id`）写的是**容器本身**，不是它
们的某种拼法：容器字面量写在值的位置上就是那个 list / dict，能数、能按地址取、能原样写回去
（[`viba/viba-interpreter.md`](viba/viba-interpreter.md) 的「容器字面量」与「按地址读元素」两节）。
所以 `$VIBA_PATH` 在盘上就是 `ListLiteral[…]`，读它的人按位置一个一个取
（[`ticket_system/tickets.py`](ticket_system/tickets.py) 的 `the_paths`）；
`$handler_name2api_repo_commit_id` 在盘上就是 `DictLiteral[…]`，读它的人拿键、按键取值（`a_dict`）。
这一层不把 `$VIBA_PATH` 拼成 `os.pathsep` 连起来的一串：那样每读一次都要再切一次，切出来跟原值对不
对得上没人管。真正要一串的地方只有一处 —— 跑这次调用时 `Environment.viba_path` 收的是 `$PATH` 那种
写法，那一串由 [`ticket_system/handler.py`](ticket_system/handler.py) 在那时候连。
[`ticket_system/README.md`](ticket_system/README.md) 的「两个容器成员」一节说的就是这两项。

一张票据就是一个文件。写它的人不去通知谁，读它的人每次都重新打开一遍 —— 所以「发出去了」和
「被谁拿走了」之间没有中间人，也就没有中间人坏掉的余地。

## 2. 一个角色一张能力表：谁答哪个名字

一个处理进程的本事是它那张**能力表**：`{名字: 实现}`，和 `distributed.service` 的 api 是同一种东西
—— 一个实现拿**这次调用跑在的那个环境**，加这次调用的每一个参数，答一个值。表写在角色自己的模块
里，一行一个名字：

```python
# demo/ticket_examples/service_a.py（节选）
def the_api(context):
    """A's capability table: the program, and A's own step of it."""
    return {THE_PROGRAM: the_program(context.norm), "a_add": _a_add}
```

```python
# demo/ticket_examples/service_b.py（节选）
def the_api(context):
    """B's capability table: the program, and B's own step of it."""
    return {THE_PROGRAM: the_program(context.norm), "b_scale": _b_scale}
```

一个服务一个模块、一个模块一个进程。两件事写在这张表里：

- `the_program` 是**票据 `$call` 里那个名字**，两个角色都答它，做法是「把 norm repo 里那段程序跑
  一遍」：
  ```python
  def the_program(norm):
      def run(environ, *given):
          return repo.run_definition(norm, THE_PROGRAM, "run", environ, list(given))
      return run
  ```
  `context.norm` 是这张票据的 norm repo 的那份 checkout（第 3 节说它是怎么来的），`the_program`
  拿它去跑那段程序。
- `a_add` / `b_scale` 是**程序里那几步**，各自只有服务自己答。哪一步归谁是写下来的，不是猜出来的；
  别人问到自己没有的那一步，这一轮就停在那儿（`$not_implemented_err`，第 4 节），那是它**试过**这张
  票据的凭据。

两个服务是两个模块、两个文件，所以票据上 `$handler_name2api_repo_commit_id` 的两项各钉在一个文件
上：`"a"` 钉 [`service_a.py`](demo/ticket_examples/service_a.py) 的提交，`"b"` 钉
[`service_b.py`](demo/ticket_examples/service_b.py) 的提交 —— 换个进程、换个文件，都得对上。

跑一张票据就是跑它那个 `$call`：`$call` 是 `Any <- Env`，缺的只是环境，所以这一步就是 `exec`
（[`viba/viba-interpreter.md`](viba/viba-interpreter.md)「把一次调用写成可执行的」）。给它的那个环境
三样东西来自票据和角色：

```python
environ = Environment(
    EnvironmentStorage("", None, ticket.storage_path),            # 存储根：$storage_path
    EnvironmentCompute(get_func),                                 # 角色能力表 + 内建算子
    os.pathsep.join([norm_checkout, *ticket.viba_path]))          # 找模块的那串目录
```

`get_func` 问的是「这一步谁答」，一次给两个名字（`get_func(module, func_name)`）：这一步声明在哪个
模块（`service_a`）、它在那儿叫什么（`a_add`）。答法两步：先看这个角色的能力表，表里没有再看**这次
调用自己的存储路径**下有没有答案 —— 那条路径只有拿到环境才知道，所以这一步是在实现里判的：有答案就
拿它当答案，没有就说「没有实现」。第二步是「别人做过的那几步这一轮不用再做」，也就是程序能一轮一轮
往前推的原因：第 2 篇里的 `b` 直接跳过 `c0`，因为 `a` 上一轮已经把它记在自己的数据路径下了。

于是「这次调用被给了什么参数」不需要谁来拆 —— 参数本来就在 `$call` 里；「这个名字归谁」也不需要
猜 —— 角色模块写着。这就是为什么一张票据可以今天由甲进程跑、明天由乙进程跑：票据上写着的是**这次
调用和它落在哪份代码上**，不是谁去跑。

走一遍 [`viba_ticket/two_handlers/`](viba_ticket/two_handlers/)。两个处理进程：

```bash
python3 -m ticket_system.scheduler --tickets <票据目录> \
    --handler a=demo.ticket_examples.service_a:the_api \
    --handler b=demo.ticket_examples.service_b:the_api
```

两行 `--handler` 就是两个进程，各加载各的那个模块。

两个进程都在轮询同一个票据目录。`a` 的表里有 `the_program` 与 `a_add`，`b` 的有 `the_program` 与
`b_scale`，所以一张票据是这么被推着往前走的（这是套件跑真调度时日志里的样子）：

| 第几篇 | 谁写的 | 做到了哪一步 | 停在哪 |
|---|---|---|---|
| 1 | `a` | `c0`：`a_add` | `c1` 的 `b_scale` —— 这一步不是 `a` 的 |
| 2 | `b` | `c1`：`b_scale`（`c0` 从存储里回放） | `c2` 的 `a_add` |
| 3 | `a` | `c2`：`a_add`（`c0`、`c1` 回放） | `c3` 的 `b_scale` |
| 4 | `b` | `c3`：`b_scale`（前三个回放） | 没有了：这一段程序跑完了，`$ok` |

第四篇记下 `$ok`，这张票据就做完了。谁的进程都没等谁，两次轮询之间只隔一秒：**上一篇是谁写的，下一
手就是别人的**（`ticket_system/handler.py` 的 `Handler.tick`），而不是「一张票据一个进程只试一
次」—— 那样第一轮之后就没有人再动它了。

**一段 norm 程序「跑起来」是什么意思**：不是宿主拿 python 把它重写一遍，而是照它写一份小 viba 程序、
交给**票据上那个解释器**跑（[`ticket_system/repo.py`](ticket_system/repo.py) 的 `run_definition`）：

```viba
__decl__ = Any <- $env Env
args = __get_args__ << __decl__
import the_program as the_code
__impl__ = the_code << (args.env.sub_env << args.env << "run") << $x 1
```

那份程序在**这次调用的子环境**里跑（名字是 `norm`），所以答案落在票据自己的存储里，而程序本身与它
调用的那几步不会落在同一个数据路径上（viba 不允许两次调用共用一个数据路径）。

## 3. 跑之前把三个版本读出来：对不上就不跑

一张票据说的是「这次调用**落在**哪三个版本上」，不是「大概在哪一份上」。三样都在动手之前**读**
出来对一遍（[`ticket_system/handler.py`](ticket_system/handler.py) 的 `the_commit_id_problem`）：

- **解释器**：正在跑的这个 `viba` 包在哪一个提交上（`handler.the_running_interpreter` 从
  `viba.interpret.__file__` 读），必须就是 `$viba_interpreter_repo_commit_id`。一个进程换不了自己跑的
  解释器，所以对不上就是**不跑**，没有第二条路；
- **norm repo**：`$norm_repo_path`（代码所在的那层目录）得在那个提交上、而且那层目录里没有未提交
  的改动。对不上时不是不跑，而是**把这个提交的树抽一份出来再跑**：那个 checkout 不是这一层能动的
  东西（人还在上面干活），于是 `git read-tree` 到一个临时索引、`git checkout-index` 抽出那份树，
  落在票据目录下自己的一处（[`ticket_system/repo.py`](ticket_system/repo.py) 的 `NormRepo.checkout`）
  —— 对那个 repo 一个字节都不写，没有 worktree、没有索引、没有 ref。抽出来的是整棵树，代码还是在
  同一层目录里（`NormRepo.where`）。没有那个提交、或者那不是 checkout，就留一条停下的记录；
- **这个角色自己的模块**：`$handler_name2api_repo_commit_id` 里写给**这个进程**的那一项，必须是**这个
  进程加载到的那段代码**所在的提交。哪段代码、在哪个文件，由 `handler.where_the_api_is` 从
  `MODULE:FUNCTION` 里问出来（import 它，取它的 `__file__`），提交就在那个文件所在的地方读。

三样都是**读**出来的，没有哪一样是进程说了算 —— 这正是钉它的原因。读不出来的（那里不是 checkout、
机器上没有 git）也是同一条路：钉不住的版本不能算钉住了。票据上没给这个角色写版本，就是没许过它
什么，它照常做。读提交的是 [`ticket_system/code.py`](ticket_system/code.py) 的 `git_commit`：一个
文件路径也能用，git 会往上找到它所在的那个仓库。

## 4. 进度是那个目录：一次尝试一篇，只增不删

进度不是一个文件，是票据旁边那个目录（`<票据目录>/<uid>/progress/`）：**一次尝试一个文件**
（`<写入时刻>-<处理进程名>.viba`），装着那次尝试。上面那张票据被两个进程轮着试了四篇（第 2 节说
为什么是四篇）—— 前三篇各停在一个不归自己的步子上，第四篇把这段程序跑完：

```viba
value =
  $ticket_uid "t1"
  * $handler_name "a"
  * $interpret_result ($err ($not_implemented_err ($msg "no implementation"
    * $module_path "/service_b"
    * $full_qualified_func_name "service_b.b_scale"
    * $call (__dyn_call__ << "service_b.b_scale" << $x 4))))
  * $time "2024-01-02T03:04:05.123456+00:00"
```

```viba
value =
  $ticket_uid "t1"
  * $handler_name "b"
  * $interpret_result ($err ($not_implemented_err ($msg "no implementation"
    * $module_path "/service_a"
    * $full_qualified_func_name "service_a.a_add"
    * $call (__dyn_call__ << "service_a.a_add" << $x 8))))
  * $time "2024-01-02T03:04:06.234567+00:00"
```

```viba
value =
  $ticket_uid "t1"
  * $handler_name "a"
  * $interpret_result ($err ($not_implemented_err ($msg "no implementation"
    * $module_path "/service_b"
    * $full_qualified_func_name "service_b.b_scale"
    * $call (__dyn_call__ << "service_b.b_scale" << $x 16))))
  * $time "2024-01-02T03:04:07.345678+00:00"
```

```viba
value =
  $ticket_uid "t1"
  * $handler_name "b"
  * $interpret_result ($ok 48)
  * $time "2024-01-02T03:04:08.456789+00:00"
```

`$module_path` 与 `$full_qualified_func_name` 是停在哪一步：这一步声明在哪个模块，读成路径
（`/service_b`），以及它的整名（`service_b.b_scale`）—— 名字里带着模块，所以读日志的人不看别的也
知道差的是哪一步。`$call` 是那一步本身，还是能再跑的形式（名字就是那个整名，按最后一个点切开就是
模块和名字）；`$ok 48` 是这一段程序跑完的答案。

**这一步跑在哪条数据路径上**不在这两个名字里：那是给它的那个 environment 的数据路径，宿主从环境上
读（`env.storage.cur_storage_path`）—— 这一步的答案就落在它下面，两个进程轮着跑时靠的也是它。

它的类型是这一层说的第二样东西（[`viba_ticket/ticket_design.viba`](viba_ticket/ticket_design.viba)）：

```viba
TicketStage =
    Object
  * $ticket_uid str
  * $handler_name str
  * $interpret_result InterpretResult
  * $time datetime

TicketProgress = AppendOnlyList[TicketStage]
```

`$interpret_result` 是那次尝试得到的答案，就是 `interpret` 答的那种东西
（[`viba/viba-interpreter.md`](viba/viba-interpreter.md)）：`$ok <值>` 是一次**做完了**的尝试；别的
都是**停下的记录**，里面是 `InterpretError` 的那一支：

- `$not_implemented_err`：这一次尝试停在一个**别人做**的步子上。第 2 节那张表里的四篇记录，前三篇
  都是它 —— 它是「这张票据我接过了，走到这儿，剩下的不是我的」，也就是轮换的那一手；
- `$underlying_viba_op_err`：补这个调用的人写坏了；
- `$viba_program_err`：这次调用或者这个环境根本跑不起来；
- `$environment_api_invalid_argument_err`：环境自己的 api 收不下给它的东西。

和只写**选中的那一支**（`$ok Any | $err InterpretError` 的居民就是一支），所以一篇停下来了的
记录上没有任何 `$ok`，一次答完了的尝试上也没有 `$err`；两支都写下来的东西不是这个和的居民。读的
时候 `by_tag` 问另一支会报「设计里没有这个地址」，读的人把这当成「没有这一支」—— 不是错误，因为
「没答」本来就是结果能说的两件事之一。

这个过程答的就是 viba 那份数据（`viba/interpret_result.viba`），这一层原样存下来
（`tickets.a_result`）：一支一支、字段都在。停下的那一支里，`UnderlyingOpErr` 两支写
`$msg`、`$module_path`、`$full_qualified_func_name` 与 `$call`（那次调用本身，还是能再跑的形式 ——
norm 定义内部坏掉的那种停法 `$module_path` 与 `$full_qualified_func_name` 会空着，因为那是解释器在
跑一份生成程序时报的，它没有一个「哪一步」可指；原因本身在 `$msg` 里），`$viba_program_err` 写 `$msg` 与 `$stack`，
`$environment_api_invalid_argument_err` 写 `$msg`、`$api_name`、`$args`。所以日志里读得出停在哪一步、
为什么停。

`$stack` 是 `list[Frame]`：这次运行当时在哪些调用里，最外一层在前，每一帧是 `$file_path` 与
`$lineno` 两个成员 —— 最外那一帧是主文件本身，没人调它，它的行号是 0；没进过任何调用就是
`ListLiteral[]`。它写在盘上也还是一个列表值：

```viba
value =
  $ticket_uid "t1"
  * $handler_name "b"
  * $interpret_result ($err ($viba_program_err ($msg "broken program"
      * $stack ListLiteral[$file_path "main.viba"
          * $lineno 0, $file_path "/home/norm/the_program.viba"
          * $lineno 12])))
  * $time "2024-01-02T03:04:05+00:00"
```

`$not_implemented_err` 那一支也写着停在哪一步：`$module_path` 是那一步声明在哪个模块（读成路径，
`/service_b`），`$full_qualified_func_name` 是它的整名（`service_b.b_scale`）—— 读日志的人因此看得出
这个角色走到了哪儿、下一手该谁。这一步**跑在哪条数据路径上**不在这两个字段里 —— 那是给它的环境上的东西，读的人在实现里读环境才
拿得到（第 2 节）。写进这一篇的是 `$call`：整名加写在链上的实参，给一个环境就是那一次调用；名字按
最后一个点切开就是模块和名字（[`viba-distributed.md`](viba-distributed.md) 第 3 节说的工单就是照它
落地的）。

读的人按字段取：`progress.error_tag`、`progress.field_of`、`progress.call_of`，
`$stack` 用 `progress.stack_of`（答一串 `Frame`），调度报 `unfinished` 时打的那份状态里也有它
（`progress.the_state` 的 `latest_stack`）。

`AppendOnlyList[TicketStage]` 说的就是那个目录：先写的永远还在，后来的只是又加一个文件。文件名里
带写入时刻与处理进程的名字，所以两个进程同时追加也是两个文件，谁都不会覆盖谁 —— **只增不删不需要
锁**。一张票据现在的状态，读的就是它这一整份进度（`ticket_system/progress.py` 的 `answered`）。

## 5. 停下的条件：每一张票据的进度里都有一条 `$ok`

处理进程那个循环就是：睡一秒，读一遍票据目录和每一张票据的进度，接那些进度里还没有 `$ok`、而且
**上一篇不是自己写的**票据，跑它的 `$call`，把这一篇追加进去。整个系统停在：

> **每一张票据的进度里都有一条 `$ok`。**

一句话在 `ticket_system/progress.py` 的 `finished` 里。`ticket_system/scheduler.py` 每秒钟看一次这
句话：还没到，就让处理进程接着跑；到了，就把它们停掉，打一行 JSON：

```json
{"outcome": "ok", "rounds": 3, "handlers": ["a", "b"], "tickets": ["t1", "t2", "t3"]}
```

处理进程自己退出了呢？重新起一个 —— 一个进程累了不等于系统做完了，停下的条件是调度在看的。起过
`--restarts` 次还退，就报 `crashed`，而不是没完没了地起。`--seconds`（默认 600）到了还没做完，报
`unfinished` 并退 1。

### 谁该动手：轮换，以及「答过就算」

几套处理进程同时在同一个票据目录上轮询，有两件事躲不掉，它们各有一条规矩。

**第一件：一张票据要靠几个进程轮流往前推。** 一段跨两个服务的程序，一个进程做不完（第 2 节）。
所以「这一手是谁的」不是把票据分给某个进程，而是读日志：**上一篇不是自己写的**，这一手就是自己的；
上一篇是自己写的，就等别人。这一条在 `Handler.tick` 里（`the_latest_is_mine`），它同时管住轮换和
重复：一个进程不会对着同一张票据连写两篇没有进展的记录。

**第二件：甲读到一张票据还没做完、正要做，乙在这一瞬间把它做完了** —— 甲那条**停下的**记录落在乙
那条 `$ok` 之后。按「最新一条说了算」读，这张票据又成了没做完，而且**永远回不来**：甲的记录刚落，
下一手轮到乙，乙的 `$ok` 已经不是最新的一条，谁也不肯再写。

所以读的是这一整份进度里**有没有**一条 `$ok`（`progress.answered`）。`TicketProgress` 是只增的
列表：一条记录写进去就永远在里面，那么「这张票据已经答过」这件事也只会从没有变成有，谁后写都顶不
掉。甲那条停下的记录说的只是甲当时读到的东西旧了，它没有答过这张票据，也就无权取消乙的答案。整个
系统的停止条件因此是：**每一张票据的进度里都有一条 `$ok`**（`progress.finished`）。

进程每次要动手之前都会再看一眼日志，所以第二件那个窗口只有几毫秒，不是一整秒。
`tests/test_ticket_system.py` 一边跑真调度一边查这两条：日志里就算有落在 `$ok` 之后的停下记录，
`finished` 也还是真，第二遍调度一篇都不再追加。

## 6. `$storage_path`：答案落在那儿，第二次从那儿回放

一张票据的 `$storage_path` 是那次调用跑在的 viba 环境的存储根。viba 里不纯的宿主函数经
`replayed` 作答：先看这次调用的存储路径下有没有答案，有就回放，没有才算、才写下去
（[`viba/viba-interpreter.md`](viba/viba-interpreter.md)）。票据系统给这条规矩的是一个**落处**，
所以同一张票据被处理两次 —— 两个进程，或者同一个进程两次 —— 那次不纯的调用只算一次：

```
/var/tickets/storage/t1/value.viba      # 第一次尝试写下的答案
```

`value = 42`，就一行。第二次尝试从它回放。第 2 节那条链上的每一步都是这样一次不纯调用：`a_add`
抽的数、`b_scale` 抽的倍数，谁先做到就写在自己那条路径下，后面每一轮都从那儿回放 —— 这也就是两个
进程能一轮一轮把同一段程序推下去的原因。

[`viba_ticket/add_one/`](viba_ticket/add_one/) 那个示例专门演这件事：它的 norm 代码是一个普通的
叶子（加一），角色把它 **套在 `replayed` 里**答（那个处理进程每张票据试两次）：

```python
# demo/ticket_examples/add_one.py
def add_one(environ, x):
    return replayed(environ,
                    lambda: repo.run_definition(norm, "add_one", "add_one", environ, [x]))
```

```bash
python3 -m ticket_system.handler --tickets <票据目录> --handler add_one \
    --api demo.ticket_examples.add_one:the_api --again
```

票据系统里没有「已经算过了」这种状态要维护：答案就在那次调用自己的存储里，票据指着它，viba 自己
认识它。

## 7. 职责边界

这个系统的输入是一个票据目录，输出是票据旁边那份进度。它做三件事：按票据上写的三个提交把版本对
一遍，把 `$call` 交给答这个名字的角色去跑，把结果追加成一篇记录。

它不做的事，是这个边界另一侧的：

- 票据是谁写的、什么时候写、按什么顺序写，是写票据那个人的事。系统里没有「下一张」「优先级」
  「依赖」这些东西，也没有持有票据的那份清单；
- `$call` 里的名字归哪个角色、以及那个角色怎么答，写在角色模块里（[`demo/ticket_examples/`](demo/ticket_examples/)）。
  这一层不带任何一份具体 viba 代码的实现，只带内建算子
  （[`ticket_system/builtins.py`](ticket_system/builtins.py)：解释器不带库，算术要有人补）；
- 一个名字由谁答，不看名字，只看角色的能力表。ai agent 与普通进程在这一层是同一种东西：都是
  `$handler_name` 下的一个答案。
