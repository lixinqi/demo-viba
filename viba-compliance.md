# 合规：规则与呈证

一份规则（rule）说"什么算合规"，一份呈证（witness）说"这一次是什么情况"，两者合起来给一个
判定。这一章讲这套东西怎么用**可执行模块**来写：规则是程序，呈证也是程序（它给出那份实例，
而实例里的事实是问来的），判定就是跑规则那个程序。

## 1. 一个规则是一个程序

先看情景（完整的例子在 [`compliance/demo/`](compliance/demo/)）。一起案子：**受害人与
嫌疑人各有一个当时的坐标，还有一个时刻**。12:30 那一刻，受害人在 (0,0)，嫌疑人在 (3,4)。要问
的是一件事——**那一刻两人是不是至少隔了 5**。

这条规则读的就是呈证（第 2 节）里的三个事实：`$victim`、`$suspect`、`$at`，然后把它问的那
件事判成 `bool`。规则就是一个 viba 程序：`__decl__` 是 `bool <- $env Env`，判定不是另一套推理，
就是把文件跑起来。

```viba
# compliance/demo/rule_distance.viba
__decl__ = bool <- $env Env

args = __get_args__ << __decl__

import case_at_1230 as case_at_1230

Point = $x int * $y int
Case = $victim Point * $suspect Point * $at str

measure_distance =
	int
	<- $env Environment
	<- $evidence Environment
	<- $case Case
	<- {
		how far apart the victim and the suspect were: not a pure function,
		so the answer is a call the run records
	}

distance_ge =
	bool
	<- $env Environment
	<- $d int
	<- $threshold int
	<- {
		is that distance at least the threshold?
	}

# this case's storage path: the witness is read under it, and this is where the
# case's evidence — its call — is kept
case_env = args.env.sub_env << args.env << "case_at_1230"

# the witness: the three facts of that moment
the_case = case_at_1230 << case_env

# the measurement of those facts. The call itself runs under a temporary
# environment (a call has no storage path of its own), and is told where the evidence
# goes: this case's storage path. Not pure, so what it answers becomes the call.
distance =
    measure_distance
    << $env (args.env.tmp_env << args.env)
    << $evidence case_env
    << $case the_case

# the rule's question: at least this far apart?
threshold = 5

__impl__ =
    distance_ge
    << $env (args.env.tmp_env << args.env)
    << $d distance
    << $threshold threshold
```

读法：

- **一步一个定义**：案子的数据路径、呈证、测量、判定各是一行，没有把调用套在调用里面。定义是按需求值的
  绑定，一次运行里只求值一次（[`viba-interpreter.md`](viba/viba-interpreter.md) 的「求值策略：按需求值
  （call-by-need）」一节），所以 `the_case` 就是那份实例本身。
- **`case_env` 是这个案子的数据路径**：`case_at_1230` 这个名字同时是模块名、子环境名，也落在
  数据路径上（`root/case_at_1230`）。读呈证用它，这个案子的证据也存在它下面。
- **调用用临时环境，证据才要数据路径**。函数调用给 `(args.env.tmp_env << args.env)`：一次调用没有
  自己的数据路径，也不该占一个（`tmp_env` 每次都是新的，见
  [`viba-interpreter.md`](viba/viba-interpreter.md)）。要给
  证据落数据路径的是**测量**：它多收一个槽位 `$evidence Environment`，明说"这次测量属于哪个案子"。
  两者分开，规则里才没有人把任意一次调用钉到案子的数据路径上。
- **`__impl__` 是判定**。它是 `bool`，跑完就是结果：真合规、假不合规。这条规则跑出来是
  `$ok true`——量出来恰好 5，够门槛。
- **条件是它自己的函数，拿什么比由它的参数给**。`distance_ge` 问的是"距离至少到没到门槛"，门槛由
  `$threshold` 给——`threshold = 5` 是这条规则自己的选择，换个案子换个门槛，写的还是同一个
  函数。规则想有几个条件、想怎么组合（`<<` 给参数、定义复用、模块拆开），都是写程序的事。
- **函数体里的 `{...}` 是说明**：实现来自宿主的 `get_func(module_path, func_name)`（见
  [`viba-interpreter.md`](viba/viba-interpreter.md)），interpret 不带任何库函数——提示写给的正是要
  照着它把实现补出来的 agent。
