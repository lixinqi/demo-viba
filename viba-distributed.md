# 分布式：多套服务、一份 store

一份 viba 定义不写谁来实现、在哪台机器上跑（[`roadmap.md`](roadmap.md)）。同一份程序的各部分因此
可以分在不同的进程里，各是一套服务 —— 一套服务就是一组 **api**：它实现得了的那些名字。哪一步要
的算子只有哪一套会，这一步就在哪一套那里算。几套都行 —— 这一章的例子是两套（A 和 B，各是一个
Python 进程）。这样的程序一个进程跑不完：它停下来欠着的每一步，都以一份 **viba 工单** 留在几套
服务共用的 store 里，而一份工单只有两部分：**viba 代码**和**数据路径**（第 3 节）。

跑这样一份程序的是 [`distributed/`](distributed/) 这个包：[`distributed/service.py`](distributed/service.py)
是一个服务进程那一侧，[`distributed/scheduler.py`](distributed/scheduler.py) 是每一轮的调度，
[`distributed/README.md`](distributed/README.md) 里是它们的命令、报告和 store 布局。这一章跟着
[`demo/distributed/naive/`](demo/distributed/naive/) 里那份跑得通的程序过一遍：它是两套服务（A 和
B，各是一个 Python 进程）共用一份 environment storage（下文只说 store）。同一个包也跑得动别的
程序：[`demo/distributed/delivery/`](demo/distributed/delivery/) 是三套服务，
[`demo/distributed/reading/`](demo/distributed/reading/) 是五套服务、一套一个 api，名字和类型都不
一样，调度那条命令照旧。

跑它的还是 `interpret`（[`viba-interpreter.md`](viba-interpreter.md)）：类型、`__decl__`、
`__impl__` 都没有第二套。多出来的只有一条：**谁的能力表里有这一步要的那个名字，这一步就在谁那里
算** —— 能力表就是 `get_func` 报给解释器的那张表：这个进程实现得了哪些名字。走到哪一套服务都没
有那个名字的一步，而 store 里也还没有这条数据路径上的结果（`<数据路径>/value.viba`，第 4 节），
运行不会失败，而是停下，结果是一支**递延**（第 2 节）。

## 1. 同一份 viba 代码，两组 api 交替

[`demo/distributed/naive/interleaved.viba`](demo/distributed/naive/interleaved.viba) 是这份程序：两套
服务各自的 api 写在自己的文件里，程序把它们 import 进来，然后写五步，两边的 api 交替：

```viba
# demo/distributed/naive/interleaved.viba
__decl__ = int <- $env Env

args = __get_args__ << __decl__

import service_a
import service_b

c0 = service_a.a_step << $env ($sub_env << args.env << "c0") << $x 1
c1 = service_b.b_step << $env ($sub_env << args.env << "c1") << $x c0
c2 = service_a.a_scale << $env ($sub_env << args.env << "c2") << $x c1
c3 = service_b.b_scale << $env ($sub_env << args.env << "c3") << $x c2
c4 = service_b.b_step << $env ($sub_env << args.env << "c4") << $x c3

__impl__ = c4
```

两个写法是这份程序要求的：

- **每一步都给自己一份子环境**（`c0`、`c1`、…）：这份子环境在 store 里的路径，就是这一步的数据
  路径；一条数据路径只对应一次调用（一步就是一次调用）—— 服务把这一步的结果写在它下面，哪一步
  停下了，这一步写下的那份文件也在它下面（第 3 节）。同一个 `a_step` 写在两处就要两个名字，
  否则两次调用就会用同一条数据路径。
- **每一步的实参是上一步的结果**：这份程序因此只能按书写次序跑，两套服务只能轮流往前走，谁也
  一个人跑不完。

两套服务的 api 就是那两个被 import 的文件：`service_a.viba` 是 A 的 `a_step`、`a_scale`，
`service_b.viba` 是 B 的 `b_step`、`b_scale`（同样两个签名，换了名字）：

```viba
# demo/distributed/naive/service_a.viba
a_step =
    int
  <- $env Env
  <- $x int
  <- { add the amount this service drew, and record the answer }

a_scale =
    int
  <- $env Env
  <- $x int
  <- { multiply by the amount this service drew, and record the answer }
```

四个都是叶子（每一步都在 `{…}` 里直接算出结果，不再调别的模块）：一个 int 进、一个 int 出，而且
都不纯 —— 结果不只由实参决定，加多少、乘多少由 A 或 B 的服务进程当场随机抽。签名写在设计里，
实现只有那一套服务有：

