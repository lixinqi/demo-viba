"""章节里的 viba 代码块：读到的每一块都要编得过。

`viba-compliance.md`、`viba-distributed.md`、`distributed/README.md` 与 `demo/distributed/` 下四份
README 里的 ```viba 块是写给别人照抄的，一块编不过就是在教一个错。viba 仓库那边的自检
（`viba/parser.py` 的 `__main__`）只查它自己那几份文档；这两层搬到这个仓库以后，它们的 viba
代码块归这个套件查。

    python3 tests/test_documents.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "viba"))

from interpreter_support import Checks

from viba.parser import check_definition_names, parse_source

checks = Checks("documents")
check = checks.check

# 这两层自己的文档。哪一份暂时没有 ```viba 块也留着：以后补上一块，这里就查得到。
DOCUMENTS = ("viba-compliance.md",
             "viba-distributed.md",
             "distributed/README.md",
             "demo/distributed/README.md",
             "demo/distributed/naive/README.md",
             "demo/distributed/delivery/README.md",
             "demo/distributed/reading/README.md")


def viba_blocks(text: str) -> list:
    """Every fenced block in `text` labelled `viba`, verbatim."""
    blocks = []
    inside = False
    wanted = False
    current = []
    for line in text.splitlines():
        if line.startswith("```"):
            if inside:
                if wanted:
                    blocks.append("\n".join(current))
                inside = wanted = False
                current = []
            else:
                inside = True
                wanted = line[3:].strip() == "viba"
            continue
        if inside:
            current.append(line)
    return blocks


def one_document(name: str) -> int:
    """Check every viba block in one document; answer how many there were."""
    blocks = viba_blocks((ROOT / name).read_text(encoding="utf-8"))
    for index, block in enumerate(blocks):
        try:
            check_definition_names(parse_source(block) or [])
            check(True, f"{name} block {index} compiles")
        except Exception as exc:                # one bad sample, not the rest
            check(False, f"{name} block {index}: {type(exc).__name__}: {exc}")
    return len(blocks)


def main() -> int:
    total = sum(one_document(name) for name in DOCUMENTS)
    check(total > 0, "the documents still hold viba blocks to check")
    return checks.report()


if __name__ == "__main__":
    sys.exit(main())
