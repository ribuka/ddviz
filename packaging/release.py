"""Decide and carry out the GitHub release steps of ``.github/workflows/release.yml``.

Two commands, each run with ``uv run --no-project packaging/release.py``:

- ``state --tag v<VERSION> --event <push|workflow_dispatch>`` prints, as
  ``key=value`` lines for ``$GITHUB_OUTPUT``, the state of the tag's release
  (``none``, ``draft`` or ``published``) and whether to build the exe. A push
  for a published release builds nothing; a manual run rebuilds it.
- ``publish --tag v<VERSION> --zip <zip>`` creates the release as a draft
  when there is none (it reuses a draft left by an earlier run), attaches the
  zip (replacing one of the same name) and then publishes the draft. When the
  release is already published, it only replaces the zip. If a step fails, it
  stops with a non-zero exit code before the release is published.

``gh`` needs ``GH_TOKEN`` and, outside a checkout, ``GH_REPO``.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Callable, Sequence

Gh = Callable[[list[str]], subprocess.CompletedProcess[str]]

NONE = "none"
DRAFT = "draft"
PUBLISHED = "published"


class GhError(RuntimeError):
    """A ``gh`` command that failed."""


def run_gh(args: list[str]) -> subprocess.CompletedProcess[str]:
    """Run ``gh`` with ``args``, capturing its output.

    Parameters
    ----------
    args : list of str
        Arguments after ``gh``.

    Returns
    -------
    subprocess.CompletedProcess of str
        The finished process; it is not checked.
    """
    return subprocess.run(["gh", *args], capture_output=True, text=True, check=False)


def _check(gh: Gh, args: list[str]) -> str:
    """Run ``gh`` and fail unless it exits with 0.

    Parameters
    ----------
    gh : Gh
        Runs ``gh``.
    args : list of str
        Arguments after ``gh``.

    Returns
    -------
    str
        Its standard output.

    Raises
    ------
    GhError
        If it exits with a non-zero code.
    """
    done = gh(args)
    if done.returncode != 0:
        raise GhError(f"gh {' '.join(args)} failed ({done.returncode}): {done.stderr.strip()}")
    return done.stdout


def release_state(gh: Gh, tag: str) -> str:
    """Read the state of the release of ``tag``.

    Parameters
    ----------
    gh : Gh
        Runs ``gh``.
    tag : str
        The tag, ``v<VERSION>``.

    Returns
    -------
    str
        ``none`` when the tag has no release, ``draft`` or ``published``.

    Raises
    ------
    GhError
        If ``gh`` fails for another reason than a missing release.
    """
    done = gh(["release", "view", tag, "--json", "isDraft"])
    if done.returncode != 0:
        if "release not found" in done.stderr:
            return NONE
        raise GhError(f"gh release view {tag} failed ({done.returncode}): {done.stderr.strip()}")
    return DRAFT if json.loads(done.stdout)["isDraft"] else PUBLISHED


def should_build(state: str, event: str) -> bool:
    """Tell whether a run builds and attaches the exe.

    Parameters
    ----------
    state : str
        The state of the release (``release_state``).
    event : str
        The event of the run, ``push`` or ``workflow_dispatch``.

    Returns
    -------
    bool
        False only for a push when the release is already published.
    """
    return not (state == PUBLISHED and event == "push")


def publish(gh: Gh, tag: str, zip_path: str) -> None:
    """Attach the zip to the release of ``tag`` and publish it.

    Parameters
    ----------
    gh : Gh
        Runs ``gh``.
    tag : str
        The tag, ``v<VERSION>``; it must exist on the remote.
    zip_path : str
        The zip to attach, ``ddviz-<VERSION>-win-x64.zip``.

    Raises
    ------
    GhError
        If a ``gh`` command fails; the release is then not published.
    """
    state = release_state(gh, tag)
    if state == NONE:
        _check(gh, ["release", "create", tag, "--draft", "--verify-tag", "--title", tag, "--generate-notes"])
    _check(gh, ["release", "upload", tag, zip_path, "--clobber"])
    if state != PUBLISHED:
        _check(gh, ["release", "edit", tag, "--draft=false"])


def main(argv: Sequence[str] | None = None, gh: Gh = run_gh) -> int:
    """Run a command.

    Parameters
    ----------
    argv : sequence of str, optional
        Arguments; ``sys.argv[1:]`` when omitted.
    gh : Gh, optional
        Runs ``gh``; tests pass one that records the commands.

    Returns
    -------
    int
        The exit code: 0 on success, 1 when a ``gh`` command failed.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    state_parser = commands.add_parser("state")
    state_parser.add_argument("--tag", required=True)
    state_parser.add_argument("--event", required=True, choices=["push", "workflow_dispatch"])
    publish_parser = commands.add_parser("publish")
    publish_parser.add_argument("--tag", required=True)
    publish_parser.add_argument("--zip", required=True)
    args = parser.parse_args(argv)

    try:
        if args.command == "state":
            state = release_state(gh, args.tag)
            print(f"state={state}")
            print(f"build={str(should_build(state, args.event)).lower()}")
        else:
            publish(gh, args.tag, args.zip)
    except GhError as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