```python
# demo/distributed/naive/service_a.py
def the_api(service):
    def a_step(environ, x):
        return service.recorded(environ, lambda: int(x.value) + random.randrange(1, 10))

    def a_scale(environ, x):
        return service.recorded(environ, lambda: int(x.value) * random.randrange(2, 5))

    return {"a_step": a_step, "a_scale": a_scale}
```

`recorded` 就是 `replayed`（[`viba-interpreter.md`](viba-interpreter.md)「幂等与快照：结果要能
回放」）：第一次执行时算出结果、写进 store，之后每一次都直接回放同一份。随机抽出来的那个数只用
一次，落到盘上的是算出来的结果 —— 后面每一次运行都回放这份结果，不再抽第二次。这是整份程序可复现
的全部依据。

## 2. 递延：停下的那一步带回来什么

A 的服务进程执行到 `c1`（`b_step`）这一步时，能力表里没有这个名字。`interpret` 遇到这样一步，
给出的不是失败，而是一支**递延**（deferral）—— `$not_my_duty_exception Duty`，意思是"这一步不归
这个进程管"，等有能力表里那个名字的服务进程接着做。它是 `interpret` 四支结果里的第四支
（[`viba-interpreter.md`](viba-interpreter.md)「一次执行会得到什么」）：

```viba
Duty =
    Object
  * $step Step        # 停在哪一步
  * $call ...         # 那一步收到了什么：实例，写下来是什么样就是什么样
  * $reason str       # 为什么停

Step =
    Object
  * $module_path str  # 那一步的数据路径
  * $func_name str    # 那一步要的名字
```

`$step` 说的是**停在哪一步**，它的两个字段正是宿主（跑 `interpret` 的那个程序）从
`get_func(module_path, func_name)` 收到的两个参数：

- **`$module_path` 是这一步的数据路径**：这一步跑在的那份子环境，在 store 里的路径就是它。这份
  程序里五步各在自己的子环境里执行，所以是 `root/c0`、`root/c1`、…；同一个定义换个案子就是另
  一步；
- **`$func_name` 是这一步要的名字**（这里是 `b_step`）—— A 的能力表里没有的那一个。

数据路径不决定这一步由哪个服务进程算（那由谁的能力表里有 `$func_name` 决定），它只说数据放在
哪：这一步的结果写在它下面，停下时写下的那份文件也在它下面（第 3 节）—— 接手的服务进程照着这条
数据路径就知道该往哪写。

`$call` 是这一步**拿到的实参**，照源码里的写法：执行到这一步时，前面每一步的结果都已经算好，所以
里面是值（`$call 9`）。环境排在参数第一位，它是宿主值、不是可序列化数据，不随 `$call` 走 ——
接手的服务进程自己造一份环境。

`$reason` 是**为什么停**：这里是 `no implementation`，也就是"这个进程的能力表里没有这个名字"。

服务进程把这三个字段写成一行 JSON 报给调度：`service` 是哪一个服务进程报的，`phase` 是它在做工单
还是在跑程序（第 4 节），`result` 是这一行的种类（这里是 `not_my_duty`，就是第 2 节那支递延），
`path` 就是 `$step.module_path`，`func_name` 就是 `$step.func_name`，`reason` 就是 `$reason`，
`prepare` 是这份递延写成文件的样子（第 3 节），`api` 是这个进程这一回经手的每一次调用
（`recorded` 留下的记录：哪条数据路径、是算的还是回放的、结果是什么）：

```json
{"service": "a", "phase": "run", "api": [{"path": "root/c0", "computed": true, "value": 9}],
 "result": "not_my_duty", "reason": "no implementation", "path": "root/c1",
 "func_name": "b_step", "prepare": "value =\n  $call 9\n  * $measured nil\n"}
```

## 3. viba 代码加数据路径

调度拿到这行 JSON，把它写进各套服务共用的 store。写下的只有两部分，缺一个都不成：

- **viba 代码**：文件的内容 —— 一个定义 `value`，两个成员：`$call`（这一步拿到的实参，就是递延
  里那一份，已经算成值、已经固定下来）和 `$measured`（这一步的结果，还没人算出来的时候写 `nil`）；
- **数据路径**：它的位置 —— 停下这一步的那条数据路径 `<数据路径>`，文件名就是它要的那个名字
  `<api>`（就是 `$func_name`）。

```viba
# <数据路径>/prepare/<api>.viba
value =
  $call 9          # 这一步拿到的实参
  * $measured nil  # 结果还没算出来
```

两部分各管一半，五件事因此各归各位：

