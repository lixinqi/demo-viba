"""Where a piece of code is, and what a run refuses to do about it.

A ticket names the viba it was written against and the commit each handler's api is at
(`ticket_system/tickets.py`). Naming one is not enough: the run has to be **at** it, or
the answer is another version's answer. So both sides of a run are read off the file
system before anything is executed:

- the viba **interpreter** the ticket names — `$viba_interpreter_repo_commit_id`, which the
  package this process runs has to be at, because that is what reads and runs the program;
- the **norm repo** the call is written in — `$norm_repo_commit_id` with `$norm_repo_path`;
- the handler's own code — `$handler_name2api_repo_commit_id`, because that code is what
  answers the call.

`git_commit` is how a place is read; `Error` is what is raised when it cannot be. What
counts as a mismatch, and what is merely unnamed, is `ticket_system.handler`.
"""

import subprocess
from pathlib import Path


class Error(RuntimeError):
    """A place's commit could not be read: the run cannot be pinned to it."""


def git_commit(path, what: str, ticket_uid: str) -> str:
    """The commit the checkout at (or above) `path` is at.

    A file path works as well as a directory: git looks upward for the repository, so a
    handler's own module names the repository its api was loaded from. A place that is
    no checkout, or a `git` that is not there, is an `Error` — and an error here is a
    stop, not a shrug: a run that cannot say which version it is at is not the run the
    ticket asked for.
    """
    if not path:
        raise Error(f"there is no {what} to read a commit from — the ticket "
                    f"{ticket_uid!r} has to be run at the version it names")
    here = Path(path)
    where = str(here if here.is_dir() else here.parent)
    try:
        done = subprocess.run(["git", "-C", where, "rev-parse", "HEAD"],
                              capture_output=True, text=True, timeout=30)
    except FileNotFoundError:
        raise Error(f"there is no git to read {what} ({where}) with, and ticket "
                    f"{ticket_uid!r} has to be run at the version it names") from None
    except subprocess.TimeoutExpired:
        raise Error(f"reading {what} ({where}) took too long") from None
    if done.returncode != 0 or not done.stdout.strip():
        raise Error(f"{where} is no checkout to read {what} from, and ticket "
                    f"{ticket_uid!r} has to be run at the version it names")
    return done.stdout.strip()


def is_clean_at(path, commit: str) -> bool:
    """Is the code at `path` at that commit, with nothing uncommitted in it?

    That is what says a run may read it where it stands: a commit it is not at (or edits
    on top of that commit, in that path) is not the version the ticket names, and the run
    makes itself a copy instead (`ticket_system/repo.py`).

    The question is asked about **that path**, not about the whole repository: `$norm_repo_path`
    may be one directory of a repository that holds several things (`viba_ticket/two_handlers/`
    of this repository, say), and an edit elsewhere in it is somebody else's work on another
    part of the tree. Untracked files are not counted, here or anywhere: a file git has never
    seen is in no commit, so there is no version of it to be at.
    """
    where = Path(path)
    where = where if where.is_dir() else where.parent
    try:
        head = subprocess.run(["git", "-C", str(where), "rev-parse", "HEAD"],
                              capture_output=True, text=True, timeout=30)
        if head.returncode != 0 or head.stdout.strip() != str(commit):
            return False
        dirty = subprocess.run(["git", "-C", str(where), "status", "--porcelain",
                                "--untracked-files=no", "--", "."],
                               capture_output=True, text=True, timeout=60)
        return dirty.returncode == 0 and not dirty.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
