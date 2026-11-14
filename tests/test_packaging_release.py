"""Tests of the release steps (``packaging/release.py``) and their workflow."""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
RELEASE = ROOT / "packaging" / "release.py"
WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"
TAG = "v9.9.9"
ZIP = "ddviz-9.9.9-win-x64.zip"


def _load_release() -> ModuleType:
    """Load ``packaging/release.py``, which is not in a package.

    Returns
    -------
    ModuleType
        The module.
    """
    spec = importlib.util.spec_from_file_location("ddviz_release", RELEASE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


release = _load_release()


class FakeGh:
    """A ``gh`` that records the commands and keeps the state of one release.

    Parameters
    ----------
    state : str
        The state of the release at the start: ``none``, ``draft`` or
        ``published``.
    fail : str, optional
        The ``gh release`` subcommand that fails (e.g. ``upload``).
    """

    def __init__(self, state: str, fail: str | None = None) -> None:
        self.state = state
        self.fail = fail
        self.calls: list[str] = []

    def __call__(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        """Run a ``gh release`` command against the fake release.

        Parameters
        ----------
        args : list of str
            Arguments after ``gh``.

        Returns
        -------
        subprocess.CompletedProcess of str
            The result the real ``gh`` would give.
        """
        assert args[0] == "release" and args[2] == TAG
        command = args[1]
        self.calls.append(command)
        if command == self.fail:
            return subprocess.CompletedProcess(args, 1, "", "HTTP 502")
        if command == "view":
            if self.state == "none":
                return subprocess.CompletedProcess(args, 1, "", "release not found\n")
            out = json.dumps({"isDraft": self.state == "draft"})
            return subprocess.CompletedProcess(args, 0, out, "")
        if command == "create":
            assert "--draft" in args and "--verify-tag" in args
            assert self.state == "none"
            self.state = "draft"
        elif command == "upload":
            assert args[3] == ZIP and "--clobber" in args
            assert self.state != "none"
        elif command == "edit":
            assert args[3:] == ["--draft=false"]
            self.state = "published"
        return subprocess.CompletedProcess(args, 0, "", "")


def test_new_release_is_drafted_attached_then_published() -> None:
    """A new release is a draft until the zip is attached."""
    gh = FakeGh("none")
    assert release.main(["publish", "--tag", TAG, "--zip", ZIP], gh=gh) == 0
    assert gh.calls == ["view", "create", "upload", "edit"]
    assert gh.state == "published"


def test_failed_upload_does_not_publish() -> None:
    """When the attachment fails, the command fails and the draft stays."""
    gh = FakeGh("none", fail="upload")
    assert release.main(["publish", "--tag", TAG, "--zip", ZIP], gh=gh) != 0
    assert gh.calls == ["view", "create", "upload"]
    assert gh.state == "draft"


def test_failed_draft_is_not_uploaded() -> None:
    """When the draft cannot be created, nothing else runs."""
    gh = FakeGh("none", fail="create")
    assert release.main(["publish", "--tag", TAG, "--zip", ZIP], gh=gh) != 0
    assert gh.calls == ["view", "create"]


def test_retry_reuses_the_draft() -> None:
    """A retry attaches to the draft left by a failed run, then publishes it."""
    gh = FakeGh("draft")
    assert release.main(["publish", "--tag", TAG, "--zip", ZIP], gh=gh) == 0
    assert gh.calls == ["view", "upload", "edit"]
    assert gh.state == "published"


def test_published_release_only_replaces_the_zip() -> None:
    """A manual run for a published release replaces the zip only."""
    gh = FakeGh("published")
    assert release.main(["publish", "--tag", TAG, "--zip", ZIP], gh=gh) == 0
    assert gh.calls == ["view", "upload"]


def test_view_error_is_not_taken_as_no_release() -> None:
    """A failure of ``gh release view`` other than not found stops the run."""
    gh = FakeGh("none", fail="view")
    assert release.main(["publish", "--tag", TAG, "--zip", ZIP], gh=gh) != 0
    assert gh.calls == ["view"]


@pytest.mark.parametrize(
    ("state", "event", "build"),
    [
        ("none", "push", "true"),
        ("draft", "push", "true"),
        ("published", "push", "false"),
        ("none", "workflow_dispatch", "true"),
        ("draft", "workflow_dispatch", "true"),
        ("published", "workflow_dispatch", "true"),
    ],
)
def test_state_decides_the_build(capsys: pytest.CaptureFixture[str], state: str, event: str, build: str) -> None:
    """Only a push for a published release skips the build."""
    gh = FakeGh(state)
    assert release.main(["state", "--tag", TAG, "--event", event], gh=gh) == 0
    assert capsys.readouterr().out.splitlines() == [f"state={state}", f"build={build}"]
    assert gh.calls == ["view"]


def _job(name: str) -> str:
    """Return the lines of a job of ``release.yml``.

    Parameters
    ----------
    name : str
        The job's key under ``jobs:``.

    Returns
    -------
    str
        The job's lines, up to the next job.
    """
    text = WORKFLOW.read_text(encoding="utf-8")
    match = re.search(rf"^  {name}:\n(.*?)(?=^  \S|\Z)", text, re.MULTILINE | re.DOTALL)
    assert match is not None
    return match.group(1)


def test_publish_runs_only_after_a_successful_build() -> None:
    """The publish job needs the exe job (build and smoke test) and has no ``if:``.

    Without an ``if:``, a job runs only when every job it needs succeeded, so
    a failed or skipped build never reaches the release steps.
    """
    publish = _job("publish")
    assert re.search(r"^    needs: \[tag, exe\]$", publish, re.MULTILINE)
    assert not re.search(r"^    if:", publish, re.MULTILINE)
    assert "packaging/release.py publish" in publish
    exe = _job("exe")
    assert "uses: ./.github/workflows/exe.yml" in exe
    assert "ref: ${{ needs.tag.outputs.tag }}" in exe
    assert "if: needs.tag.outputs.build == 'true'" in exe


def test_exe_smoke_tests_before_zipping() -> None:
    """``exe.yml`` runs the smoke test before it zips and uploads the exe."""
    text = (ROOT / ".github" / "workflows" / "exe.yml").read_text(encoding="utf-8")
    assert text.index("packaging/build.py") < text.index("packaging/smoke.py") < text.index("name: Zip")