| 想知道什么 | 在哪 |
|---|---|
| 哪一步 | 数据路径：那一段 `<数据路径>`（就是 `$step.module_path`） |
| 要哪个名字 | 数据路径：文件名 `<api>`（就是 `$step.func_name`） |
| 它收到了什么 | viba 代码里的 `$call`（已经是算好的值） |
| 还缺什么 | viba 代码里那个还是 `nil` 的 `$measured`，以及这条数据路径上还没有的结果文件 `<数据路径>/value.viba` |
| 结果落在哪 | 同一条数据路径下的 `<数据路径>/value.viba`，`replayed` 读写的文件（第 4 节） |

这两部分合起来，就是 **viba 工单**（work order），它是自足的：人、另一个进程、另一门语言，谁都
只靠这两部分就能把这一步算完 —— 数据路径说有哪一步、要哪个名字，`$call` 说这一步拿到了什么，
能力表里有 `<api>` 的那个服务进程据此算出结果，把结果落到同一条数据路径下 `replayed` 读的那份
文件上（`<数据路径>/value.viba`，文件名是 viba 自己的约定，见
[`viba-interpreter.md`](viba-interpreter.md)「幂等与快照：结果要能回放」），不必知道这次运行的
其他任何情况。补账那一侧算完还会把同一份结果填回工单的 `$measured`（`measure` 干的）：那是它
自己的记录，下一轮凭它知道这份工单已经补过，不会再算一遍（第 4 节）。执行状态也没有跟着搬过来：
continuation 没有被捕获，它就在盘上（[`roadmap.md`](roadmap.md) 第 3 节）。谁的能力表里有
`<api>`，谁就接下这一步，把它完成。

环境不随 `$call` 走这一点，正是"每门语言各有自己的 `interpret`"的意思（[`roadmap.md`](roadmap.md)
第 4 节）：环境是局部的，写进 store 的只有实例。

这份程序在一轮里跑不完：它欠着的那几步就在 store 里的 `<数据路径>/prepare/<api>.viba`，`$measured`
还是 `nil`，那条数据路径下也还没有 `value.viba`。谁补上自己名下的那几份 —— 按 `$call` 算出结果、
落到那条数据路径下 —— 整份程序就往前走一步；全补上，整份程序就有了结果。整份程序此刻的状态，
就是那几份 viba 代码加它们各自的数据路径，不是一次失败的记录。

## 4. 一轮：欠着的先补上，再跑

调度 [`distributed/scheduler.py`](distributed/scheduler.py) 每一轮同时启动每一套服务的进程两次：
第一次让它们各自读 store，把属于自己那些 `<数据路径>/prepare/<api>.viba` 补上；第二次让它们各跑
一遍这份程序 —— 上一次停下的那些调用这次直接回放，接着跑下去。服务进程的命令行参数 `--phase answer` 和
`--phase run` 选的就是这两次。一次**运行**指一个服务进程跑一遍程序；一次**调度**是从头跑到 OK 的
那一串轮。

顺序不能反：上一轮欠着的没补上就跑，只会在同一条数据路径上停第二次。

**停下那一步会留下文件，一轮也会留下记录**，都进 store：

- **停下那一步的那份文件**：`$call` 加还没填的 `$measured`，调度把它写在停下的数据路径上 ——
  `<数据路径>/prepare/<api>.viba`，例如 `root/c1/prepare/b_step.viba`；
- **这一轮的记录**：`failure/round-<k>.viba`，写着这一轮 A 和 B 各停在哪一步（`$module_path`、
  `$func_name`、`$reason`），以及上面那份文件在哪。

下一轮读这些 `prepare/` 就是在补上一轮欠的：工单里已经填好 `$measured` 的照它回放，还没填的现在
按 `$call` 算。算出的结果落在这次调用自己的数据路径下（`<数据路径>/value.viba`），那正是
`replayed` 读写的文件；同一份结果也填进工单的 `$measured`（`measure` 干的），那是补账这一侧的
记录，下一轮凭它知道这份工单已经补过 —— 于是**停下过的运行再跑一遍时直接回放，接着跑下去**。

store 里因此留着一次运行已经算过的每一步：`root/c0/value.viba` 里有结果，这一步就既不用再问 A，
也不用再问 B。

一份 store 同时被各套服务的进程读写，所以写出的文件是一次写完整的（先写在旁边，再改名：
[`viba-interpreter.md`](viba-interpreter.md)「幂等与快照：结果要能回放」）。读到的那一份要么还
没有，要么是完整的一份，不会是半份。

回放的依据只有 store：同一步的结果落在两处（`<数据路径>/value.viba` 与工单里的 `$measured`），
两处不一致时运行不会报错 —— 例如删掉 `value.viba` 却留着已经填好的 `$measured`，下一轮会重算这
一步，而后面几步仍回放着上一次的结果，同一条链上因此混着两次执行的结果，调度照报 `ok`。

