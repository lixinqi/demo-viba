# ticket_system

一批调用写在文件系统上，一批普通进程各按自己的角色去接。这个包是那件事的 python：票据怎么写怎么
读、进度怎么追加、一个处理进程怎么轮询、调度怎么起它们又怎么停。

| 模块 | 是什么 |
|---|---|
| `tickets.py` | 一张票据：一次要跑的调用、它落在哪三个版本上、它跑在哪个存储根，写在哪儿 |
| `progress.py` | 一张票据的进度：一次尝试一篇；怎么读那篇里的 `InterpretResult`（哪一支、哪个字段、哪次调用、`$stack` 是哪些调用）；以及「进度里有一条 `$ok` 才算做完」 |
| `handler.py` | 一个处理进程：它问角色要能力表、把三个版本读出来对一遍、接「上一篇不是自己写的」那些票据，和那个隔一秒轮询一遍的循环 |
| `repo.py` | norm 代码所在的那个 repo 的那棵树（代码那一层在里面；提交对不上就抽一份出来，不写那个 repo），以及把它的代码跑起来 |
| `builtins.py` | `builtin.*` 那些算子：解释器不带库，宿主补 |
| `code.py` | 一段代码在哪、在哪个提交上（`git rev-parse HEAD`），读不出来的时候说什么 |
| `scheduler.py` | 起每一个处理进程，并在每张票据都做完的那一刻停下它们 |

[`viba-ticket.md`](../viba-ticket.md) 是这一层的章节；[`viba_ticket/`](../viba_ticket/) 里是
票据与进度的 viba 定义，以及两个示例的 norm 代码；角色模块在
[`demo/ticket_examples/`](../demo/ticket_examples/)；[`tests/test_ticket_system.py`](../tests/test_ticket_system.py)
是跑它们的套件。

三个词先分清：**解释器**（跑 viba 的 python 包，票据说必须是哪个提交）、**norm repo**（调用要跑的
viba 代码所在的那个 git repo，`$norm_repo_path` 指到代码那一层目录、`$norm_repo_commit_id` 说哪个
提交）、**角色**（一个处理进程的能力表 `{名字: 实现}`，写在自己
的 python 模块里）。

## 跑一次

```bash
python3 -m ticket_system.scheduler --tickets <目录> \
    --handler <名字>=<模块>:<函数> --handler <名字>=<模块>:<函数>
```

`--handler NAME=MODULE:FUNCTION` 说两件事：`NAME` 是这个处理进程的名字（它写的每一条进度都带着
这个名字），`MODULE:FUNCTION` 就是**角色**：一个 python 函数，拿一个 `Context`（谁在做、在哪个票据
目录上做、**这次调用落在哪个 norm repo 上**）**答一张能力表** —— `{名字: 实现}`，与
`distributed.service` 的 api 同一种东西：一个实现拿这次调用跑在的那个环境，加这次调用的每一个参数，
答一个值。**哪个名字归哪个角色，就是那个模块里的一行**，不是这里按约定推的：

```python
# demo/ticket_examples/service_a.py（节选）
def the_api(context):
    """A's capability table: the program, and A's own step of it."""
    return {THE_PROGRAM: the_program(context.norm), "a_add": _a_add}
```

一个角色一个模块：上面这份是服务 A 的进程，服务 B 是另一个文件
（[`service_b.py`](../demo/ticket_examples/service_b.py)），所以票据上那两个提交是两份代码、两个文件
—— 「哪个名字归谁」就在这两个文件里。

能力表每张票据问一次（两张票据可能落在两个 norm repo 上），表里的 `builtin.*` 由这一层补上。在哪跑
就从哪 import，所以在仓库根目录跑。

一段程序要两个服务轮流做时（[`viba_ticket/two_handlers/`](../viba_ticket/two_handlers/) 就是），
**这一手是谁的**也是从日志里读的：进程接那些进度里还没有 `$ok`、而且**上一篇不是自己写的**票据
（`Handler.the_latest_is_mine`）。这么写有两个用处：一是轮换 —— 甲做一步、停下，乙接着做下一步；
二是不重复 —— 一个进程不会对着同一张票据连写两篇没有进展的记录。

