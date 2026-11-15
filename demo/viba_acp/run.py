"""Run the viba_acp demo end to end: one schedule, one service, one store.

    python3 demo/viba_acp/run.py                        # the scripted agent
    python3 demo/viba_acp/run.py --fresh                # start from an empty store

What it starts is `distributed.scheduler` over one service:

    acp   agent_service   the two ACP operations, spoken over ACP

and it leaves two things behind besides the store's own files: the schedule's reports
(one JSON line per round, on stdout) and the ACP messages, one JSON line per message,
in `--trace` (by default `<store>/agent-trace.jsonl`). `viba_acp/README.md` 第 3.1 节
与第 4 节 read those two outputs. What `build_source` writes under `<store>/source/` is
a build product: the documents are the source, and it is made again on every run.

This file sets `PYTHONPATH` for the service process it starts, so it runs from any
directory; the service is named by python module and must be importable there.
"""

import argparse
import os
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent    # demo/viba_acp
ROOT = HERE.parent.parent                 # the repository root
LAYER = ROOT / "viba_acp"                 # the interface, the service, the ACP client

DEFAULT_STORE = HERE / ".store"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="run the viba_acp demo")
    parser.add_argument("--store", default=str(DEFAULT_STORE),
                        help="the environment storage the rounds share "
                             "(default: demo/viba_acp/.store)")
    parser.add_argument("--trace", default=None,
                        help="where the ACP messages go, one JSON line per message "
                             "(default: <store>/agent-trace.jsonl)")
    parser.add_argument("--rounds", type=int, default=8,
                        help="the most rounds one schedule may take (default: 8)")
    parser.add_argument("--fresh", action="store_true",
                        help="remove the store before starting")
    options = parser.parse_args(argv)

    store = Path(options.store).expanduser().resolve()
    if options.fresh and store.exists():
        if store in (HERE, ROOT) or len(store.parts) < 3:
            raise SystemExit(f"refusing to remove {store}")
        shutil.rmtree(store)
    store.mkdir(parents=True, exist_ok=True)

    trace = (Path(options.trace).expanduser().resolve() if options.trace
             else store / "agent-trace.jsonl")
    trace.write_text("", encoding="utf-8")

    here_and_the_library = [str(LAYER), str(ROOT), str(ROOT / "viba")]
    os.environ["PYTHONPATH"] = os.pathsep.join(
        here_and_the_library
        + ([os.environ["PYTHONPATH"]] if os.environ.get("PYTHONPATH") else []))
    os.environ["VIBA_AGENT_TRACE"] = str(trace)
    sys.path[:0] = here_and_the_library

    from distributed import scheduler

    entry = build_source(store)
    print(f"store: {store}\ntrace: {trace}\nsource: {entry.parent}",
          file=sys.stderr)
    return scheduler.main([
        "--store", str(store),
        "--program", str(entry),
        "--service", "acp=agent_service",
        "--rounds", str(options.rounds),
    ])


def build_source(store: Path) -> Path:
    """Write the two modules the program needs, from the two documents.

    A document here is one module, divided into sections by its headings: every
    `viba` block, in order, is the module's source. The headings and the prose are
    the documentation; they do not enter the file. The documents stay the source;
    this directory is a build product, made again on every run.
    """
    source = store / "source" / "viba_acp"
    source.mkdir(parents=True, exist_ok=True)
    for document, name in ((ROOT / "viba_acp.viba.md", "acp.viba"),
                           (ROOT / "demo" / "viba_acp.viba.md",
                            "explain_then_shorten.viba")):
        (source / name).write_text(module_source(document), encoding="utf-8")
    return source / "explain_then_shorten.viba"


def module_source(document: Path) -> str:
    """The module a document stands for: its `viba` blocks, in order, joined."""
    blocks = []
    inside = wanted = False
    current = []
    for line in document.read_text(encoding="utf-8").splitlines():
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
    return "\n\n".join(blocks) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
