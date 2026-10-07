"""The scheduler: start every handler process, and stop them when the work is done.

One run of this is one system: a tickets path, and a handler process for each
`--handler NAME=MODULE:FUNCTION`. Every handler polls the same tickets path once a
second; each one takes the tickets it can answer, logs the attempt, and leaves the rest
alone. Nothing is handed out and nothing is waited for: the store — the tickets path —
is the only thing they share.

The run ends when **every ticket's progress holds a `$ok`** (`progress.finished`), and
not before: a handler process that ends on its own is restarted, because a system is
not finished because one of its processes got tired. `--seconds` is the cap; a run that
reaches it reports `unfinished` and stops the handlers.

The outcome is one JSON line: `ok` when every ticket finished, `unfinished` when the
cap was reached, `crashed` when a handler process could not be started. Each handler's
own report (its JSON line) is read when the handler ends and carried under `reports`.

    python3 -m ticket_system.scheduler --tickets <tickets path> \\
        --handler adder=my_package.adder:the_api \\
        --handler doubler=my_package.doubler:the_api
"""

import argparse
import json
import signal
import subprocess
import sys
import time
from pathlib import Path

from ticket_system import progress, tickets

# How long one round waits: the same second the handlers poll at.
INTERVAL = 1.0


class OneHandler:
    """One handler process of the system: how to start it, and how it is doing."""

    def __init__(self, name: str, spec: str, tickets_path, interval: float):
        self.name = name
        self.spec = spec
        self.tickets_path = str(tickets_path)
        self.interval = interval
        self.process = None
        self.reports = []
        self.restarts = 0

    def start(self):
        """Start this handler process."""
        command = [sys.executable, "-m", "ticket_system.handler",
                   "--tickets", self.tickets_path, "--handler", self.name,
                   "--api", self.spec, "--interval", str(self.interval)]
        self.process = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    def restart_if_ended(self, cap: int) -> dict:
        """When this handler ended on its own — the stop condition is the scheduler's.

        A handler that ends before every ticket is finished is started again: the
        system is not finished because one of its processes got tired. A handler
        that keeps ending is not started again and is reported as `crashed`: a
        process that cannot stay up is a failure to report, not a process to
        restart forever.
        """
        if self.process is None or self.process.poll() is None:
            return None
        out, err = self.process.communicate()
        self.reports += _json_lines(out)
        self.restarts += 1
        if self.restarts > cap:
            return {"handler": self.name, "result": "crashed", "restarts": cap,
                    "why": (err or out).strip()[-400:]}
        self.start()
        return {"handler": self.name, "result": "restarted",
                "restarts": self.restarts, "why": (err or out).strip()[-400:]}

    def stop(self) -> dict:
        """Stop this handler process, and read the report it printed."""
        if self.process is None:
            return {"handler": self.name, "result": "never started"}
        if self.process.poll() is None:
            self.process.send_signal(signal.SIGTERM)
            try:
                out, err = self.process.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                out, err = self.process.communicate()
        else:
            out, err = self.process.communicate()
        self.reports += _json_lines(out)
        return {"handler": self.name, "result": "stopped",
                "why": (err or "").strip()[-400:] or None}


def _json_lines(text: str) -> list:
    """Every JSON object on its own line of this text, in order."""
    lines = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            lines.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return lines


def the_handler(spec: str) -> tuple:
    """One `NAME=MODULE:FUNCTION` from the command line, as (name, spec).

    Nothing here says which commit the handler is at: its commit is read from the code
    it loads (`ticket_system/code.py`), because a version a process states about itself
    is the one thing the pinning exists to check.
    """
    name, _, rest = spec.partition("=")
    if not name or not rest:
        raise SystemExit(f"--handler wants NAME=MODULE:FUNCTION, not {spec!r}")
    return name, rest


def run(tickets_path, handlers, interval: float = INTERVAL, seconds: float = 600.0,
        restarts: int = 5):
    """Run the system over this tickets path until every ticket is finished.

    `paused` is the scheduler's own poll: it looks at the tickets path once per
    `interval`, and one round is never shorter than that, so a `--interval` of 0
    (which a test may want for speed) is still a loop, not a spin.
    """
    started = time.monotonic()
    paused = max(interval, 0.05)
    rounds = 0
    notes = []
    for one in handlers:
        one.start()
    try:
        while True:
            rounds += 1
            for one in handlers:
                note = one.restart_if_ended(restarts)
                if note is not None:
                    notes.append(note)
            broken = [one["handler"] for one in notes if one["result"] == "crashed"]
            if broken:
                outcome = {"outcome": "crashed", "rounds": rounds,
                           "handlers": broken}
                break
            if progress.finished(tickets_path):
                outcome = {"outcome": "ok", "rounds": rounds,
                           "handlers": [one.name for one in handlers],
                           "tickets": tickets.ticket_uids(tickets_path)}
                break
            if time.monotonic() - started >= seconds:
                outcome = {"outcome": "unfinished", "rounds": rounds,
                           "seconds": seconds,
                           "unfinished": [uid for uid
                                          in tickets.ticket_uids(tickets_path)
                                          if not progress.answered(tickets_path, uid)],
                           "tickets": progress.the_state(tickets_path)}
                break
            time.sleep(paused)
    finally:
        stops = [one.stop() for one in handlers]
    outcome["stopped"] = stops
    outcome["reports"] = [report for one in handlers for report in one.reports]
    outcome["notes"] = notes
    return outcome


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="run the handlers of a ticket processing system until it is done")
    parser.add_argument("--tickets", required=True, help="the tickets path")
    parser.add_argument("--handler", action="append", required=True,
                        metavar="NAME=MODULE:FUNCTION",
                        help="one handler process: its name, and the module and "
                             "function that build its capability table (repeat for "
                             "each handler)")
    parser.add_argument("--interval", type=float, default=INTERVAL,
                        help=f"seconds between two polls (default {INTERVAL})")
    parser.add_argument("--seconds", type=float, default=600.0,
                        help="the most seconds one run may take (default 600)")
    parser.add_argument("--restarts", type=int, default=5,
                        help="how often one handler process is started again before "
                             "it is reported as crashed (default 5)")
    options = parser.parse_args(argv)
    handlers = [OneHandler(name, spec, options.tickets, options.interval)
                for name, spec in (the_handler(one) for one in options.handler)]
    outcome = run(options.tickets, handlers, options.interval, options.seconds,
                  options.restarts)
    print(json.dumps(outcome), flush=True)
    return 0 if outcome["outcome"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
