"""Reading one norm repo: a checkout at the commit a ticket names, and the code in it.

A ticket names **two** repositories, and they are two different things:

- `$viba_interpreter_repo_commit_id` + `$viba_interpreter_repo_path`: the viba
  **interpreter** — the python package that reads and runs programs. One process runs one
  interpreter, and the ticket says which it has to be (`handler.the_running_interpreter`);
- `$norm_repo_commit_id` + `$norm_repo_path`: the **norm repo** — the git repository the viba
  code is read from, and the directory inside it that holds that code. `$VIBA_PATH` is where
  a run looks the code up, and this module is what says **which commit** of it a run reads.

The two need not be one repository each: `$norm_repo_path` may be a directory of a repository
that holds other things too — `viba_ticket/two_handlers/` of **this** repository, say — and then
the commit is that repository's own (`git rev-parse HEAD` up there, which for those two is this
repository's commit).

This module is about that checkout, and nothing else. It does not hold a role's
capability table and it does not dispatch anything: a role's api module says which
norm-repo definitions that role serves, and runs them here (`ticket_system/README.md`).

The norm repo is read, never written. A commit it is not at — or edits on top of that commit
in that directory (`code.is_clean_at`) — means the code is **extracted** into a directory of its
own under the tickets path: `git read-tree` into a temporary index and `git checkout-index`
out of it. That writes nothing into the repository: no worktree, no index, no ref. The norm
repo is a place someone is working in, and a run has no business leaving anything there.
"""

import os
import subprocess
import tempfile
from pathlib import Path

from viba.interpret import (Environment, EnvironmentStorage, interpret, sub_env)
from viba.type import ERR_TAG, OK_TAG, VibaProgramErr

from ticket_system import code

# The name of the child environment a generated program runs at, under the call's own.
NORM_ENVIRONMENT = "norm"


class NormRepo:
    """The norm code one run reads: where it is, which commit, and the tree it is read from."""

    def __init__(self, path, commit, store):
        self.path = Path(path)
        self.commit = str(commit) if commit else None
        self.store = Path(store)
        self._checkout = None
        self._where = None
        self._repo = None

    @property
    def checkout(self) -> Path:
        """The tree at the commit the ticket names — read once, then reused.

        A commit the code is already at, with nothing uncommitted in that directory
        (`code.is_clean_at`), is read where it stands — that tree is the repository itself, and
        `where` inside it is `$norm_repo_path`. Any other one is extracted into a directory of
        its own under the tickets path (`_extract`), so two tickets naming the same commit read
        the same copy — and the repository is not written to at all.

        What comes back is the **root** of that tree. Where the norm code sits inside it is
        `where`; `code` is the two together, and that is the directory a run reads modules from.
        """
        if self._checkout is not None:
            return self._checkout
        if self.commit is None or code.is_clean_at(self.path, self.commit):
            # 就地读：那棵树就是这个 repository 本身，树根是它的根，代码在 `where` 那一处。
            self._checkout = self.the_repo
        else:
            # 抽一份：树根是抽出来那棵树的根，代码还是在同一个 `where` 那一处。
            self._checkout = self._extract()
        return self._checkout

    @property
    def where(self) -> str:
        """Where the norm code sits inside its repository: `''`, or `a/b/` with a slash.

        It is `$norm_repo_path` read against the repository it is in (`git rev-parse
        --show-prefix`), so a norm repo that is one directory of a bigger repository reads its
        own directory of whichever tree the commit is read from.
        """
        if self._where is None:
            self._where = self._prefix()
        return self._where

    @property
    def code(self) -> Path:
        """The directory the norm code is read from: the tree, and `where` inside it."""
        return self.checkout / self.where

    def _prefix(self) -> str:
        """`git rev-parse --show-prefix` at `$norm_repo_path`: where it is in its repo.

        A path that is no checkout at all is a stop (`code.Error`): the run cannot say where
        in a repository this code is, so it cannot read it at a commit either.
        """
        here = self.path if self.path.is_dir() else self.path.parent
        done = subprocess.run(["git", "-C", str(here), "rev-parse", "--show-prefix"],
                              capture_output=True, text=True, timeout=30)
        if done.returncode != 0:
            raise code.Error(f"{here} is no checkout, so the norm code at {self.path} has "
                             f"no commit to be read at")
        return done.stdout.strip()

    @property
    def the_repo(self) -> Path:
        """The repository the code is in: git looks upward from `$norm_repo_path`."""
        if self._repo is not None:
            return self._repo
        here = self.path if self.path.is_dir() else self.path.parent
        done = subprocess.run(["git", "-C", str(here), "rev-parse", "--show-toplevel"],
                              capture_output=True, text=True, timeout=30)
        if done.returncode != 0 or not done.stdout.strip():
            raise code.Error(f"{here} is no checkout, so there is no repository to read "
                             f"{self.path} from")
        self._repo = Path(done.stdout.strip())
        return self._repo

    def _extract(self) -> Path:
        """This commit's tree, written out under the tickets path.

        The index is a temporary file of its own (`GIT_INDEX_FILE`), so the repo's own
        index, refs and worktrees are untouched: this writes into the directory it is
        handed, and reads the repo. The tree is written out whole, so its root is the
        repository's root and `where` is the same inside it.
        """
        place = self.store / "_norm" / f"{self.the_repo.name}-{self.commit[:12]}"
        marker = place / ".the-commit"
        if marker.is_file() and marker.read_text().strip() == str(self.commit):
            return place
        place.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(prefix="norm-index-", delete=False) as index:
            index_path = index.name
        try:
            environment = dict(os.environ, GIT_INDEX_FILE=index_path)
            self._git(environment, "read-tree", self.commit)
            self._git(environment, "checkout-index", "--all", "--force",
                      f"--prefix={place}{os.sep}")
        finally:
            try:
                os.unlink(index_path)
            except OSError:
                pass
        marker.write_text(str(self.commit))
        return place

    def _git(self, environment, *arguments: str) -> None:
        """One git read of this repo, in that environment; a failure is a stop."""
        done = subprocess.run(["git", "-C", str(self.the_repo), *arguments],
                              capture_output=True, text=True, timeout=300,
                              env=environment)
        if done.returncode != 0:
            raise code.Error(
                f"the norm repo {self.path} has no tree to read for commit "
                f"{self.commit!r}: {(done.stderr or done.stdout).strip()[-200:]}")

    def viba_path(self) -> str:
        """Where a run of this code looks its modules up: the code's own directory."""
        return str(self.code)

    def has(self, module: str) -> bool:
        """Is there a `<module>.viba` in the norm code? That is what a `$call` name needs."""
        return (self.code / f"{module}.viba").is_file()