`get_func` 问的是一次调用、两个名字：这一步声明在哪个模块（`service_a`）、它在那儿叫什么
（`a_add`）—— 这是 viba 的协议（`viba-interpreter.md`「`get_func` 与
`full_qualified_func_name`」）。表里没有这个名字时，答案还可能在**这次调用自己的存储路径**下：
有人记过就拿它当答案。那条路径只有环境上有，所以这件事是在实现里判的（`_capabilities` 的
`from_the_storage`）—— 这就是「另一个进程做过的那几步，我这一轮直接回放」，一段跨服务的程序因此
能被两个进程一段一段地推完。谁都没记过、也不归自己的那一步，才是 `$not_implemented_err`；它由
说这句话的那一方写全（`handler.not_implemented`：模块读成路径、整名、以及 `$call`）。

几套处理进程同时在同一个票据目录上轮询，所以「甲读到还没做完、要动手时乙已经做完了」这件事躲不
掉：甲那条停下的记录会落在乙那条 `$ok` 之后。所以一张票据做完了没有，读的是它这一整份进度里**有
没有**一条 `$ok`（`progress.answered`），不是最新那一条是不是 —— 进度只增，「这张票据已经答过」就
只会从没有变成有，后来那条停下的记录顶不掉它。进程每次要动手之前都会再看一次日志
（`Handler.tick`），所以这个窗口是几毫秒，不是一整秒。

调度每秒钟看一次票据目录：只要还有一张票据的进度里没有 `$ok`，处理进程就在跑；每一张都有一条
了，它就把它们停掉，打一行 JSON 并退 0。`--seconds`（默认 600）是一次运行的上限，到了还没做完就
报 `unfinished` 并退 1；处理进程自己退出了会被重新起一个，起过 `--restarts`（默认 5）次还退，就报
`crashed`。

## 跑一次之前，三个版本先读出来对一遍

票据上 `$viba_interpreter_repo_commit_id`、`$norm_repo_commit_id` 与 `$handler_name2api_repo_commit_id`
是**一次运行要落在哪三个版本上**。处理进程在跑那张票据之前把三样都读出来对一遍
（`handler.the_commit_id_problem`）：

- **解释器**：正在跑的这个 `viba` 包在哪一个提交上（`the_running_interpreter` 从
  `viba.interpret.__file__` 读），必须就是票据写的那个。一个进程换不了自己跑的解释器，对不上就是不跑；
- **norm repo**：`$norm_repo_path` 那一层代码在哪个提交上、那一层里有没有未提交的改动，都必须对得上
  `$norm_repo_commit_id`。对不上时不是不跑，而是**把这个提交的树抽一份出来**：
  `repo.NormRepo.checkout` 用 `git read-tree`（临时索引）
  加 `git checkout-index` 把那份树写到票据目录下自己的一处，跑的是那一份 —— 那个 repo 一个字节都不写，
  人在上面干活不受影响。没有那个提交、或者那不是 checkout，留一条停下的记录；
- **这个角色自己的模块**：`$handler_name2api_repo_commit_id` 里写给**这个进程**的提交，必须是**这个进程
  加载到的那段代码**所在的提交。哪段代码、在哪个文件，由 `handler.where_the_api_is` 从
  `MODULE:FUNCTION` 里问出来，提交从那儿读。

三样都是**读**出来的，没有哪一样是进程说了算 —— 版本是读出来的，这就是要钉它的原因。对不上（包括
读不出来：不是 checkout、没有 git）时，这个进程不跑这次调用，留的是**停下的那一条**：`$err` 里是
`$underlying_viba_op_err` 那一支，`$msg` 里写着票据要的版本和读到的版本。票据上没给这个角色写版本，
就是没许过它什么，它照常做。

## 一个处理进程单独跑（测试里就是这么跑它自己的那一份）

```bash
python3 -m ticket_system.handler --tickets <目录> --handler <名字> \
    --api <模块>:<函数> [--interval 1] [--ticks N] [--again]
```

这个进程的版本没有开关可报：它是从加载到的那个文件里读出来的。`--ticks` 是「走这么多轮就停」，
`--again` 是「每张票据试两次」—— 第二次试的时候那次调用的存储里已经有答案了，于是回放
（[`viba_ticket/add_one/`](../viba_ticket/add_one/) 那个示例）。

## norm repo 里的代码怎么被跑起来

