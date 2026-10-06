"""The store a rule runs against: its own writes, and the Prepare backup.

A *Prepare* is the call a measurement was made of — the arguments fixed, the
result declared — kept as a file in the store. The one a run is handed was
backed up before it started (that is what makes the run repeatable); so:

- reading `prepare/...` looks at what this run wrote first, and at the backup
  second — a run replays the evidence it was given, and can still write its own;
- writing `prepare/...` goes into this run's store and never into the backup:
  the backup is the evidence, and a run does not get to rewrite it.

Recording a backup is a separate, deliberate act: `record_text` (see
`compliance.judge.prepare_run`).
"""

from pathlib import Path
from typing import Optional

from viba.interpret import EnvironmentStorage

# A Prepare is named `prepare/<name>` (that is what `judge.prepare_path` builds)
# and lands in the store under the storage's own path, so the segment is what
# tells one from an ordinary snapshot: `<storage-path>/prepare/<name>.viba`.
PREPARE_PREFIX = "prepare/"
PREPARE_SEGMENT = "prepare"


class PreparedStorage(EnvironmentStorage):
    """A store whose Prepare files are backed up: read the backup, write your own."""

    __slots__ = ("prepare_root_dir",)

    def __init__(self, cur_storage_path: str, sub_storage: Optional[dict] = None,
                 store_root_dir: Optional[str] = None, prepare_root_dir: Optional[str] = None):
        super().__init__(cur_storage_path, sub_storage, store_root_dir)
        self.prepare_root_dir = prepare_root_dir

    def sub(self, name: str) -> "PreparedStorage":
        if name not in self.sub_storage:
            path = f"{self.cur_storage_path}/{name}" if self.cur_storage_path else name
            self.sub_storage[name] = type(self)(path, None, self.store_root_dir,
                                                self.prepare_root_dir)
        return self.sub_storage[name]

    def is_prepare(self, file_path: str) -> bool:
        """Is this store path a Prepare? (`root/prepare/distance.viba` is.)"""
        parts = [part for part in str(file_path).split("/") if part]
        return PREPARE_SEGMENT in parts

    def read_text(self, file_path: str):
        """This run's text, then the backup's; None when neither has it."""
        if self.prepare_root_dir is None or not self.is_prepare(file_path):
            return super().read_text(file_path)
        own = super().read_text(file_path)
        if own is not None:
            return own
        return self._read_under(self._store_path(file_path, self.prepare_root_dir))

    def write_text(self, file_path: str, content: str) -> None:
        """Always this run's store: the backup is not a run's to write."""
        super().write_text(file_path, content)

    def record_text(self, file_path: str, content: str) -> None:
        """Write into the backup itself: how a Prepare comes to be backed up."""
        if self.prepare_root_dir is None:
            raise RuntimeError("this storage has no prepare backup to record into")
        path = self._store_path(file_path, self.prepare_root_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    def _read_under(self, path: Path):
        try:
            return path.read_text()
        except FileNotFoundError:
            return None
