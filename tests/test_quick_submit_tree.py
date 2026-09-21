from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from tools import quick_submit_tree as tree_gate

SUBMISSION_ID = "01234567-89ab-4def-8123-456789abcdef"


def _git(worktree: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(worktree), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _submission_repository(
    tmp_path: Path, *, mode: str = "regular", add_extra: bool = False
) -> tuple[Path, str, str]:
    source = tmp_path / "source"
    source.mkdir()
    _git(source, "init", "-b", "main")
    _git(source, "config", "user.name", "Test")
    _git(source, "config", "user.email", "test@example.com")
    (source / "README.md").write_text("base\n")
    (source / "submissions").mkdir()
    _git(source, "add", "README.md", "submissions")
    _git(source, "commit", "-m", "base")
    base_sha = _git(source, "rev-parse", "HEAD")

    _git(source, "checkout", "-b", f"quick-submit-{SUBMISSION_ID}")
    scenario = source / "submissions" / f"{SUBMISSION_ID}.json"
    if mode == "symlink":
        os.symlink("../README.md", scenario)
    else:
        scenario.write_text('{"scenario":true}\n')
        if mode == "executable":
            scenario.chmod(0o755)
    _git(source, "add", f"submissions/{SUBMISSION_ID}.json")
    if add_extra:
        (source / ".gitattributes").write_text("* filter=evil\n")
        _git(source, "add", ".gitattributes")
    _git(source, "commit", "-m", "submission")
    return source, base_sha, _git(source, "rev-parse", "HEAD")


def _materialize(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    source: Path,
    base_sha: str,
    head_sha: str,
) -> tuple[Path, Path]:
    repository_url = source.as_uri()
    monkeypatch.setattr(tree_gate, "EXPECTED_REPOSITORY_URL", repository_url)
    repo_dir = tmp_path / "bare.git"
    output = tmp_path / "scenario.release.json"
    tree_gate.materialize_submission(
        repo_dir=repo_dir,
        repository_url=repository_url,
        head_sha=head_sha,
        base_sha=base_sha,
        submission_id=SUBMISSION_ID,
        output=output,
    )
    return repo_dir, output


def test_materializes_only_exact_regular_scenario_blob(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source, base_sha, head_sha = _submission_repository(tmp_path)
    _, output = _materialize(monkeypatch, tmp_path, source, base_sha, head_sha)
    assert output.read_text() == '{"scenario":true}\n'
    assert not output.is_symlink()


@pytest.mark.parametrize("mode", ["symlink", "executable"])
def test_rejects_non_regular_git_mode(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mode: str
) -> None:
    source, base_sha, head_sha = _submission_repository(tmp_path, mode=mode)
    repository_url = source.as_uri()
    monkeypatch.setattr(tree_gate, "EXPECTED_REPOSITORY_URL", repository_url)
    with pytest.raises(tree_gate.GateError, match="regular 100644"):
        tree_gate.materialize_submission(
            repo_dir=tmp_path / "bare.git",
            repository_url=repository_url,
            head_sha=head_sha,
            base_sha=base_sha,
            submission_id=SUBMISSION_ID,
            output=tmp_path / "scenario.release.json",
        )


def test_rejects_any_second_changed_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source, base_sha, head_sha = _submission_repository(tmp_path, add_extra=True)
    repository_url = source.as_uri()
    monkeypatch.setattr(tree_gate, "EXPECTED_REPOSITORY_URL", repository_url)
    with pytest.raises(tree_gate.GateError, match="exactly one path"):
        tree_gate.materialize_submission(
            repo_dir=tmp_path / "bare.git",
            repository_url=repository_url,
            head_sha=head_sha,
            base_sha=base_sha,
            submission_id=SUBMISSION_ID,
            output=tmp_path / "scenario.release.json",
        )


def test_rejects_noncanonical_uuid() -> None:
    with pytest.raises(tree_gate.GateError, match="invalid Quick Submit UUID"):
        tree_gate._validate_uuid("-" * 36)
    with pytest.raises(tree_gate.GateError, match="invalid Quick Submit UUID"):
        tree_gate._validate_uuid(SUBMISSION_ID.upper())


def test_rejects_submission_not_based_on_exact_event_base(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source, _, head_sha = _submission_repository(tmp_path)
    _git(source, "checkout", "main")
    (source / "README.md").write_text("advanced base\n")
    _git(source, "add", "README.md")
    _git(source, "commit", "-m", "advance base")
    advanced_base = _git(source, "rev-parse", "HEAD")
    repository_url = source.as_uri()
    monkeypatch.setattr(tree_gate, "EXPECTED_REPOSITORY_URL", repository_url)

    with pytest.raises(tree_gate.GateError, match="exact pull request base"):
        tree_gate.materialize_submission(
            repo_dir=tmp_path / "bare.git",
            repository_url=repository_url,
            head_sha=head_sha,
            base_sha=advanced_base,
            submission_id=SUBMISSION_ID,
            output=tmp_path / "scenario.release.json",
        )


def test_creates_direct_child_commit_without_a_worktree(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source, base_sha, head_sha = _submission_repository(tmp_path)
    repo_dir, _ = _materialize(monkeypatch, tmp_path, source, base_sha, head_sha)
    result = tmp_path / "results.json"
    provenance = tmp_path / "provenance.json"
    result.write_text('{"status":"completed"}\n')
    provenance.write_text('{"timestamp":"2026-09-21T00:00:00Z"}\n')

    commit = tree_gate.create_results_commit(
        repo_dir=repo_dir,
        head_sha=head_sha,
        submission_id=SUBMISSION_ID,
        result=result,
        provenance=provenance,
    )

    assert _git(repo_dir, "rev-parse", f"{commit}^") == head_sha
    assert (
        _git(repo_dir, "show", f"{commit}:results/{SUBMISSION_ID}.json")
        == '{"status":"completed"}'
    )
    assert (
        _git(
            repo_dir,
            "show",
            f"{commit}:submissions/{SUBMISSION_ID}-provenance.json",
        )
        == '{"timestamp":"2026-09-21T00:00:00Z"}'
    )


def test_push_is_compare_and_swap_against_exact_event_head(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source, base_sha, head_sha = _submission_repository(tmp_path)
    remote = tmp_path / "remote.git"
    subprocess.run(
        ["git", "clone", "--bare", str(source), str(remote)],
        check=True,
        capture_output=True,
    )
    repository_url = remote.as_uri()
    monkeypatch.setattr(tree_gate, "EXPECTED_REPOSITORY_URL", repository_url)
    repo_dir, _ = _materialize(
        monkeypatch, tmp_path / "materialized", remote, base_sha, head_sha
    )
    result = tmp_path / "results.json"
    provenance = tmp_path / "provenance.json"
    result.write_text('{"status":"completed"}\n')
    provenance.write_text('{"timestamp":"2026-09-21T00:00:00Z"}\n')
    commit = tree_gate.create_results_commit(
        repo_dir=repo_dir,
        head_sha=head_sha,
        submission_id=SUBMISSION_ID,
        result=result,
        provenance=provenance,
    )

    tree_gate.push_results_commit(
        repo_dir=repo_dir,
        repository_url=repository_url,
        head_sha=head_sha,
        submission_id=SUBMISSION_ID,
        commit_sha=commit,
        token="test-token",
    )
    branch = f"refs/heads/quick-submit-{SUBMISSION_ID}"
    assert _git(remote, "rev-parse", branch) == commit

    _git(remote, "update-ref", branch, head_sha)
    competing_tree = _git(remote, "rev-parse", f"{head_sha}^{{tree}}")
    competing = subprocess.run(
        ["git", f"--git-dir={remote}", "commit-tree", competing_tree, "-p", head_sha],
        input="competing commit\n",
        text=True,
        check=True,
        capture_output=True,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@example.com",
        },
    ).stdout.strip()
    _git(remote, "update-ref", branch, competing)

    with pytest.raises(tree_gate.GateError, match="git push"):
        tree_gate.push_results_commit(
            repo_dir=repo_dir,
            repository_url=repository_url,
            head_sha=head_sha,
            submission_id=SUBMISSION_ID,
            commit_sha=commit,
            token="test-token",
        )

    # A plain push from the event head's parent would fast-forward successfully.
    # The exact lease must still reject it because the remote no longer equals
    # the event head SHA.
    _git(remote, "update-ref", branch, base_sha)
    with pytest.raises(tree_gate.GateError, match="git push"):
        tree_gate.push_results_commit(
            repo_dir=repo_dir,
            repository_url=repository_url,
            head_sha=head_sha,
            submission_id=SUBMISSION_ID,
            commit_sha=commit,
            token="test-token",
        )