- **每个要执行的函数都得拿到环境**：`__decl__` 里可以写 `$env Env` 这个参数，也可以不写 —— 写了就给
  这个参数，不写就随这次调用的结果往后走，直到落进某一个函数的 `$env Env` 那一处。规则也不例外。
- **环境不能当结果**：只有内建函数能把它声明成返回值，规则文件也一样写不了——要读环境就写
  `args.env`，别把环境当结果交出去（见 [`viba-interpreter.md`](viba/viba-interpreter.md)）。

## 2. 呈证给出实例

呈证是规则要判的那份实例，它自己也是一个程序：环境进、实例出。

**事实是问来的，不是写死的。** 呈证文件说的是"这个案子里有哪几件事"，不是"这几件事是什么"：它
定义一个函数（`at_1230`），函数的类型就是那份实例的写法，实现落在宿主侧——真实案子里读的是记录、
数据库或服务。所以换一份事实不用改呈证文件，换实现就行；同一份呈证也可以对着不同的实现跑。

```viba
# compliance/demo/case_at_1230.viba
__decl__ =
    ($victim ($x int * $y int) * $suspect ($x int * $y int) * $at str)
  <- $env Env

args = __get_args__ << __decl__

at_1230 =
    ($victim ($x int * $y int) * $suspect ($x int * $y int) * $at str)
  <- $env Env
  <- { where each of them was at 12:30, and when it was }

__impl__ = at_1230 << $env args.env
```

它给出的就是那份实例——受害人 (0,0)，嫌疑人 (3,4)，时刻 12:30，横竖各差 3 与 4 于是相距 5，
正好压在规则的门槛上。这条呈证给的是**事实**（谁在哪、什么时候），不是结论。

> 案子的值当然也可以直接写在文件里（`$victim ($x 0 * $y 0) * …`），那是同一个程序的最短写法，
> 适合钉住一个例子；把事实写进文件的那种呈证，只在那份事实就是常量时才对。

呈证的文件名就是案子的名字（[`case_at_1230.viba`](compliance/demo/case_at_1230.viba)：
那一刻），规则按这个名字调它：

```viba
the_case = case_at_1230 << case_env
```

呈证给出的是实例，规则要按数据路径读它：`$victim`、`$suspect`、`$at` 是数据路径，`$x`/`$y` 再往下一层。
读的工具在宿主侧，是 [`viba/reflect.py`](viba/viba/reflect.py)（[`viba-reflect.md`](viba/viba-reflect.md)）：
上面那段 [`host.py`](compliance/demo/host.py) 里的 `_point` 就是按数据路径读的
（`given.by_tag("victim").by_tag("x").leaf`）。呈证不必长得像规则：它就是事实。

[`host.py`](compliance/demo/host.py) 里 `at_1230` 的实现读的是一张表——演示里为了短；一个
真案子读的是记录或服务，那就是不纯的，得像测量一样把它记下来（`replayed` 写到案子自己的数据路径
下），否则一年后再判同一个案子，读到的事实可能已经变了。

## 3. 判定

```python
from compliance import is_compliant

verdict = is_compliant("rule_distance.viba", environ)   # -> 声明的 InterpretResult（viba 数据）
```

- 规则给出 `bool`，判定就是它：`$ok true` / `$ok false`（`verdict.by_tag("$ok")` 读出来的那个叶子）。
- 给出的不是 `bool`：这一次运行答的还是一个值，所以这一层当场拒绝（`compliance.Error`，
  "a verdict is a bool"）—— 那是**交进来的文件不是规则**，不是这次运行停在哪一步，所以它不装在
  `InterpretResult` 里，而是抛出来。
- 规则里某一步没人实现，则是**递延**：`interpret` 的 `$err InterpretError` 里那一支
  `$not_implemented_err UnderlyingOpErr`（读它先读 `$err`，再读 `$not_implemented_err` 那一支）。
  判定还没发生，这次规则不归这台机器跑完。它带着 `$module_path` /
  `$func_name`（哪条数据路径上的哪个定义）与 `$call`——`$call` 是**这次调用本身**、按它写下来的样子
  （可执行的那份），所以工单可以照它直接写出来，不必再跑一次。`record_run` 在这种情形下什么都不记进
  备份——没发生的判定不留下调用。
