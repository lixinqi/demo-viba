"""distributed 各套件与 compliance 套件共用的计数器。

不是套件本身（没有 `__main__` 的跑法），`tests/` 下那几套从这里取：

    from interpreter_support import Checks

`Checks` 管每个套件自己的通过/失败计数与那一行汇总；失败会打出来。用例文件是
`tests/data/compliance/` 下的 `.viba` 文件，不写在这里。
"""


class Checks:
    """One suite's counter: `check` and the summary line."""

    def __init__(self, name: str):
        self.name = name
        self.passed = 0
        self.failures = 0

    def check(self, ok: bool, label: str):
        if ok:
            self.passed += 1
        else:
            self.failures += 1
            print(f"FAIL: {label}")

    def report(self) -> int:
        print(f"{self.name}: {self.passed} passed, {self.failures} failed")
        return 1 if self.failures else 0
