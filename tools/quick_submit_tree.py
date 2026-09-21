#!/usr/bin/env python3
"""Materialize and update a Quick Submit branch without checking out its tree."""

from __future__ import annotations

import argparse
import base64
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

EXPECTED_REPOSITORY_URL = "https://github.com/onejumpinc/officeqa-pro-v2-agentbeats.git"
UUID_PATTERN = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
UUID_RE = re.compile(rf"^{UUID_PATTERN}$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
MAX_SCENARIO_BYTES = 1_000_000


class GateError(ValueError):
    """Raised when submitted Git data does not match the release contract."""


def _validate_uuid(value: str) -> str:
    normalized = value.lower()
    if not UUID_RE.fullmatch(normalized):
        raise GateError(f"invalid Quick Submit UUID: {value!r}")
    return normalized


def _validate_sha(value: str, label: str) -> str:
    normalized = value.lower()
    if not SHA_RE.fullmatch(normalized):
        raise GateError(f"{label} must be a full lowercase Git SHA")
    return normalized


def _validate_repository_url(value: str) -> str:
    if value != EXPECTED_REPOSITORY_URL:
        raise GateError(
            f"repository URL is {value!r}, expected {EXPECTED_REPOSITORY_URL!r}"
        )
    return value


def _git(
    repo_dir: Path,
    *args: str,
    input_data: bytes | None = None,
    env: dict[str, str] | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[bytes]:
    result = subprocess.run(
        ["git", f"--git-dir={repo_dir}", *args],
        input=input_data,
        capture_output=True,
        env=env,
        check=False,
    )
    if check and result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise GateError(f"git {' '.join(args)} failed: {detail}")
    return result


def _git_text(repo_dir: Path, *args: str) -> str:
    return _git(repo_dir, *args).stdout.decode("utf-8").strip()


def _initialize_bare_repository(repo_dir: Path) -> None:
    if repo_dir.exists():
        raise GateError(f"temporary Git directory already exists: {repo_dir}")
    repo_dir.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["git", "init", "--bare", str(repo_dir)],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise GateError(f"could not initialize temporary bare repository: {detail}")


def _fetch_event_commits(
    repo_dir: Path, repository_url: str, head_sha: str, base_sha: str
) -> None:
    _git(
        repo_dir,
        "fetch",
        "--no-tags",
        "--no-recurse-submodules",
        "--force",
        repository_url,
        f"{head_sha}:refs/quick-submit/head",
        f"{base_sha}:refs/quick-submit/base",
    )
    fetched_head = _git_text(repo_dir, "rev-parse", "refs/quick-submit/head^{commit}")
    fetched_base = _git_text(repo_dir, "rev-parse", "refs/quick-submit/base^{commit}")
    if fetched_head != head_sha or fetched_base != base_sha:
        raise GateError("fetched commits do not match the pull request event")


def _parse_single_added_file(raw_diff: bytes) -> tuple[str, str]:
    fields = raw_diff.split(b"\0")
    if fields and fields[-1] == b"":
        fields.pop()
    if len(fields) != 2:
        raise GateError("Quick Submit PR must change exactly one path")

    metadata, raw_path = fields
    try:
        path = raw_path.decode("utf-8")
        parts = metadata.decode("ascii").split()
    except UnicodeDecodeError as error:
        raise GateError("Quick Submit diff contains a non-UTF-8 path") from error
    if len(parts) != 5 or not parts[0].startswith(":"):
        raise GateError("unexpected Git raw-diff record")

    old_mode = parts[0][1:]
    new_mode, old_sha, new_sha, status_code = parts[1:]
    if (
        old_mode != "000000"
        or new_mode != "100644"
        or set(old_sha) != {"0"}
        or status_code != "A"
    ):
        raise GateError(
            "submission scenario must be one newly added regular 100644 file"
        )
    return path, new_sha


def materialize_submission(
    *,
    repo_dir: Path,
    repository_url: str,
    head_sha: str,
    base_sha: str,
    submission_id: str,
    output: Path,
) -> Path:
    """Validate the event tree and write its sole scenario blob to a safe path."""
    repository_url = _validate_repository_url(repository_url)
    head_sha = _validate_sha(head_sha, "head SHA")
    base_sha = _validate_sha(base_sha, "base SHA")
    submission_id = _validate_uuid(submission_id)
    expected_path = f"submissions/{submission_id}.json"

    _initialize_bare_repository(repo_dir)
    _fetch_event_commits(repo_dir, repository_url, head_sha, base_sha)
    merge_base = _git_text(repo_dir, "merge-base", base_sha, head_sha)
    raw_diff = _git(
        repo_dir,
        "diff",
        "--raw",
        "-z",
        "--no-abbrev",
        "--no-renames",
        merge_base,
        head_sha,
    ).stdout
    changed_path, changed_oid = _parse_single_added_file(raw_diff)
    if changed_path != expected_path:
        raise GateError(
            f"Quick Submit PR adds {changed_path!r}, expected {expected_path!r}"
        )

    tree_record = _git(repo_dir, "ls-tree", "-z", head_sha, "--", expected_path).stdout
    records = [record for record in tree_record.split(b"\0") if record]
    if len(records) != 1 or b"\t" not in records[0]:
        raise GateError("scenario path does not resolve to exactly one Git tree entry")
    raw_header, raw_tree_path = records[0].split(b"\t", 1)
    try:
        tree_path = raw_tree_path.decode("utf-8")
        mode, kind, oid = raw_header.decode("ascii").split()
    except (UnicodeDecodeError, ValueError) as error:
        raise GateError("scenario tree entry is malformed") from error
    if tree_path != expected_path or mode != "100644" or kind != "blob":
        raise GateError("scenario tree entry is not the exact regular file expected")
    if oid != changed_oid:
        raise GateError("scenario tree object disagrees with the validated PR diff")

    scenario = _git(repo_dir, "cat-file", "blob", oid).stdout
    if not scenario or len(scenario) > MAX_SCENARIO_BYTES:
        raise GateError(
            f"scenario size must be between 1 and {MAX_SCENARIO_BYTES} bytes"
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(output, flags, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(scenario)
    return output


def _regular_file(path: Path, label: str) -> None:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError as error:
        raise GateError(f"{label} does not exist: {path}") from error
    if not stat.S_ISREG(mode):
        raise GateError(f"{label} must be a regular non-symlink file")


def create_results_commit(
    *,
    repo_dir: Path,
    head_sha: str,
    submission_id: str,
    result: Path,
    provenance: Path,
) -> str:
    """Create a child commit by manipulating the Git index, never a worktree."""
    head_sha = _validate_sha(head_sha, "head SHA")
    submission_id = _validate_uuid(submission_id)
    _regular_file(result, "result artifact")
    _regular_file(provenance, "provenance artifact")
    if _git_text(repo_dir, "rev-parse", "refs/quick-submit/head^{commit}") != head_sha:
        raise GateError("temporary repository head does not match the event SHA")

    destination_files = {
        f"results/{submission_id}.json": result,
        f"submissions/{submission_id}-provenance.json": provenance,
    }
    for destination in destination_files:
        exists = _git(
            repo_dir,
            "cat-file",
            "-e",
            f"{head_sha}:{destination}",
            check=False,
        )
        if exists.returncode == 0:
            raise GateError(
                f"destination already exists in submission head: {destination}"
            )

    _git(repo_dir, "read-tree", head_sha)
    for destination, source in destination_files.items():
        blob = _git_text(repo_dir, "hash-object", "-w", "--no-filters", str(source))
        _git(
            repo_dir,
            "update-index",
            "--add",
            "--cacheinfo",
            "100644",
            blob,
            destination,
        )
    tree = _git_text(repo_dir, "write-tree")
    identity_env = os.environ.copy()
    identity_env.update(
        {
            "GIT_AUTHOR_NAME": "github-actions[bot]",
            "GIT_AUTHOR_EMAIL": "41898282+github-actions[bot]@users.noreply.github.com",
            "GIT_COMMITTER_NAME": "github-actions[bot]",
            "GIT_COMMITTER_EMAIL": "41898282+github-actions[bot]@users.noreply.github.com",
        }
    )
    commit = (
        _git(
            repo_dir,
            "commit-tree",
            tree,
            "-p",
            head_sha,
            input_data=b"[AgentBeats] Exact OfficeQA Pro v2 90/90 result\n",
            env=identity_env,
        )
        .stdout.decode("ascii")
        .strip()
    )
    return _validate_sha(commit, "created commit SHA")


def push_results_commit(
    *,
    repo_dir: Path,
    repository_url: str,
    head_sha: str,
    submission_id: str,
    commit_sha: str,
    token: str,
) -> None:
    """Push the verified child commit without force or stored credentials."""
    repository_url = _validate_repository_url(repository_url)
    head_sha = _validate_sha(head_sha, "head SHA")
    commit_sha = _validate_sha(commit_sha, "result commit SHA")
    submission_id = _validate_uuid(submission_id)
    if not token or any(character in token for character in "\r\n\0"):
        raise GateError("GitHub token is missing or malformed")
    if _git_text(repo_dir, "rev-parse", f"{commit_sha}^") != head_sha:
        raise GateError("result commit is not a direct child of the event head")

    credential = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    push_env = os.environ.copy()
    push_env.pop("GITHUB_TOKEN", None)
    push_env.update(
        {
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader",
            "GIT_CONFIG_VALUE_0": f"AUTHORIZATION: basic {credential}",
        }
    )
    branch = f"quick-submit-{submission_id}"
    _git(
        repo_dir,
        "push",
        repository_url,
        f"{commit_sha}:refs/heads/{branch}",
        env=push_env,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    materialize = subparsers.add_parser("materialize")
    materialize.add_argument("--repo-dir", type=Path, required=True)
    materialize.add_argument("--repository-url", required=True)
    materialize.add_argument("--head-sha", required=True)
    materialize.add_argument("--base-sha", required=True)
    materialize.add_argument("--submission-id", required=True)
    materialize.add_argument("--output", type=Path, required=True)

    commit = subparsers.add_parser("commit")
    commit.add_argument("--repo-dir", type=Path, required=True)
    commit.add_argument("--head-sha", required=True)
    commit.add_argument("--submission-id", required=True)
    commit.add_argument("--result", type=Path, required=True)
    commit.add_argument("--provenance", type=Path, required=True)

    push = subparsers.add_parser("push")
    push.add_argument("--repo-dir", type=Path, required=True)
    push.add_argument("--repository-url", required=True)
    push.add_argument("--head-sha", required=True)
    push.add_argument("--submission-id", required=True)
    push.add_argument("--commit-sha", required=True)
    push.add_argument("--token-env", default="GITHUB_TOKEN")
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.command == "materialize":
            materialize_submission(
                repo_dir=args.repo_dir,
                repository_url=args.repository_url,
                head_sha=args.head_sha,
                base_sha=args.base_sha,
                submission_id=args.submission_id,
                output=args.output,
            )
            print("PASS: exact Quick Submit Git tree materialized")
        elif args.command == "commit":
            print(
                create_results_commit(
                    repo_dir=args.repo_dir,
                    head_sha=args.head_sha,
                    submission_id=args.submission_id,
                    result=args.result,
                    provenance=args.provenance,
                )
            )
        else:
            push_results_commit(
                repo_dir=args.repo_dir,
                repository_url=args.repository_url,
                head_sha=args.head_sha,
                submission_id=args.submission_id,
                commit_sha=args.commit_sha,
                token=os.environ.get(args.token_env, ""),
            )
            print("PASS: exact result commit pushed without force")
    except (GateError, OSError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