- 规则编不过、没有 `__impl__`、`$env` 没给……是 `$viba_program_err ProgramErr`；某一步的实现抛了、
  给出了没有叶子的东西，是 `$underlying_viba_op_err UnderlyingOpErr`。两者的 `$msg` 一句话说清
  是什么事；`$call` 是那次调用本身，写成能再跑的形式。
- 一次运行的环境（`Environment`、storage、`get_func`）怎么给，见
  [`viba-interpreter.md`](viba/viba-interpreter.md)：
  `is_compliant` 就是 `interpret` 加"读出那个 bool"—— 它的答案就是 `interpret` 答的那份数据
  （`$ok <bool>` 或 `$err <why it stopped>`），只有"这文件不是规则"与"这存储记不了调用"两件事是
  这一层自己的拒绝（`compliance.Error`）。

## 4. 不纯的那一步：调用

程序里唯一不能保证"跑多少次都一样"的东西是宿主函数：它可能读时钟、掷骰子、调服务。
`measure_distance` 就是这样一个函数。它不能自己给出一个数就算了——那样结果不可回放。它走
`measure`：

```python
# compliance/demo/host.py
def measure_distance(self, env, evidence, case):
    def compute(given):
        victim = _point(given, "victim")
        suspect = _point(given, "suspect")
        return int(round(((victim[0] - suspect[0]) ** 2
                          + (victim[1] - suspect[1]) ** 2) ** 0.5))
    return measure(env, "measure_distance", case, compute, evidence=evidence)
```

`env` 是这次调用跑在哪个环境里——规则给的是临时环境，够用；这份调用记在哪个案子下，由 `evidence` 指定——它就是案子的环境。

`measure(environ, name, given, compute, evidence=None)` 做的事：

1. 读 `name` 那份**调用**。里面已经有 `$result` → **直接回放，`compute` 一次不调**；
2. 没有 → 调 `compute(given)`（不纯的那一步），把**这次调用**和它给出的值写进本轮 store，再给出结果。

**这份记录是"这一次调用"的存档**：调用本身（参数定了）与它给出的值，一个文件：

```viba
# <store>/root/case_at_1230/call/measure_distance.viba
value =
    $call (__dyn_call__ << "measure_distance" << (
        $victim ($x 0 * $y 0)
      * $suspect ($x 3 * $y 4)
      * $at "12:30"
    ))
  * $result 5
```

- 它是**序列化的 viba 数据**，不是 pickle：人读得懂，也能解析回实例。
- `$call` 是**这次调用本身**，按它写下来的样子：`__dyn_call__ << "<名字>" << <它拿到的>`。这是 viba
  给的那种写法（`UnderlyingOpErr.call` 就是它），**给一个环境就是执行它**——照它就能把这次调用再做
  一遍；环境不在里面，谁跑谁自己造（[`viba-interpreter.md`](viba/viba-interpreter.md)）。
- `$result` 是它给出的值，还没人给过就是 `nil`。文件里的 `$call` 压过现场传进来的 `given`：
  **被固定的那次调用才算数**。
- 路径是 `<案子路径>/call/<name>.viba`；`name` 由调用方取（同一个调用用同一个名字），
  所以上面这份记录的整个路径就在说：哪个案子、哪一次调用。
- 分布式那一层把同一份记录当工单用：一次运行停在自己实现不了的一步上，就把它交出来，
  调度写在它停下的数据路径上（`<数据路径>/call/<api>.viba`），另一边接过去把这次调用跑一遍、
  把 `$result` 填上（[`viba-distributed.md`](viba-distributed.md)）。

## 5. 备份与回放

一次运行读调用的规矩在 [`compliance/storage.py`](compliance/storage.py) 的 `CallStorage`：

- **读：先看本轮 store，再看备份**（`call_root_dir`）。备份是运行之前就存好的那份调用。
- **写：只进本轮 store，永不写备份**。运行不许改那份备份。

于是"量一次、判多次"：

