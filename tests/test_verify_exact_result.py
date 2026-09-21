from __future__ import annotations

import csv
from email.message import Message
from pathlib import Path
from urllib.request import Request

import pytest

from tools.fetch_pinned_dataset import SafeRedirectHandler
from tools.verify_exact_result import (
    DATASET_REVISION,
    EXPECTED_IMAGES,
    EXPECTED_MANIFEST_SOURCES,
    GATEWAY_MANIFEST,
    GENERATED_GATEWAY_MANIFEST,
    GREEN_MANIFEST,
    PURPLE_AGENT_ID,
    PURPLE_MANIFESTS,
    load_dataset,
    verify_artifact,
    verify_provenance,
    verify_scenario,
)

ROOT = Path(__file__).resolve().parents[1]


def _dataset(tmp_path: Path) -> tuple[Path, list[dict[str, str]]]:
    rows = [
        {
            "uid": str(index),
            "question": f"Question {index}",
            "answer": str(index),
            "source_docs": "doc",
            "source_files": "file",
        }
        for index in range(90)
    ]
    path = tmp_path / "dataset.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0])
        writer.writeheader()
        writer.writerows(rows)
    return path, rows


def _scenario() -> dict:
    return {
        "manifest_version": "0.4.0",
        "experimental_features": ["docker"],
        "config_schema": {
            "type": "object",
            "properties": {
                "green_hf_token": {"type": "string", "secret": True},
                "participant_api_url": {"type": "string", "secret": True},
                "participant_api_token": {"type": "string", "secret": True},
            },
            "required": [
                "green_hf_token",
                "participant_api_url",
                "participant_api_token",
            ],
            "additionalProperties": False,
        },
        "components": {
            "gateway": {
                "manifest": GATEWAY_MANIFEST,
                "config": {
                    "assessment_config": {
                        "tolerance": 0,
                        "timeout_seconds": 900,
                        "shard_index": 0,
                        "num_shards": 10,
                    },
                    "participant_roles": {
                        "green": "officeqa_pro_v2_green",
                        "purple1": "agent",
                    },
                },
            },
            "officeqa_pro_v2_green": {
                "manifest": GREEN_MANIFEST,
                "config": {"hf_token": "${config.green_hf_token}"},
            },
            "opencode_agent": {
                "manifest": min(PURPLE_MANIFESTS),
                "config": {
                    "officeqa_api_url": "${config.participant_api_url}",
                    "officeqa_api_token": "${config.participant_api_token}",
                },
            },
        },
        "bindings": [
            {"to": "#gateway.green", "from": "#officeqa_pro_v2_green.a2a"},
            {"to": "#gateway.purple1", "from": "#opencode_agent.a2a"},
            {
                "to": "#officeqa_pro_v2_green.proxy",
                "from": "#gateway.proxy",
                "weak": True,
            },
            {
                "to": "#opencode_agent.proxy",
                "from": "#gateway.proxy",
                "weak": True,
            },
        ],
        "exports": {
            "results": "#gateway.results",
            "participant_proxy": "#gateway.proxy",
        },
        "metadata": {
            "agentbeats_ids": {
                "officeqa_pro_v2_green": "11111111-1111-4111-8111-111111111111",
                "agent": PURPLE_AGENT_ID,
                "opencode_agent": PURPLE_AGENT_ID,
            }
        },
    }


def _artifact(rows: list[dict[str, str]]) -> dict:
    shards = []
    for shard_index in range(10):
        shard_rows = rows[shard_index::10]
        rewards = {row["uid"]: 1.0 for row in shard_rows}
        shards.append(
            {
                "benchmark": "OfficeQA Pro v2",
                "dataset_revision": DATASET_REVISION,
                "shard_index": shard_index,
                "num_shards": 10,
                "score": len(rewards),
                "max_score": len(rewards),
                "pass_rate": 100.0,
                "time_used": 1.0,
                "task_rewards": rewards,
                "error_count": 0,
                "error_types": {},
            }
        )
    return {
        "status": "completed",
        "participants": {"agent": PURPLE_AGENT_ID},
        "results": shards,
    }