一个角色可以用两种办法补一个名字：自己拿 python 答（[`demo/ticket_examples/upper.py`](../demo/ticket_examples/upper.py)），
或者指名 norm repo 里的一段代码、由这一层跑它
（[`demo/ticket_examples/service_a.py`](../demo/ticket_examples/service_a.py) 与
[`service_b.py`](../demo/ticket_examples/service_b.py) 里的 `the_program`）。第二种走的是 `repo.run_definition`：照那段代码写一份小 viba 程序，交给**票据上那个
解释器**跑 —— 不是宿主拿 python 把它重写一遍：

```viba
__decl__ = Any <- $env Env
args = __get_args__ << __decl__
import the_program as the_code
__impl__ = the_code << (args.env.sub_env << args.env << "run") << $x 1
```

那份程序在**这次调用的子环境**里跑（名字是 `norm`），所以答案落在票据自己的存储里，程序与它调用的
那几步也不会落在同一个数据路径上（viba 不允许两次调用共用一个数据路径）。

那段代码自己 import 的 api 文件（`service_a.viba`、`service_b.viba`）只写签名与提示，实现在角色
那边：程序里 `service_a.a_add` 这一步问的是宿主（`get_func`），问到谁就是谁做。

## 票据与进度在盘上

```
<票据目录>/<uid>/ticket.viba              一个定义 value，装着整张票据
<票据目录>/<uid>/progress/<时刻>-<进程>.viba  一次尝试，一个定义 value
```

一张票据就是一个文件：谁写下来就是谁的，没有注册，也没有谁要去通知谁 —— 处理进程每次轮询都重新读
一遍。进度是那个目录：一次尝试一个文件，文件名带写入时刻与处理进程的名字，所以两个进程同时追加也
是两个文件，**只增不删不需要锁**。一张票据做完了没有，读的是这一整份进度里有没有 `$ok`。

## 两个容器成员：`$VIBA_PATH` 与 `$handler_name2api_repo_commit_id`

`Ticket` 上的这两项就是容器本身，盘上写的是容器字面量，读的人按地址取元素 —— 中间没有第二种写法：

```viba
value =
  Object
  * $VIBA_PATH ListLiteral["/home/norm", "/home/viba"]
  * $handler_name2api_repo_commit_id DictLiteral[("a", "36d82da5"), ("plain", "1a2b3c4d")]
```

容器字面量写在**值**的位置上就是那个容器：一次运行把它算成一个值，能数、能按地址取、能原样写回去
（`viba-interpreter.md`「容器字面量」）。所以这一层两头都走 `viba.serialize`：写票据与写进度是同一个
`write_snapshot`，读回来是同一个 `read_snapshot`，容器成员不另开一条路。

`$VIBA_PATH` 是 `list[str]`：这次调用找它 import 的模块时用的那些目录，读的人按位置一个一个取
（`tickets.a_list`，`tickets.the_paths` 在上面再加一道「每一个都得是字符串」）。这一项**不**存成
`os.pathsep` 连起来的一串：那样每读一次都要再切一次，切出来跟原值对不对得上没人管。真正需要一串的
地方只有一处 —— `Environment.viba_path` 收的是 `$PATH` 那种写法，那是 `handler.answer` 跑之前用
`os.pathsep` 连的事，不是票据存什么的事。

`$handler_name2api_repo_commit_id` 是 `dict[str, str]`：一个角色一项，键就是写下来的那些键，值按键取
（`tickets.a_dict`：`VibaNode.keys` 加 `VibaNode.at_key`），和 `$__getitem__` 对 dict 的两步是同一件
事（`viba-interpreter.md`「按地址读元素」）。

谁要的值不是容器，读的人当场报出来，不猜：`a_list` / `a_dict` 遇上不是容器的成员、`the_paths` 遇上
不是字符串的元素，都停下并把那一个值写进消息里。这是
[`viba_ticket/ticket_design.viba`](../viba_ticket/ticket_design.viba) 上写的类型，读的人照它来。

## 票据的存储：答案落在那儿

一张票据的 `$storage_path` 是那次调用跑在的 viba 环境的**存储根**：调用写下的每一份快照都落在那里
（`<存储根>/value.viba`，子环境再往下层层叠）。所以同一张票据被处理两次 —— 两个进程，或者同一个
进程两次 —— 那次不纯的调用只算一次，第二次从快照里回放。这是 viba 自己的规矩
（`viba.interpret.replayed`），票据系统给它的是一个**落处**：进程叫什么、跑在哪、答案记在哪，都在
票据里，不在进程里。