def run_definition(repo: "NormRepo", module: str, definition: str, environ: Environment,
                   given: list):
    """Run `<module>.<definition>` of this repo, given these arguments, in this environment.

    The program is written for this one call — the arguments are the literals the ticket
    wrote — and run through the interpreter (`interpret`), at a sub-environment of the
    call's own so that the program and the definition it calls cannot land on one storage
    path. It is the interpreter the ticket named that runs it: a norm definition is a viba
    program, and this is the only way it is ever run.
    """
    source = ("__decl__ = Any <- $env Env\n"
              "args = __get_args__ << __decl__\n"
              f"import {module} as the_code\n"
              f'__impl__ = the_code << (args.env.sub_env << args.env << "{definition}")'
              + "".join(f" << $x {_literal(one)}" for one in given) + "\n")
    # The generated program is written outside the norm repo: a run reads that repository
    # and writes nothing into it — not this, and not a snapshot (`environ` carries the
    # ticket's own storage). The program is found through `viba_path`, not by where its own
    # file lies, so it may live anywhere.
    with tempfile.NamedTemporaryFile("w", suffix=".viba", delete=False) as written:
        written.write(source)
        place = Path(written.name)
    try:
        answer = interpret(str(place), _the_environment(environ, repo))
    finally:
        try:
            place.unlink()
        except OSError:
            pass
    return _the_value(answer)


def _the_environment(environ: Environment, repo: "NormRepo") -> Environment:
    """The environment a generated program runs at: a child of the call's own.

    Its search path is the norm repo's checkout, its storage is a child of the call's, and
    its compute side is the call's own — the program's imports and the definitions it
    calls are read from this repo, and a name neither the role nor the builtin table
    answers is still nobody's.
    """
    child = sub_env(environ, NORM_ENVIRONMENT)
    child.viba_path = repo.viba_path()
    return child


def _the_value(answer):
    """The norm run's answer, as the value the step is answered with.

    A run answers the declared `InterpretResult` as viba data (`viba.interpret`), so
    this reads the branch:

    - `$ok <值>`：把那个值本身答回去（宿主答一个 `VObject`，viba 就当它是这个值）；
    - `$err ($not_implemented_err …)` / `$err ($underlying_viba_op_err …)`：**把那份失败
      原样答回去** —— 一次运行在自己里面转发一次失败（`viba.interpret._completed`），
      所以停下来的仍然是 norm 代码里那一步，它自己的模块、整名与 `$call` 都留着；
    - `$err` 的另外两支（程序跑不起来、环境的 api 收不下）不是「哪一步没有实现」，
      这里抛出去，让它按「这个实现坏了」记下来（`raised: …`）。
    """
    if answer.data.tag == OK_TAG:
        return answer.by_tag(OK_TAG)
    stop = answer.by_tag(ERR_TAG)
    if stop.data.tag in ("$not_implemented_err", "$underlying_viba_op_err"):
        return stop
    raise RuntimeError(f"the norm code did not run: {_the_reason(stop)}")


def _the_reason(stop) -> str:
    """One stop's `$msg`, for the sentence above."""
    given = stop.by_tag(stop.data.tag)
    if given is None:
        return str(stop.data.tag)
    return str(given.by_tag("$msg").leaf)


def _literal(value) -> str:
    """One argument as the viba literal it is written as."""
    from viba import serialize, viba_ast
    from viba.interpret import viba_data

    data = value if isinstance(value, viba_ast.AST) else getattr(value, "data", value)
    if data is None or isinstance(data, viba_ast.Nil):
        return "nil"
    if isinstance(data, viba_ast.Constant):
        return _scalar(data.value)
    written = serialize.serialize("value", viba_data(data))
    if isinstance(written, VibaProgramErr):
        raise code.Error(f"cannot write this argument as viba code: {written.msg}")
    return "(" + written.ok_value.split("=", 1)[1].strip() + ")"


def _scalar(value) -> str:
    """nil, or one of viba's four literals, as viba source."""
    if value is None:
        return "nil"
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, str):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return str(value)