## 5. 预期的三件事

`demo/distributed/naive/` 这份程序上，一次调度是这样的：

1. **最后一轮某个服务进程上得到 OK**。跑到底的是最后一步的 api 所属的那个服务进程：它的运行走到
   `__impl__`，给出整份程序的结果，调度报一行结局 —— `outcome` 是整次的结局，`rounds` 是跑了几
   轮，`service` 是最后跑到底的那一套，`value` 是整份程序的结果：

   ```json
   {"outcome": "ok", "rounds": 2, "service": "b", "value": 165}
   ```

   这一行在最后，退出码 0。
2. **最后一轮之前的每一轮，两套服务停下的都是 `not_my_duty`，而且数据路径从不重复**。理由在第 4 节：
   一轮停下的数据路径，在下一轮跑之前一定已经补上，所以再跑到那里就直接回放，不会再停。停下的
   数据路径因此一次比一次靠后，只增不减。两套服务的进程是同时跑的，一轮能往前走多远看它们怎么错开
   —— 它有时一轮就走完，有时要三轮 —— 但不会退回去。
3. **不会死循环，坏了就报坏**。轮数有上限（`--rounds`，默认 1024），跑满就报
   `{"outcome": "unfinished", ...}`；同一个数据路径上停第二次（说明那一份没人补）当场报
   `{"outcome": "stuck", ...}`；一个服务进程 60 秒没退出，或者它报回来的 `result` 是 `crashed`、
   `failed`、`program_err`（进程起不来、这一步的实现抛了异常、程序本身跑不起来），整次调度报
   `{"outcome": "broken", ...}`。四种结局里只有 `ok` 的退出码是 0，其余三种都是 1，而不是一轮
   一轮等下去。

`demo/distributed/naive/test_distributed.py` 验证的就是这几条（`broken` 那一支用的是起不来的服务
进程），另外还验证两件事：每一个不纯的步子只算一次（`recorded` 留下的记录就是证据），以及同一份
store 上再调度一次一轮就 OK、一步都不算。

## 6. 自己写一份

1. 写一份 viba 程序，每一套服务的 api 各写成叶子（`名字 = 结果类型 <- $env Env <- $x 类型 <- { … }`）；
2. 每一步给自己一份子环境（`$sub_env << args.env << "名字"`），名字不要重 —— 子环境也可以开在另一份
   子环境下面（[`demo/distributed/delivery/`](demo/distributed/delivery/) 那五步就都开在 `order`
   这一个子环境下面，数据路径因此是 `root/order/weight` 这样的）；
3. 给每一套服务写一组实现（`名字 → callable(environ, x)`），实现里用 `service.recorded`；
4. 起调度。调度脚本不认任何具体的服务：`--service 名字=模块` 给几条就有几套，模块是你自己写的
   （一套服务一个进程，那一侧由 [`distributed/service.py`](distributed/service.py) 提供）：

   ```bash
   python3 -m distributed.scheduler --store <一个空目录> --program <你的程序> \
       --service <名字>=<你的服务模块> --service <名字>=<你的服务模块>
   ```

   一条能跑的命令要自己写；照抄一份见 [`demo/distributed/naive/README.md`](demo/distributed/naive/README.md)
   （那里是两套服务，A 和 B）。三套服务的例子是
   [`demo/distributed/delivery/`](demo/distributed/delivery/)，五套服务、一套一个 api 的例子是
   [`demo/distributed/reading/`](demo/distributed/reading/)；三份 README 里的命令是同一个写法，
   只有 `--service`、`--store`、`--program` 三项各按各自的程序和服务填。

实现拿到的是这次调用的一个个实参，环境排在第一位：写 `(environ, x)` 就收一个实参，写
`(environ, x, y)` 就收两个。这是程序那一侧要守的写法：运行那一侧按参数写下来的次序一个一个交，
环境交在 `$env (...)` 写的位置（[`viba-interpreter.md`](viba-interpreter.md)），补账那一侧则固定
把环境放在第一个（[`distributed/service.py`](distributed/service.py)）—— `$env (...)` 因此要写在
一条链的最前面。工单里留得下的只有可序列化数据，所以一个实参的调用把那个值本身写成 `$call 9`，
几个实参的调用把它们写成一个带 tag 的积 —— `$call($x 9 * $y 4)`，tag 只说这份实参去了哪个位置
（见 [`viba-pattern.md`](viba-pattern.md)）。补上一轮欠账时按实现自己的参数个数交：一个参数就交
整份 `$call`（它本身是个积也一样），几个参数就把积按书写次序拆开交。实参里除了环境还有别的宿主
值的调用，留不了工单，补账时当场报错而不是少交一份。
