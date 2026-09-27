from __future__ import annotations

import csv
import hashlib
import json
import re
import subprocess
from email.message import Message
from pathlib import Path
from urllib.request import Request

import pytest

from tools import verify_exact_result as gate
from tools.fetch_pinned_dataset import SafeRedirectHandler
from tools.verify_exact_result import (
    _COMPOSE_IMAGE_REPLACEMENTS,
    _COMPOSE_SOURCE_IMAGE_COUNTS,
    COMPILE_MANIFESTS,
    DATASET_REVISION,
    EXPECTED_FRAMEWORK_IMAGES,
    EXPECTED_MANIFEST_SOURCES,
    EXPECTED_TOOL_IMAGES,
    GATEWAY_MANIFEST,
    GENERATED_GATEWAY_MANIFEST,
    GREEN_MANIFEST,
    PINNED_PURPLE_MANIFEST,
    PURPLE_AGENT_ID,
    PURPLE_MANIFESTS,
    _expected_compiled_images,
    _expected_manifest_digests,
    _expected_runtime_images,
    load_dataset,
    pin_compose_images,
    verify_artifact,
    verify_compiled_ir,
    verify_provenance,
    verify_rendered_compose,
    verify_scenario,
)
from tools.verify_manual_submission import verify_submission

ROOT = Path(__file__).resolve().parents[1]
TEST_GREEN_AGENT_ID = "11111111-1111-4111-8111-111111111111"
CHECKED_IN_GREEN_AGENT_ID = gate.GREEN_AGENT_ID
FROZEN_RUNNER_SHA = "94a8460f564887bbdcb8819e1b0368da6e89c46a"
FROZEN_RUNNER_SHA256 = (
    "b90d6f2a564730dacd2cd6ba7a3a8ea5233ad37ee75c5546e5bdfeba836c9181"
)


@pytest.fixture(autouse=True)
def _configure_green_agent_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gate, "GREEN_AGENT_ID", TEST_GREEN_AGENT_ID)


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


