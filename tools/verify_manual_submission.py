"""Verify a fork/self-run result PR without executing code from the fork."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

from tools.verify_exact_result import (
    EXPECTED_ROWS,
    _load_json,
    scenario_kind,
    verify_artifact,
    verify_provenance,
    verify_scenario,
)

TARGET_REPOSITORY = "onejumpinc/officeqa-pro-v2-agentbeats"
WORKFLOW_PATH = ".github/workflows/run-scenario.yml"
SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+-[0-9]+$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"{label} must be an object")
    return value


def _array(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise TypeError(f"{label} must be an array")
    return value


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _expected_paths(unique_name: str) -> set[str]:
    return {
        f"results/{unique_name}.json",
        f"submissions/{unique_name}.json5",
        f"submissions/{unique_name}-provenance.json",
    }


def verify_submission(
    *,
    result_path: Path,
    provenance_path: Path,
    scenario_path: Path,
    source_scenario_path: Path,
    changed_files_path: Path,
    run_metadata_path: Path,
    repository_metadata_path: Path,
    head_repository: str,
    head_ref: str,
    head_sha: str,
    base_repository: str,
) -> None:
    if base_repository != TARGET_REPOSITORY:
        raise ValueError(
            f"base repository is {base_repository!r}, expected {TARGET_REPOSITORY!r}"
        )
    if not SHA_RE.fullmatch(head_sha):
        raise ValueError("pull-request head SHA is not a full lowercase Git SHA")
    if not head_ref.startswith("submission-"):
        raise ValueError("manual result branch must start with submission-")

    repository = _object(_json(repository_metadata_path), "repository metadata")
    parent = _object(repository.get("parent"), "repository parent")
    if (
        repository.get("full_name") != head_repository
        or repository.get("fork") is not True
        or repository.get("visibility") != "public"
        or parent.get("full_name") != base_repository
    ):
        raise ValueError("submission head is not the expected public leaderboard fork")

    run = _object(_json(run_metadata_path), "workflow run metadata")
    run_repository = _object(run.get("repository"), "workflow run repository")
    actor = _object(run.get("actor"), "workflow run actor")
    triggering_actor = _object(
        run.get("triggering_actor"), "workflow run triggering actor"
    )
    run_id = run.get("id")
    run_attempt = run.get("run_attempt")
    if isinstance(run_id, bool) or not isinstance(run_id, int) or run_id <= 0:
        raise ValueError("workflow run ID is invalid")
    if run_attempt != 1 or isinstance(run_attempt, bool):
        raise ValueError("manual workflow run_attempt must be exactly 1")
    if run.get("event") not in {"push", "workflow_dispatch"}:
        raise ValueError("manual workflow event is not push or workflow_dispatch")
    if run.get("status") != "completed" or run.get("conclusion") != "success":
        raise ValueError("manual workflow run did not complete successfully")
    if run.get("path") != WORKFLOW_PATH:
        raise ValueError("manual workflow run used an unexpected workflow path")
    if run_repository.get("full_name") != head_repository:
        raise ValueError("manual workflow run repository does not match the PR fork")
    if actor.get("login") != triggering_actor.get("login"):
        raise ValueError("manual workflow actor and triggering actor differ")

    run_head_sha = run.get("head_sha")
    run_head_branch = run.get("head_branch")
    if not isinstance(run_head_branch, str) or not run_head_branch:
        raise ValueError("manual workflow head branch is missing")
    if not isinstance(run_head_sha, str) or not SHA_RE.fullmatch(run_head_sha):
        raise ValueError("manual workflow head SHA is invalid")
    if run.get("html_url") != (
        f"https://github.com/{head_repository}/actions/runs/{run_id}"
    ):
        raise ValueError("manual workflow run URL is not canonical")

    owner = head_repository.split("/", maxsplit=1)[0]
    unique_name = f"{owner}-{run_id}"
    if not SAFE_NAME_RE.fullmatch(unique_name):
        raise ValueError("manual submission name is not canonical")
    if head_ref != f"submission-{unique_name}":
        raise ValueError("result PR branch does not match its workflow run")

    changed_files = _array(_json(changed_files_path), "changed files")
    if len(changed_files) != 3:
        raise ValueError("manual result PR must add exactly three files")
    observed_paths: set[str] = set()
    for item in changed_files:
        changed = _object(item, "changed file")
        if changed.get("status") != "added":
            raise ValueError("manual result PR files must all be newly added")
        filename = changed.get("filename")
        if not isinstance(filename, str):
            raise TypeError("changed filename must be a string")
        observed_paths.add(filename)
    if observed_paths != _expected_paths(unique_name):
        raise ValueError("manual result PR paths do not match the workflow run")

    if scenario_path.read_bytes() != source_scenario_path.read_bytes():
        raise ValueError("submitted scenario differs from the scenario used by the run")
    scenario = _load_json(scenario_path)
    verify_scenario(scenario, require_kind="self-run")
    metadata = _object(scenario.get("metadata"), "scenario metadata")
    participants = _object(metadata.get("agentbeats_ids"), "scenario participants")

    result = _load_json(result_path)
    synthetic_rows = [{"uid": str(index)} for index in range(EXPECTED_ROWS)]
    verify_artifact(result, synthetic_rows, participants)

    expected_run_url = f"https://github.com/{head_repository}/actions/runs/{run_id}"
    expected_repository_url = f"https://github.com/{head_repository}"
    expected_ref = f"refs/heads/{run_head_branch}"
    expected_workflow_ref = (
        f"{head_repository}/{WORKFLOW_PATH}@refs/heads/{run_head_branch}"
    )
    verify_provenance(
        _load_json(provenance_path),
        scenario_kind=scenario_kind(scenario),
        expected_run_url=expected_run_url,
        expected_repository_url=expected_repository_url,
        expected_github_sha=run_head_sha,
        expected_github_ref=expected_ref,
        expected_workflow_ref=expected_workflow_ref,
        expected_workflow_sha=run_head_sha,
        expected_job_workflow_ref=expected_workflow_ref,
        expected_job_workflow_sha=run_head_sha,
        expected_results_sha256=_sha256(result_path),
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--provenance", type=Path, required=True)
    parser.add_argument("--scenario", type=Path, required=True)
    parser.add_argument("--source-scenario", type=Path, required=True)
    parser.add_argument("--changed-files", type=Path, required=True)
    parser.add_argument("--run-metadata", type=Path, required=True)
    parser.add_argument("--repository-metadata", type=Path, required=True)
    parser.add_argument("--head-repository", required=True)
    parser.add_argument("--head-ref", required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--base-repository", required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        verify_submission(
            result_path=args.result,
            provenance_path=args.provenance,
            scenario_path=args.scenario,
            source_scenario_path=args.source_scenario,
            changed_files_path=args.changed_files,
            run_metadata_path=args.run_metadata,
            repository_metadata_path=args.repository_metadata,
            head_repository=args.head_repository,
            head_ref=args.head_ref,
            head_sha=args.head_sha,
            base_repository=args.base_repository,
        )
    except (OSError, TypeError, json.JSONDecodeError, ValueError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print("PASS: canonical public fork run produced an exact 90/90 submission")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