| 运行 | 量距离 | 条件看到 | 结果 |
|---|---|---|---|
| 第一次（没有备份） | 量了一次：受害人 (0,0) 与嫌疑人 (3,4) | 5 | `$ok true` |
| `record_run` | 回放刚量过的那份 | 5 | `$ok true`，并把这次调用记进备份 |
| 之后每一次（有备份） | **一次都不走**，读备份里的 5 | 5 | `$ok true` |

把备份留下来的是**一次专门的运行**：

```python
from compliance import record_run

record_run("rule_distance.viba", environ)   # 跑一遍，把它量过的调用记进备份
```

[`tests/data/compliance/backup/`](tests/data/compliance/backup/) 里放着一份事先备份好的
记录（`root/case_at_1230/call/measure_distance.viba`）：拿它当 `call_root_dir` 运行，
那条不纯的路一次都不走，判定仍是同一个。

**换一个案子**（比如 12:10 那一刻，嫌疑人在 (0,3)）：呈证写成 `case_at_1210.viba`，规则里
`case_env` 换成 `args.env.sub_env << args.env << "case_at_1210"`——量出来 3，判定 `$ok false`。名字换了，
环境与证据也跟着换到 `root/case_at_1210` 下面，两起案子不会互相踩到对方的记录。

## 6. 句柄一览

判定与测量（[`compliance/judge.py`](compliance/judge.py)）：

```python
is_compliant(rule_file, environ) -> InterpretResult  # 跑规则，读它的判定（声明的数据）
record_run(rule_file, environ)                                # 跑一遍，并把量过的调用记进备份
measure(environ, name, given, compute, evidence=None)          # 量一次：有结果就回放，没有就量并存
```

直接读写一份调用：

```python
call_path(name)                     # 它在 store 里的名字：call/<name>
read_call(environ, name)            # 存着的那份，或 None
record_call(environ, name, call, result=None)   # 写进本轮 store
result_of(call)                     # (值, True)；还没人给过是 (None, False)
call_of(call)                       # 这次调用本身（可执行的那份），或 None
given_of(call)                      # 它拿到的实参，或 None
the_call(name, *given)              # 现造一份可执行的调用：__dyn_call__ << "<name>" << …
```

storage：

```python
CallStorage(cur_storage_path, sub_storage=None,
                store_root_dir=None, call_root_dir=None)
read_text(file_path)      # 本轮 store，然后备份；都没有是 None
write_text(file_path, content)           # 只写本轮 store
record_text(file_path, content)          # 写进备份本身（record_run 用它）
```

## 7. 自己写一份

1. **给案子起个名字**：这个名字会同时是呈证的模块名、规则的子环境名与数据路径
   （`case_at_1230`）。案子多起来之后，这条路径就是证据的归属。
2. **写呈证**：一个模块（`<案子>.viba`），`__impl__` 是实例。事实从函数问来——定义一个
   函数，它的类型就是那份实例的写法，实现交给宿主（第 2 节）；只有真的是常量的东西才写进文件。
3. **写规则**：一个模块，`__impl__` 是 `bool`；一步一个定义（案子的数据路径、呈证、测量、判定），
   别把调用套进调用里；条件写成它自己的函数，每个函数带 `$env Environment`。
4. **实现宿主那侧**：这一步是交给 agent 的——照着文件里 `{...}` 的提示，把每个函数写出来。
   `get_func(module_path, func_name)` 给出这些函数的实现；纯的照常写，
   不纯的用 `measure` 包住，名字取"量的是什么"（它也是那份记录的文件名），并收一个槽位
   `$evidence Environment`——它是案子的数据路径，记录记在那里。
5. **跑判定**：给一个 `Environment`（storage + compute）。要留证据就 `record_run` 一次，
   之后每次 `is_compliant` 都读备份。规则里的函数调用给临时环境，只有读呈证与记证据才用
   案子的数据路径。
6. **要检查实例**：用 [`viba/reflect.py`](viba/viba/reflect.py) 的数据路径与叶子读
   （[`viba-reflect.md`](viba/viba-reflect.md)），或 `read_call` 直接读存档。

[`tests/test_compliance.py`](tests/test_compliance.py) 是一份可以照抄的完整例子；
[`compliance/demo/`](compliance/demo/) 是上面这套的最小可运行版本。