def _frozen_runner() -> str:
    working_runner = (ROOT / ".github/workflows/quick-submit-runner.yml").read_text()
    assert hashlib.sha256(working_runner.encode()).hexdigest() == FROZEN_RUNNER_SHA256
    completed = subprocess.run(
        [
            "git",
            "show",
            f"{FROZEN_RUNNER_SHA}:.github/workflows/quick-submit-runner.yml",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return working_runner
    assert completed.stdout == working_runner
    return completed.stdout


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
                "manifest": PINNED_PURPLE_MANIFEST,
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
            {"to": "#agent.proxy", "from": "#gateway.proxy", "weak": True},
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
    manifests = _expected_manifest_digests("self-run")
    return {
        "image_digests": _expected_runtime_images("self-run"),
        "framework_image_digests": EXPECTED_FRAMEWORK_IMAGES,
        "manifest_digests": manifests["0"],
        "manifest_digests_by_shard": manifests,
        "release_manifests": EXPECTED_MANIFEST_SOURCES,
        "tool_images": EXPECTED_TOOL_IMAGES,
        "results_sha256": "0" * 64,
        "timestamp": "2026-09-21T00:00:00Z",
        "github_actions": {
            "run_url": "https://github.com/onejumpinc/repo/actions/runs/1",
            "ref": "refs/heads/release",
            "sha": "a" * 40,
            "repository_url": "https://github.com/onejumpinc/repo",
            "workflow_ref": "onejumpinc/repo/.github/workflows/run.yml@refs/heads/release",
            "workflow_sha": "a" * 40,
            "job_workflow_ref": "onejumpinc/repo/.github/workflows/run.yml@refs/heads/release",
            "job_workflow_sha": "a" * 40,
            "run_attempt": 1,
        },
    }


def _quick_provenance() -> dict:
    provenance = _provenance()
    manifests = _expected_manifest_digests("generated")
    provenance["manifest_digests"] = manifests["0"]
    provenance["manifest_digests_by_shard"] = manifests
    provenance["image_digests"] = _expected_runtime_images("generated")
    provenance["github_actions"] = {
        "run_url": "https://github.com/onejumpinc/officeqa-pro-v2-agentbeats/actions/runs/1",
        "ref": "refs/heads/main",
        "sha": "c" * 40,
        "repository_url": "https://github.com/onejumpinc/officeqa-pro-v2-agentbeats",
        "workflow_ref": (
            "onejumpinc/officeqa-pro-v2-agentbeats/"
            ".github/workflows/quick-submit.yml@refs/heads/main"
        ),
        "workflow_sha": "c" * 40,
        "job_workflow_ref": (
            "onejumpinc/officeqa-pro-v2-agentbeats/"
            f".github/workflows/quick-submit-runner.yml@{'b' * 40}"
        ),
        "job_workflow_sha": "b" * 40,
        "run_attempt": 1,
    }
    provenance["pull_request"] = {
        "number": 42,
        "event_name": "pull_request_target",
        "actor": "agentbeats-dev[bot]",
        "author": "agentbeats-dev[bot]",
        "head_ref": "quick-submit-01234567-89ab-4def-8123-456789abcdef",
        "head_sha": "d" * 40,
        "head_repository": "onejumpinc/officeqa-pro-v2-agentbeats",
        "base_ref": "main",
        "base_sha": "c" * 40,
    }
    return provenance


def _workflow_run_blocks(workflow: str) -> list[str]:
    lines = workflow.splitlines()
    blocks: list[str] = []
    for index, line in enumerate(lines):
        if line.strip() != "run: |":
            continue
        indentation = len(line) - len(line.lstrip())
        body: list[str] = []
        for candidate in lines[index + 1 :]:
            if (
                candidate.strip()
                and len(candidate) - len(candidate.lstrip()) <= indentation
            ):
                break
            body.append(candidate)
        blocks.append("\n".join(body))
    return blocks


def test_exact_scenario_result_and_provenance_pass(tmp_path: Path) -> None:
    dataset_path, _ = _dataset(tmp_path)
    rows = load_dataset(dataset_path, None, None)
    verify_scenario(_scenario())
    verify_artifact(_artifact(rows), rows)
    verify_provenance(
        _provenance(),
        scenario_kind="self-run",
        expected_run_url="https://github.com/onejumpinc/repo/actions/runs/1",
        expected_repository_url="https://github.com/onejumpinc/repo",
        expected_github_sha="a" * 40,
    )


def test_agentbeats_generated_scenario_passes() -> None:
    verify_scenario(_generated_scenario())


def test_quick_submit_can_require_generated_scenario_kind() -> None:
    verify_scenario(_generated_scenario(), require_kind="generated")
    with pytest.raises(ValueError, match="required exact kind"):
        verify_scenario(_scenario(), require_kind="generated")


def test_compiled_ir_and_runtime_images_are_exact() -> None:
    shard_index = 7
    manifests = _expected_manifest_digests("generated")[str(shard_index)]
    compiled_images = _expected_compiled_images("generated")
    ir = {
        "components": [
            {
                "moniker": moniker,
                "digest": digest,
                "program": (
                    {"image": compiled_images[moniker]}
                    if moniker in compiled_images
                    else None
                ),
            }
            for moniker, digest in manifests.items()
        ]
    }
    verify_compiled_ir(
        ir,
        scenario_kind="generated",
        shard_index=shard_index,
        runtime_images=_expected_runtime_images("generated"),
    )

    changed_images = {**_expected_runtime_images("generated"), "/gateway": "bad"}
    with pytest.raises(ValueError, match="resolved runtime images"):
        verify_compiled_ir(
            ir,
            scenario_kind="generated",
            shard_index=shard_index,
            runtime_images=changed_images,
        )

    changed_ir = json.loads(json.dumps(ir))
    changed_ir["components"][0]["digest"] = "sha256:" + "A" * 43 + "="
    with pytest.raises(ValueError, match=r"got=.*expected="):
        verify_compiled_ir(
            changed_ir,
            scenario_kind="generated",
            shard_index=shard_index,
        )


def test_compose_image_tags_are_replaced_by_exact_digests(tmp_path: Path) -> None:
    compose = tmp_path / "compose.yaml"
    lines = ["services:"]
    service_index = 0
    for image, count in _COMPOSE_SOURCE_IMAGE_COUNTS.items():
        for _ in range(count):
            lines.extend(
                [
                    f"  service-{service_index}:",
                    f"    image: {image}",
                ]
            )
            service_index += 1
    compose.write_text("\n".join(lines) + "\n")
    framework = tmp_path / "framework-images.json"

    pin_compose_images(compose, framework)

    pinned = compose.read_text()
    for old, new in _COMPOSE_IMAGE_REPLACEMENTS.items():
        if old != new:
            assert f"image: {old}\n" not in pinned
        assert f"image: {new}\n" in pinned
    assert json.loads(framework.read_text()) == EXPECTED_FRAMEWORK_IMAGES


def test_rendered_compose_requires_exact_image_multiset(tmp_path: Path) -> None:
    services = {}
    service_index = 0
    for source_image, count in _COMPOSE_SOURCE_IMAGE_COUNTS.items():
        for _ in range(count):
            services[f"service-{service_index}"] = {
                "image": _COMPOSE_IMAGE_REPLACEMENTS[source_image]
            }
            service_index += 1
    rendered = tmp_path / "compose.json"
    rendered.write_text(json.dumps({"services": services}))
    verify_rendered_compose(rendered)

    services["service-0"]["build"] = "."
    rendered.write_text(json.dumps({"services": services}))
    with pytest.raises(ValueError, match="build or extends"):
        verify_rendered_compose(rendered)

    del services["service-0"]["build"]
    services["service-0"]["privileged"] = True
    rendered.write_text(json.dumps({"services": services}))
    with pytest.raises(ValueError, match="privileged"):
        verify_rendered_compose(rendered)

    del services["service-0"]["privileged"]
    for field, value, message in (
        ("network_mode", "host", "network namespace"),
        ("devices", ["/dev/kvm"], "host devices"),
        ("cap_add", ["SYS_ADMIN"], "unapproved capability"),
        ("security_opt", ["seccomp=unconfined"], "security profile"),
        (
            "volumes",
            [
                {
                    "type": "bind",
                    "source": "/var/lib/docker/containers",
                    "target": "/var/lib/docker/containers",
                    "read_only": True,
                }
            ],
            "unapproved host bind",
        ),
        ("ports", [{"host_ip": "0.0.0.0"}], "non-loopback port"),
    ):
        services["service-0"][field] = value
        rendered.write_text(json.dumps({"services": services}))
        with pytest.raises(ValueError, match=message):
            verify_rendered_compose(rendered)
        del services["service-0"][field]


def test_compiled_generated_scenario_requires_exact_shard_and_local_manifests() -> None:
    scenario = _generated_scenario()
    scenario["components"]["gateway"]["manifest"] = COMPILE_MANIFESTS["gateway"]
    scenario["components"]["green"]["manifest"] = COMPILE_MANIFESTS["green"]
    scenario["components"]["agent"]["manifest"] = COMPILE_MANIFESTS["purple"]
    scenario["components"]["gateway"]["config"]["assessment_config"]["shard_index"] = 7
    verify_scenario(scenario, expected_shard_index=7, compile_manifests=True)

    with pytest.raises(ValueError, match="shard_index"):
        verify_scenario(scenario, expected_shard_index=6, compile_manifests=True)


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


def test_checked_in_scenario_is_strict_json_and_fails_closed_until_registration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = json.loads((ROOT / "scenario.json5").read_text())
    registered = scenario["metadata"]["agentbeats_ids"]["officeqa_pro_v2_green"]
    assert registered == CHECKED_IN_GREEN_AGENT_ID

    monkeypatch.setattr(gate, "GREEN_AGENT_ID", CHECKED_IN_GREEN_AGENT_ID)
    if CHECKED_IN_GREEN_AGENT_ID == "REPLACE_WITH_GREEN_AGENT_ID":
        with pytest.raises(ValueError, match="registration placeholder"):
            verify_scenario(scenario, require_kind="self-run")
    else:
        assert re.fullmatch(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
            CHECKED_IN_GREEN_AGENT_ID,
        )
        verify_scenario(scenario, require_kind="self-run")


def test_scenario_rejects_unpinned_green_id() -> None:
    scenario = _scenario()
    scenario["metadata"]["agentbeats_ids"]["officeqa_pro_v2_green"] = (
        "22222222-2222-4222-8222-222222222222"
    )
    with pytest.raises(ValueError, match="pinned green"):
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
    provenance["image_digests"]["/gateway"] = "changed@sha256:bad"
    with pytest.raises(ValueError, match="runtime image digests"):
        verify_provenance(provenance, scenario_kind="self-run")


def test_provenance_rejects_changed_manifest_source() -> None:
    provenance = _provenance()
    provenance["release_manifests"] = {
        **EXPECTED_MANIFEST_SOURCES,
        "purple": {"url": "https://example.invalid", "raw_sha256": "0" * 64},
    }
    with pytest.raises(ValueError, match="manifest sources"):
        verify_provenance(provenance, scenario_kind="self-run")


def test_provenance_rejects_changed_compiled_manifest_digest() -> None:
    provenance = _provenance()
    provenance["manifest_digests_by_shard"]["4"]["/"] = (
        "sha256:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
    )
    with pytest.raises(ValueError, match="compiled manifest digests"):
        verify_provenance(provenance, scenario_kind="self-run")


def test_quick_submit_provenance_binds_event_caller_and_runner() -> None:
    provenance = _quick_provenance()
    verify_provenance(
        provenance,
        scenario_kind="generated",
        expected_run_url=(
            "https://github.com/onejumpinc/officeqa-pro-v2-agentbeats/actions/runs/1"
        ),
        expected_repository_url=(
            "https://github.com/onejumpinc/officeqa-pro-v2-agentbeats"
        ),
        expected_github_sha="c" * 40,
        expected_github_ref="refs/heads/main",
        expected_workflow_ref=(
            "onejumpinc/officeqa-pro-v2-agentbeats/"
            ".github/workflows/quick-submit.yml@refs/heads/main"
        ),
        expected_workflow_sha="c" * 40,
        expected_job_workflow_ref=(
            "onejumpinc/officeqa-pro-v2-agentbeats/"
            f".github/workflows/quick-submit-runner.yml@{'b' * 40}"
        ),
        expected_job_workflow_sha="b" * 40,
        expected_submission_id="01234567-89ab-4def-8123-456789abcdef",
        expected_pr_number=42,
        expected_actor="agentbeats-dev[bot]",
        expected_head_repository="onejumpinc/officeqa-pro-v2-agentbeats",
        expected_base_sha="c" * 40,
        expected_head_sha="d" * 40,
    )

    provenance["github_actions"]["job_workflow_sha"] = "e" * 40
    provenance.pop("pull_request")
    with pytest.raises(ValueError, match="job_workflow_sha"):
        verify_provenance(
            provenance,
            scenario_kind="generated",
            expected_job_workflow_sha="b" * 40,
        )


def test_provenance_rejects_workflow_retry() -> None:
    provenance = _provenance()
    provenance["github_actions"]["run_attempt"] = 2
    with pytest.raises(ValueError, match="run_attempt"):
        verify_provenance(provenance, scenario_kind="self-run")


def test_provenance_binds_exact_result_hash() -> None:
    provenance = _provenance()
    with pytest.raises(ValueError, match="result artifact"):
        verify_provenance(
            provenance,
            scenario_kind="self-run",
            expected_results_sha256="1" * 64,
        )


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
    quick_run = _frozen_runner()
    manual_run = (ROOT / ".github/workflows/run-scenario.yml").read_text()
    assert quick_run.index("Verify exact 90/90 release") < quick_run.index(
        "Create verified result commit without a worktree"
    )
    assert manual_run.index("Verify exact 90/90 release") < manual_run.index(
        "Create submission branch and commit results"
    )
    assert "ref: ${{ github.event.pull_request.head.sha }}" not in quick_run
    assert "git checkout" not in quick_run
    assert quick_run.count("ref: ${{ inputs.trusted_runner_sha }}") == 3
    assert quick_run.count("quick_submit_tree.py materialize") == 3
    assert "--require-kind generated" in quick_run
    assert "Compare-and-swap verified result commit" in quick_run
    assert "always() && github.run_attempt == 1" in quick_run
    assert "needs.setup.outputs.submission_id != ''" in quick_run
    assert "create_credentials_file: false" in quick_run
    assert "export_environment_variables: false" in quick_run
    assert "access_token_lifetime: 300s" in quick_run
    assert "verify_exact_result.py compose" in quick_run
    assert "verify_exact_result.py compose-config" in quick_run
    assert "github.run_attempt == 1" in quick_run
    assert quick_run.count("run_attempt: '1'") == 3
    assert quick_run.index(
        "Validate exact workflow identity before executing release tools"
    ) < quick_run.index("Checkout trusted release tools", quick_run.index("  eval:"))
    assert "inputs.backend_url" not in quick_run
    assert "vars.QUICK_SUBMIT" not in quick_run
    assert "printf 'token=%s" not in quick_run
    assert "release-artifact/results.json" in quick_run
    assert ".release-gate/tools/docker_release_wrapper.sh" in quick_run
    assert "Authenticate to GHCR" not in quick_run
    assert "docker-amber-cli" in quick_run
    assert "docker-runtime-images" in quick_run
    assert all("${{" not in block for block in _workflow_run_blocks(quick_run))
    assert ".release-gate/tools/fetch_pinned_dataset.py" in quick_run
    assert all("${{" not in block for block in _workflow_run_blocks(manual_run))
    assert "agentbeats.dev/api/quick-submit" not in manual_run
    assert (
        "GREEN_HF_TOKEN: ${{ secrets.GREEN_HF_TOKEN || "
        "secrets.OFFICEQA_PRO_V2_HF_TOKEN }}" in manual_run
    )
    assert (
        "PARTICIPANT_API_URL: ${{ secrets.PARTICIPANT_API_URL || "
        "vars.PARTICIPANT_API_URL || 'https://api.onejumpinc.com' }}" in manual_run
    )
    assert (
        "PARTICIPANT_API_TOKEN: ${{ secrets.PARTICIPANT_API_TOKEN || "
        "secrets.OFFICEQA_API_TOKEN }}" in manual_run
    )


def test_working_runner_matches_the_immutable_caller_pin() -> None:
    working_runner = (ROOT / ".github/workflows/quick-submit-runner.yml").read_text()
    assert working_runner == _frozen_runner()


def test_quick_submit_calls_agentbeats_v2_runner() -> None:
    workflow = (ROOT / ".github/workflows/quick-submit.yml").read_text()
    trigger = workflow.split("jobs:", maxsplit=1)[0]
    assert "\n  pull_request:\n" in trigger
    assert "\n  pull_request_target:\n" not in trigger
    assert "\n  push:\n" not in trigger
    assert "\n  workflow_dispatch:\n" not in trigger
    assert "types: [opened, reopened]" in workflow
    assert "branches: [main]" in workflow
    assert "startsWith(github.head_ref, 'quick-submit-')" in workflow
    assert (
        "uses: RDI-Foundation/agentbeats-leaderboard-template/"
        ".github/workflows/quick-submit-runner.yml@v2" in workflow
    )
    assert "permissions:\n      id-token: write\n      contents: write" in workflow
    assert "num_shards: 10" in workflow
    assert "trusted_runner_sha" not in workflow
    assert "secrets." not in workflow


def test_manual_workflow_is_hardened_feature_branch_or_fork_run() -> None:
    workflow = (ROOT / ".github/workflows/run-scenario.yml").read_text()
    trigger = workflow.split("env:", maxsplit=1)[0]
    assert "\n  push:\n" in trigger
    assert "\n  workflow_dispatch:\n" in trigger
    assert "branches-ignore:" in trigger
    assert "- main" in trigger
    assert "The feature-branch route requires manual dispatch" in workflow
    assert "submission_mode='feature-branch'" in workflow
    assert ".full_name == $target and .fork == false" in workflow
    assert ".parent.full_name == $target" in workflow
    assert "git merge-base --is-ancestor" in workflow
    assert "Require canonical release controls and scenario" in workflow
    assert "shard_indices=[0,1,2,3,4,5,6,7,8,9]" in workflow
    assert "num_shards = 10" in workflow
    assert "--require-kind self-run" in workflow
    assert "--force-with-lease" in workflow
    assert "Open the upstream result pull request" in workflow
    assert "environment: officeqa-production" not in workflow


@pytest.mark.parametrize("route", ["feature-branch", "public-fork"])
def test_manual_submission_evidence_passes(tmp_path: Path, route: str) -> None:
    dataset_path, rows = _dataset(tmp_path)
    del dataset_path
    scenario = _scenario()
    artifact = _artifact(rows)
    artifact["participants"] = scenario["metadata"]["agentbeats_ids"]

    feature_branch_route = route == "feature-branch"
    head_repository = (
        "onejumpinc/officeqa-pro-v2-agentbeats"
        if feature_branch_route
        else "forker/officeqa-pro-v2-agentbeats"
    )
    source_branch = "benchmark"
    source_sha = "a" * 40
    result_sha = "b" * 40
    run_id = 123
    source_owner = "onejumpinc" if feature_branch_route else "forker"
    unique_name = f"{source_owner}-{run_id}"
    run_url = f"https://github.com/{head_repository}/actions/runs/{run_id}"
    workflow_ref = (
        f"{head_repository}/.github/workflows/run-scenario.yml@"
        f"refs/heads/{source_branch}"
    )

    result_path = tmp_path / "results.json"
    result_path.write_text(json.dumps(artifact))
    provenance = _provenance()
    provenance["results_sha256"] = hashlib.sha256(result_path.read_bytes()).hexdigest()
    provenance["github_actions"] = {
        "run_url": run_url,
        "ref": f"refs/heads/{source_branch}",
        "sha": source_sha,
        "repository_url": f"https://github.com/{head_repository}",
        "workflow_ref": workflow_ref,
        "workflow_sha": source_sha,
        "job_workflow_ref": workflow_ref,
        "job_workflow_sha": source_sha,
        "run_attempt": 1,
    }
    provenance_path = tmp_path / "provenance.json"
    provenance_path.write_text(json.dumps(provenance))
    scenario_path = tmp_path / "scenario.json5"
    source_scenario_path = tmp_path / "source-scenario.json5"
    scenario_bytes = json.dumps(scenario).encode()
    scenario_path.write_bytes(scenario_bytes)
    source_scenario_path.write_bytes(scenario_bytes)
    changed_files_path = tmp_path / "changed-files.json"
    changed_files_path.write_text(
        json.dumps(
            [
                {"filename": f"results/{unique_name}.json", "status": "added"},
                {
                    "filename": f"submissions/{unique_name}.json5",
                    "status": "added",
                },
                {
                    "filename": f"submissions/{unique_name}-provenance.json",
                    "status": "added",
                },
            ]
        )
    )
    run_metadata_path = tmp_path / "run.json"
    run_metadata_path.write_text(
        json.dumps(
            {
                "id": run_id,
                "run_attempt": 1,
                "event": "workflow_dispatch",
                "status": "completed",
                "conclusion": "success",
                "path": ".github/workflows/run-scenario.yml",
                "repository": {"full_name": head_repository},
                "actor": {"login": source_owner},
                "triggering_actor": {"login": source_owner},
                "head_sha": source_sha,
                "head_branch": source_branch,
                "html_url": run_url,
            }
        )
    )
    repository_metadata_path = tmp_path / "repository.json"
    repository_metadata = {
        "full_name": head_repository,
        "fork": not feature_branch_route,
        "visibility": "public",
    }
    if not feature_branch_route:
        repository_metadata["parent"] = {
            "full_name": "onejumpinc/officeqa-pro-v2-agentbeats"
        }
    repository_metadata_path.write_text(json.dumps(repository_metadata))

    verify_submission(
        result_path=result_path,
        provenance_path=provenance_path,
        scenario_path=scenario_path,
        source_scenario_path=source_scenario_path,
        changed_files_path=changed_files_path,
        run_metadata_path=run_metadata_path,
        repository_metadata_path=repository_metadata_path,
        head_repository=head_repository,
        head_ref=f"submission-{unique_name}",
        head_sha=result_sha,
        base_repository="onejumpinc/officeqa-pro-v2-agentbeats",
    )

    run_metadata = json.loads(run_metadata_path.read_text())
    run_metadata["conclusion"] = "failure"
    run_metadata_path.write_text(json.dumps(run_metadata))
    with pytest.raises(ValueError, match="did not complete successfully"):
        verify_submission(
            result_path=result_path,
            provenance_path=provenance_path,
            scenario_path=scenario_path,
            source_scenario_path=source_scenario_path,
            changed_files_path=changed_files_path,
            run_metadata_path=run_metadata_path,
            repository_metadata_path=repository_metadata_path,
            head_repository=head_repository,
            head_ref=f"submission-{unique_name}",
            head_sha=result_sha,
            base_repository="onejumpinc/officeqa-pro-v2-agentbeats",
        )

    if feature_branch_route:
        run_metadata["conclusion"] = "success"
        run_metadata["event"] = "push"
        run_metadata_path.write_text(json.dumps(run_metadata))
        with pytest.raises(ValueError, match="must use workflow_dispatch"):
            verify_submission(
                result_path=result_path,
                provenance_path=provenance_path,
                scenario_path=scenario_path,
                source_scenario_path=source_scenario_path,
                changed_files_path=changed_files_path,
                run_metadata_path=run_metadata_path,
                repository_metadata_path=repository_metadata_path,
                head_repository=head_repository,
                head_ref=f"submission-{unique_name}",
                head_sha=result_sha,
                base_repository="onejumpinc/officeqa-pro-v2-agentbeats",
            )