def _generated_scenario() -> dict:
    return {
        "manifest_version": "0.1.0",
        "experimental_features": ["docker"],
        "config_schema": {
            "type": "object",
            "properties": {
                "green_hf_token": {"type": "string", "secret": True},
                "agent_officeqa_api_url": {"type": "string", "secret": True},
                "agent_officeqa_api_token": {"type": "string", "secret": True},
            },
            "required": [
                "green_hf_token",
                "agent_officeqa_api_url",
                "agent_officeqa_api_token",
            ],
            "additionalProperties": False,
        },
        "components": {
            "gateway": {
                "manifest": GENERATED_GATEWAY_MANIFEST,
                "config": {
                    "assessment_config": {
                        "tolerance": 0,
                        "timeout_seconds": 900,
                        "num_shards": 10,
                    },
                    "participant_roles": {"green": "green", "purple1": "agent"},
                    "callback_urls": {},
                },
            },
            "green": {
                "manifest": GREEN_MANIFEST,
                "config": {"hf_token": "${config.green_hf_token}"},
            },
            "agent": {
                "manifest": max(PURPLE_MANIFESTS),
                "config": {
                    "officeqa_api_url": "${config.agent_officeqa_api_url}",
                    "officeqa_api_token": "${config.agent_officeqa_api_token}",
                },
            },
        },
        "bindings": [
            {"to": "#gateway.green", "from": "#green.a2a"},
            {"to": "#gateway.purple1", "from": "#agent.a2a"},
            {"to": "#green.proxy", "from": "#gateway.proxy", "weak": True},
        ],
        "exports": {"results": "#gateway.results"},
        "metadata": {
            "agentbeats_ids": {
                "green": "11111111-1111-4111-8111-111111111111",
                "agent": PURPLE_AGENT_ID,
            }
        },
    }


def _provenance() -> dict:
    return {
        "image_digests": {
            f"/component-{index}": image
            for index, image in enumerate(sorted(EXPECTED_IMAGES))
        },
        "manifest_digests": {
            "/": "sha256:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
            "/gateway": "sha256:BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB=",
            "/green": "sha256:CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC=",
            "/agent": "sha256:DDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDD=",
        },
        "release_manifests": EXPECTED_MANIFEST_SOURCES,
        "timestamp": "2026-09-20T00:00:00Z",
        "github_actions": {
            "run_url": "https://github.com/onejumpinc/repo/actions/runs/1",
            "ref": "refs/heads/release",
            "sha": "abc",
            "repository_url": "https://github.com/onejumpinc/repo",
            "workflow_ref": "onejumpinc/repo/.github/workflows/run.yml@refs/heads/release",
            "workflow_sha": "abc",
        },
    }


def test_exact_scenario_result_and_provenance_pass(tmp_path: Path) -> None:
    dataset_path, _ = _dataset(tmp_path)
    rows = load_dataset(dataset_path, None, None)
    verify_scenario(_scenario())
    verify_artifact(_artifact(rows), rows)
    verify_provenance(
        _provenance(),
        expected_run_url="https://github.com/onejumpinc/repo/actions/runs/1",
        expected_repository_url="https://github.com/onejumpinc/repo",
        expected_github_sha="abc",
    )


def test_agentbeats_generated_scenario_passes() -> None:
    verify_scenario(_generated_scenario())


def test_scenario_rejects_partial_num_instances() -> None:
    scenario = _scenario()
    scenario["components"]["gateway"]["config"]["assessment_config"][
        "num_instances"
    ] = 10
    with pytest.raises(ValueError, match="num_instances"):
        verify_scenario(scenario)


def test_scenario_rejects_float_shard_count() -> None:
    scenario = _scenario()
    scenario["components"]["gateway"]["config"]["assessment_config"]["num_shards"] = (
        10.0
    )
    with pytest.raises(ValueError, match="num_shards"):
        verify_scenario(scenario)


def test_scenario_rejects_overlay_or_binding_extension() -> None:
    scenario = _scenario()
    scenario["overlays"] = []
    with pytest.raises(ValueError, match="top-level"):
        verify_scenario(scenario)

    scenario = _scenario()
    scenario["bindings"][0]["when"] = "config.enabled"
    with pytest.raises(ValueError, match="binding fields"):
        verify_scenario(scenario)


