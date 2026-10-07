"""The store a rule runs against: its own writes, and the call backup.

A *call* is a call written down as viba data — which call it was (its arguments
fixed) and what it answered (`$call` and `$result`, `nil` until something answers
it) — kept as a file in the store. The one a run is handed was backed up before it
started (that is what makes the run repeatable); so:

- reading `call/...` looks at what this run wrote first, and at the backup
  second — a run replays the evidence it was given, and can still write its own;
- writing `call/...` goes into this run's store and never into the backup:
  the backup is the evidence, and a run does not get to rewrite it.

Recording a backup is a separate, deliberate act: `record_text` (see
`compliance.judge.record_run`).
"""

from pathlib import Path
from typing import Optional

from viba.interpret import EnvironmentStorage

# A call is named `call/<name>` (that is what
# `judge.call_path` builds) and lands in the store under the storage's
# own path, so the segment is what tells one from an ordinary snapshot:
# `<storage-path>/call/<name>.viba`.
CALL_PREFIX = "call/"
CALL_SEGMENT = "call"


class CallStorage(EnvironmentStorage):
    """A store whose call files are backed up: read the backup, write your own."""

    __slots__ = ("call_root_dir",)

    def __init__(self, cur_storage_path: str, sub_storage: Optional[dict] = None,
                 store_root_dir: Optional[str] = None, call_root_dir: Optional[str] = None):
        super().__init__(cur_storage_path, sub_storage, store_root_dir)
        self.call_root_dir = call_root_dir

    def sub(self, name: str) -> "CallStorage":
        if name not in self.sub_storage:
            path = f"{self.cur_storage_path}/{name}" if self.cur_storage_path else name
            self.sub_storage[name] = type(self)(path, None, self.store_root_dir,
                                                self.call_root_dir)
        return self.sub_storage[name]

    def is_call(self, file_path: str) -> bool:
        """Is this store path a call? (`root/call/distance.viba` is.)"""
        parts = [part for part in str(file_path).split("/") if part]
        return CALL_SEGMENT in parts

    def read_text(self, file_path: str):
        """This run's text, then the backup's; None when neither has it."""
        if self.call_root_dir is None or not self.is_call(file_path):
            return super().read_text(file_path)
        own = super().read_text(file_path)
        if own is not None:
            return own
        return self._read_under(self._store_path(file_path, self.call_root_dir))

    def write_text(self, file_path: str, content: str) -> None:
        """Always this run's store: the backup is not a run's to write."""
        super().write_text(file_path, content)

    def record_text(self, file_path: str, content: str) -> None:
        """Write into the backup itself: how a call comes to be backed up."""
        if self.call_root_dir is None:
            raise RuntimeError("this storage has no call backup to record into")
        path = self._store_path(file_path, self.call_root_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    def _read_under(self, path: Path):
        try:
            return path.read_text()
        except FileNotFoundError:
            return None