def test_scenario_rejects_placeholder_green_id() -> None:
    scenario = _scenario()
    scenario["metadata"]["agentbeats_ids"]["officeqa_pro_v2_green"] = (
        "REPLACE_WITH_GREEN_AGENT_ID"
    )
    with pytest.raises(ValueError, match="placeholder"):
        verify_scenario(scenario)


def test_result_rejects_one_wrong_reward(tmp_path: Path) -> None:
    dataset_path, _ = _dataset(tmp_path)
    rows = load_dataset(dataset_path, None, None)
    artifact = _artifact(rows)
    artifact["results"][0]["task_rewards"]["0"] = 0.0
    with pytest.raises(ValueError, match="reward"):
        verify_artifact(artifact, rows)


def test_result_rejects_wrong_participant(tmp_path: Path) -> None:
    dataset_path, _ = _dataset(tmp_path)
    rows = load_dataset(dataset_path, None, None)
    artifact = _artifact(rows)
    artifact["participants"]["agent"] = "wrong"
    with pytest.raises(ValueError, match="participants.agent"):
        verify_artifact(artifact, rows)


def test_result_rejects_nested_or_extra_shard_shape(tmp_path: Path) -> None:
    dataset_path, _ = _dataset(tmp_path)
    rows = load_dataset(dataset_path, None, None)
    artifact = _artifact(rows)
    artifact["results"] = [{"wrapper": shard} for shard in artifact["results"]]
    with pytest.raises(ValueError, match="shard result fields"):
        verify_artifact(artifact, rows)


def test_result_rejects_missing_uid(tmp_path: Path) -> None:
    dataset_path, _ = _dataset(tmp_path)
    rows = load_dataset(dataset_path, None, None)
    artifact = _artifact(rows)
    del artifact["results"][0]["task_rewards"]["0"]
    with pytest.raises(ValueError, match="UID mismatch"):
        verify_artifact(artifact, rows)


def test_provenance_rejects_changed_runtime_image() -> None:
    provenance = _provenance()
    provenance["image_digests"]["/component-0"] = "changed@sha256:bad"
    with pytest.raises(ValueError, match="runtime image digests"):
        verify_provenance(provenance)


def test_provenance_rejects_changed_manifest_source() -> None:
    provenance = _provenance()
    provenance["release_manifests"] = {
        **EXPECTED_MANIFEST_SOURCES,
        "purple": {"url": "https://example.invalid", "raw_sha256": "0" * 64},
    }
    with pytest.raises(ValueError, match="manifest sources"):
        verify_provenance(provenance)


def test_dataset_redirect_does_not_forward_token_cross_host() -> None:
    request = Request(
        "https://huggingface.co/source",
        headers={"Authorization": "Bearer secret"},
    )
    redirected = SafeRedirectHandler().redirect_request(
        request,
        None,
        302,
        "Found",
        Message(),
        "https://cdn.example/download",
    )
    assert redirected is not None
    assert redirected.get_header("Authorization") is None


def test_public_workflows_gate_before_any_result_write() -> None:
    self_run = (ROOT / ".github/workflows/run-scenario.yml").read_text()
    quick_run = (ROOT / ".github/workflows/quick-submit-runner.yml").read_text()
    assert self_run.index("Verify exact 90/90 release") < self_run.index(
        "Create submission branch and commit results"
    )
    assert quick_run.index("Verify exact 90/90 release") < quick_run.index(
        "Commit results"
    )
    assert quick_run.count("ref: ${{ github.event.pull_request.head.sha }}") == 3
    assert 'git push origin "HEAD:refs/heads/${GITHUB_HEAD_REF}"' in quick_run
    assert "RELEASE_GATE_REF: 75f1d418ef25dcb6a49d55df567be93f68e3a9a7" in quick_run
    assert quick_run.count(".release-gate/tools/verify_exact_result.py") == 2
    assert ".release-gate/tools/fetch_pinned_dataset.py" in quick_run


def test_quick_submit_calls_repository_owned_runner() -> None:
    workflow = (ROOT / ".github/workflows/quick-submit.yml").read_text()
    assert "uses: ./.github/workflows/quick-submit-runner.yml" in workflow
    assert "RDI-Foundation/agentbeats-leaderboard-template" not in workflow
