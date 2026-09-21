#!/usr/bin/env python3
"""Fail closed unless an OfficeQA Pro v2 public run is the exact 90/90 release."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

BENCHMARK = "OfficeQA Pro v2"
DATASET_REVISION = "65a2b315780417bc50d7bfe6e5bdb904e63fda65"
DATASET_SHA256 = "7e253ed35c2ad80f365140beacb4549f21733c9072938bf35cea41879b76182b"
DATASET_SEMANTIC_SHA256 = (
    "e8dbf350a9e0dd1be8464744a012f17dba6605cd2a7f1e850c06dcc3562cab54"
)
EXPECTED_ROWS = 90
EXPECTED_SHARDS = 10
PURPLE_AGENT_ID = "01a05b80-58e6-7e71-95e9-656bde816e85"

GATEWAY_MANIFEST = (
    "https://raw.githubusercontent.com/RDI-Foundation/agentbeats-gateway/"
    "ca6dd30904f98bfdfbff2f79fb035e854c93a8d3/amber-manifest.json5"
)
GENERATED_GATEWAY_MANIFEST = (
    "https://raw.githubusercontent.com/RDI-Foundation/agentbeats-gateway/"
    "refs/tags/v0.3/amber-manifest.json5"
)
GREEN_MANIFEST = (
    "https://raw.githubusercontent.com/onejumpinc/officeqa-pro-v2-agentbeats/"
    "9ac7f2c39d16e13b2e10ddb3f73c63cdc9d278ad/green-agent.json5"
)
PURPLE_MANIFESTS = {
    (
        "https://raw.githubusercontent.com/onejumpinc/officeqa-agentbeats/"
        "d376c66f2be259674704ae4cc71df1fe3c9b54ce/amber-manifest.json5"
    ),
    # The existing registered purple agent uses this URL. Its resolved image is
    # still checked byte-for-byte through provenance below.
    "https://raw.githubusercontent.com/onejumpinc/officeqa-agentbeats/main/amber-manifest.json5",
}
EXPECTED_IMAGES = {
    (
        "ghcr.io/rdi-foundation/agentbeats-gateway@"
        "sha256:3f9976889c598092dc4273312ec431cbc48bbe064ff65b5613425f4990bc1d4c"
    ),
    (
        "ghcr.io/onejumpinc/officeqa-pro-v2-benchmark@"
        "sha256:79db435c4a563090391fcbc3b9b656850efc3a04746de6e20982c39702740ff7"
    ),
    (
        "ghcr.io/onejumpinc/officeqa-proxy-agent@"
        "sha256:7a6d2d64b9a582b0a57460d13ecb5ef4641afdac8d71d864007c2ce7380ce8fa"
    ),
}
EXPECTED_MANIFEST_SOURCES = {
    "gateway": {
        "url": GATEWAY_MANIFEST,
        "raw_sha256": "0ef4afd064263eaacddf0fc93bb735fffce999491b96b2dccebb573f3847c6f9",
    },
    "green": {
        "url": GREEN_MANIFEST,
        "raw_sha256": "019d98d164d479c77724dda4c20809df0ad1229b97b097893d9a98909f577946",
    },
    "purple": {
        "url": min(PURPLE_MANIFESTS),
        "raw_sha256": "7175137be7a12305c47f0535f7ece1130dace1bc2537ebd0bcc849021579b4c5",
    },
}

UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
MANIFEST_DIGEST_RE = re.compile(r"^sha256:[A-Za-z0-9+/]{43}=$")


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain a JSON object")
    return value


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"{label} must be an object")
    return value


def _as_number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{label} is not numeric: {value!r}")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{label} is not finite")
    return number


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_dataset(
    path: Path,
    expected_raw_sha256: str | None = DATASET_SHA256,
    expected_semantic_sha256: str | None = DATASET_SEMANTIC_SHA256,
) -> list[dict[str, str]]:
    raw_digest = _sha256(path)
    if expected_raw_sha256 and raw_digest != expected_raw_sha256:
        raise ValueError(
            f"dataset raw SHA-256 is {raw_digest}, expected {expected_raw_sha256}"
        )

    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    required = {"uid", "question", "answer", "source_docs", "source_files"}
    if len(rows) != EXPECTED_ROWS:
        raise ValueError(f"dataset has {len(rows)} rows, expected {EXPECTED_ROWS}")
    if not rows or not required.issubset(rows[0]):
        raise ValueError("dataset schema is missing required columns")
    if any(
        not row.get("uid") or not row.get("question") or not row.get("answer")
        for row in rows
    ):
        raise ValueError("dataset has an empty uid, question, or answer")
    if len({row["uid"] for row in rows}) != EXPECTED_ROWS:
        raise ValueError("dataset UIDs are not unique")
    if len({row["question"].strip() for row in rows}) != EXPECTED_ROWS:
        raise ValueError("dataset questions are not unique")

    semantic_rows = [
        {key: row[key] for key in ("uid", "question", "answer")} for row in rows
    ]
    payload = json.dumps(
        semantic_rows, ensure_ascii=False, separators=(",", ":")
    ).encode()
    semantic_digest = hashlib.sha256(payload).hexdigest()
    if expected_semantic_sha256 and semantic_digest != expected_semantic_sha256:
        raise ValueError(
            f"dataset semantic SHA-256 is {semantic_digest}, "
            f"expected {expected_semantic_sha256}"
        )
    return rows


def _verify_assessment(
    assessment: dict[str, Any], *, require_shard_index: bool
) -> None:
    num_shards = assessment.get("num_shards")
    if (
        isinstance(num_shards, bool)
        or not isinstance(num_shards, int)
        or num_shards != EXPECTED_SHARDS
    ):
        raise ValueError(f"num_shards must be exactly {EXPECTED_SHARDS}")
    shard_index = assessment.get("shard_index")
    if require_shard_index and (
        isinstance(shard_index, bool)
        or not isinstance(shard_index, int)
        or shard_index != 0
    ):
        raise ValueError("unpatched scenario shard_index must be exactly 0")
    if (
        not require_shard_index
        and shard_index is not None
        and (
            isinstance(shard_index, bool)
            or not isinstance(shard_index, int)
            or shard_index != 0
        )
    ):
        raise ValueError("generated scenario shard_index must be absent or 0")
    if "num_instances" in assessment:
        raise ValueError("num_instances is forbidden for a scored public run")
    if _as_number(assessment.get("tolerance"), "tolerance") != 0.0:
        raise ValueError("tolerance must be exactly 0")
    if _as_number(assessment.get("timeout_seconds"), "timeout_seconds") != 900.0:
        raise ValueError("timeout_seconds must be exactly 900")


def _binding_set(scenario: dict[str, Any]) -> set[tuple[str, str, bool]]:
    bindings = scenario.get("bindings")
    if not isinstance(bindings, list):
        raise TypeError("scenario.bindings must be an array")
    actual_bindings: set[tuple[str, str, bool]] = set()
    for binding in bindings:
        item = _mapping(binding, "scenario binding")
        actual_bindings.add(
            (str(item.get("to")), str(item.get("from")), item.get("weak") is True)
        )
    if len(actual_bindings) != len(bindings):
        raise ValueError("scenario contains duplicate bindings")
    return actual_bindings


def _verify_registered_id(value: Any, label: str) -> str:
    if not isinstance(value, str) or not UUID_RE.fullmatch(value):
        raise ValueError(f"{label} is missing or still a placeholder")
    return value


def _verify_secret_schema(scenario: dict[str, Any], expected_keys: set[str]) -> None:
    schema = _mapping(scenario.get("config_schema"), "scenario.config_schema")
    if (
        schema.get("type") != "object"
        or schema.get("additionalProperties") is not False
    ):
        raise ValueError("scenario config_schema object controls are not exact")
    properties = _mapping(schema.get("properties"), "config_schema.properties")
    if set(properties) != expected_keys:
        raise ValueError("scenario config_schema properties are not exact")
    for key, value in properties.items():
        if value != {"type": "string", "secret": True}:
            raise ValueError(
                f"config_schema property {key} is not an exact string secret"
            )
    required = schema.get("required")
    if not isinstance(required, list) or len(required) != len(expected_keys):
        raise ValueError("scenario config_schema required list is not exact")
    if set(required) != expected_keys:
        raise ValueError("scenario config_schema required keys are not exact")


def _verify_self_run_scenario(
    scenario: dict[str, Any], components: dict[str, Any]
) -> None:
    if scenario.get("manifest_version") != "0.4.0":
        raise ValueError("self-run manifest_version must be 0.4.0")
    if scenario.get("experimental_features") != ["docker"]:
        raise ValueError("self-run experimental_features must be exactly ['docker']")
    _verify_secret_schema(
        scenario,
        {"green_hf_token", "participant_api_url", "participant_api_token"},
    )

    gateway = _mapping(components["gateway"], "components.gateway")
    if gateway.get("manifest") != GATEWAY_MANIFEST:
        raise ValueError("gateway manifest is not pinned to the approved commit")
    gateway_config = _mapping(gateway.get("config"), "gateway.config")
    if set(gateway_config) != {"assessment_config", "participant_roles"}:
        raise ValueError("self-run gateway config has unexpected fields")
    assessment = _mapping(
        gateway_config.get("assessment_config"),
        "gateway.config.assessment_config",
    )
    _verify_assessment(assessment, require_shard_index=True)
    expected_roles = {"green": "officeqa_pro_v2_green", "purple1": "agent"}
    if gateway_config.get("participant_roles") != expected_roles:
        raise ValueError("gateway participant_roles do not match the self-run release")

    green = _mapping(
        components["officeqa_pro_v2_green"], "components.officeqa_pro_v2_green"
    )
    if green.get("manifest") != GREEN_MANIFEST:
        raise ValueError("green manifest is not pinned to the approved commit")
    if green.get("config") != {"hf_token": "${config.green_hf_token}"}:
        raise ValueError("green dataset token binding is not exact")

    purple = _mapping(components["opencode_agent"], "components.opencode_agent")
    if purple.get("manifest") not in PURPLE_MANIFESTS:
        raise ValueError("purple manifest is not an approved OfficeQA proxy manifest")
    if purple.get("config") != {
        "officeqa_api_url": "${config.participant_api_url}",
        "officeqa_api_token": "${config.participant_api_token}",
    }:
        raise ValueError("purple endpoint secret bindings are not exact")

    expected_bindings = {
        ("#gateway.green", "#officeqa_pro_v2_green.a2a", False),
        ("#gateway.purple1", "#opencode_agent.a2a", False),
        ("#officeqa_pro_v2_green.proxy", "#gateway.proxy", True),
        ("#opencode_agent.proxy", "#gateway.proxy", True),
    }
    if _binding_set(scenario) != expected_bindings:
        raise ValueError("scenario bindings do not match the self-run topology")

    expected_exports = {
        "results": "#gateway.results",
        "participant_proxy": "#gateway.proxy",
    }
    if scenario.get("exports") != expected_exports:
        raise ValueError("scenario exports do not match the release topology")

    metadata = _mapping(scenario.get("metadata"), "scenario.metadata")
    ids = _mapping(metadata.get("agentbeats_ids"), "metadata.agentbeats_ids")
    if set(ids) != {"officeqa_pro_v2_green", "agent", "opencode_agent"}:
        raise ValueError("self-run agentbeats_ids keys are not exact")
    if ids["agent"] != PURPLE_AGENT_ID or ids["opencode_agent"] != PURPLE_AGENT_ID:
        raise ValueError(
            "self-run metadata does not identify the approved purple agent"
        )
    green_id = _verify_registered_id(
        ids["officeqa_pro_v2_green"], "the registered green AgentBeats ID"
    )
    if green_id == PURPLE_AGENT_ID:
        raise ValueError("green and purple AgentBeats IDs must differ")


def _verify_generated_scenario(
    scenario: dict[str, Any], components: dict[str, Any]
) -> None:
    if scenario.get("manifest_version") != "0.1.0":
        raise ValueError("generated manifest_version must be 0.1.0")
    if scenario.get("experimental_features") != ["docker"]:
        raise ValueError("generated experimental_features must be exactly ['docker']")
    _verify_secret_schema(
        scenario,
        {
            "green_hf_token",
            "agent_officeqa_api_url",
            "agent_officeqa_api_token",
        },
    )

    gateway = _mapping(components["gateway"], "components.gateway")
    if gateway.get("manifest") not in {GATEWAY_MANIFEST, GENERATED_GATEWAY_MANIFEST}:
        raise ValueError("generated gateway manifest is not the approved v0.3 manifest")
    gateway_config = _mapping(gateway.get("config"), "gateway.config")
    if not {"assessment_config", "participant_roles"}.issubset(gateway_config):
        raise ValueError("generated gateway config is incomplete")
    if set(gateway_config) - {
        "assessment_config",
        "participant_roles",
        "callback_urls",
    }:
        raise ValueError("generated gateway config has unexpected fields")
    if gateway_config.get("callback_urls") not in (None, {}):
        raise ValueError("generated callback_urls must be absent or empty")
    assessment = _mapping(
        gateway_config.get("assessment_config"),
        "gateway.config.assessment_config",
    )
    _verify_assessment(assessment, require_shard_index=False)
    if gateway_config.get("participant_roles") != {
        "green": "green",
        "purple1": "agent",
    }:
        raise ValueError("generated gateway participant_roles are not exact")

    green = _mapping(components["green"], "components.green")
    if green.get("manifest") != GREEN_MANIFEST:
        raise ValueError("generated green manifest is not the approved pinned manifest")
    if green.get("config") != {"hf_token": "${config.green_hf_token}"}:
        raise ValueError("generated green dataset token binding is not exact")

    purple = _mapping(components["agent"], "components.agent")
    if purple.get("manifest") not in PURPLE_MANIFESTS:
        raise ValueError("generated purple manifest is not approved")
    if purple.get("config") != {
        "officeqa_api_url": "${config.agent_officeqa_api_url}",
        "officeqa_api_token": "${config.agent_officeqa_api_token}",
    }:
        raise ValueError("generated purple endpoint secret bindings are not exact")

    base_bindings = {
        ("#gateway.green", "#green.a2a", False),
        ("#gateway.purple1", "#agent.a2a", False),
        ("#green.proxy", "#gateway.proxy", True),
    }
    actual_bindings = _binding_set(scenario)
    allowed_bindings = base_bindings | {
        ("#agent.proxy", "#gateway.proxy", True),
    }
    if not base_bindings.issubset(actual_bindings) or not actual_bindings.issubset(
        allowed_bindings
    ):
        raise ValueError("scenario bindings do not match generated release topology")
    if scenario.get("exports") != {"results": "#gateway.results"}:
        raise ValueError("generated scenario exports are not exact")

    metadata = _mapping(scenario.get("metadata"), "scenario.metadata")
    ids = _mapping(metadata.get("agentbeats_ids"), "metadata.agentbeats_ids")
    if set(ids) != {"green", "agent"}:
        raise ValueError("generated agentbeats_ids keys are not exact")
    if ids["agent"] != PURPLE_AGENT_ID:
        raise ValueError("generated scenario does not use the approved purple agent")
    green_id = _verify_registered_id(ids["green"], "the generated green AgentBeats ID")
    if green_id == PURPLE_AGENT_ID:
        raise ValueError("green and purple AgentBeats IDs must differ")


def verify_scenario(scenario: dict[str, Any]) -> None:
    components = _mapping(scenario.get("components"), "scenario.components")
    component_names = set(components)
    if component_names == {"gateway", "officeqa_pro_v2_green", "opencode_agent"}:
        _verify_self_run_scenario(scenario, components)
    elif component_names == {"gateway", "green", "agent"}:
        _verify_generated_scenario(scenario, components)
    else:
        raise ValueError(f"unexpected scenario components: {sorted(components)}")


def _find_shards(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        if value.get("benchmark") == BENCHMARK:
            return [value]
        shards: list[dict[str, Any]] = []
        for child in value.values():
            shards.extend(_find_shards(child))
        return shards
    if isinstance(value, list):
        shards = []
        for child in value:
            shards.extend(_find_shards(child))
        return shards
    return []


def verify_artifact(artifact: dict[str, Any], rows: list[dict[str, str]]) -> None:
    if artifact.get("status") != "completed":
        raise ValueError(f"result status is {artifact.get('status')!r}, not completed")
    participants = _mapping(artifact.get("participants"), "result participants")
    if participants.get("agent") != PURPLE_AGENT_ID:
        raise ValueError(
            f"participants.agent is {participants.get('agent')!r}, "
            f"expected {PURPLE_AGENT_ID!r}"
        )

    expected_by_shard = {
        index: {
            row["uid"]
            for position, row in enumerate(rows)
            if position % EXPECTED_SHARDS == index
        }
        for index in range(EXPECTED_SHARDS)
    }
    expected_uids = {row["uid"] for row in rows}
    shards = _find_shards(artifact.get("results"))
    if len(shards) != EXPECTED_SHARDS:
        raise ValueError(
            f"found {len(shards)} shard results, expected {EXPECTED_SHARDS}"
        )

    seen_indices: set[int] = set()
    seen_uids: set[str] = set()
    total_score = 0.0
    total_max = 0.0
    for shard in shards:
        if shard.get("dataset_revision") != DATASET_REVISION:
            raise ValueError(
                f"unexpected dataset revision {shard.get('dataset_revision')!r}"
            )
        shard_index = shard.get("shard_index")
        if isinstance(shard_index, bool) or not isinstance(shard_index, int):
            raise TypeError(f"invalid shard_index {shard_index!r}")
        if not 0 <= shard_index < EXPECTED_SHARDS or shard_index in seen_indices:
            raise ValueError(f"duplicate or out-of-range shard index {shard_index}")
        shard_count = shard.get("num_shards")
        if (
            isinstance(shard_count, bool)
            or not isinstance(shard_count, int)
            or shard_count != EXPECTED_SHARDS
        ):
            raise ValueError(f"shard {shard_index} reports num_shards={shard_count!r}")
        seen_indices.add(shard_index)

        rewards = _mapping(shard.get("task_rewards"), f"shard {shard_index} rewards")
        reward_uids = set(rewards)
        if reward_uids != expected_by_shard[shard_index]:
            missing = sorted(expected_by_shard[shard_index] - reward_uids)
            extra = sorted(reward_uids - expected_by_shard[shard_index])
            raise ValueError(
                f"shard {shard_index} UID mismatch: missing={missing}, extra={extra}"
            )
        for uid, reward in rewards.items():
            if _as_number(reward, f"reward {uid}") != 1.0:
                raise ValueError(f"{uid} reward is {reward!r}, expected 1.0")

        score = _as_number(shard.get("score"), f"shard {shard_index} score")
        max_score = _as_number(shard.get("max_score"), f"shard {shard_index} max_score")
        pass_rate = _as_number(shard.get("pass_rate"), f"shard {shard_index} pass_rate")
        elapsed = _as_number(shard.get("time_used"), f"shard {shard_index} time_used")
        if elapsed < 0:
            raise ValueError(f"shard {shard_index} has negative time_used")
        if score != float(len(rewards)) or max_score != float(len(rewards)):
            raise ValueError(
                f"shard {shard_index} score/max_score disagree with task_rewards"
            )
        if pass_rate != 100.0:
            raise ValueError(f"shard {shard_index} pass_rate is {pass_rate}, not 100")
        if shard.get("error_count") != 0 or shard.get("error_types") != {}:
            raise ValueError(f"shard {shard_index} reports evaluation errors")

        seen_uids.update(reward_uids)
        total_score += score
        total_max += max_score

    if seen_indices != set(range(EXPECTED_SHARDS)):
        raise ValueError("shard index coverage is incomplete")
    if seen_uids != expected_uids:
        raise ValueError("aggregate UID coverage is incomplete")
    if total_score != EXPECTED_ROWS or total_max != EXPECTED_ROWS:
        raise ValueError(
            f"aggregate score is {total_score:g}/{total_max:g}, "
            f"expected {EXPECTED_ROWS}/{EXPECTED_ROWS}"
        )


def verify_provenance(
    provenance: dict[str, Any],
    *,
    expected_run_url: str | None = None,
    expected_repository_url: str | None = None,
    expected_github_sha: str | None = None,
) -> None:
    images = _mapping(provenance.get("image_digests"), "provenance.image_digests")
    actual_images = set(images.values())
    if actual_images != EXPECTED_IMAGES or len(images) != len(EXPECTED_IMAGES):
        raise ValueError(
            "runtime image digests differ from the exact release set: "
            f"got={sorted(actual_images)}"
        )

    release_manifests = _mapping(
        provenance.get("release_manifests"), "provenance.release_manifests"
    )
    if release_manifests != EXPECTED_MANIFEST_SOURCES:
        raise ValueError(
            "release manifest sources do not match the immutable release set"
        )

    manifests = _mapping(
        provenance.get("manifest_digests"), "provenance.manifest_digests"
    )
    if len(manifests) != 4:
        raise ValueError(f"expected 4 manifest digests, found {len(manifests)}")
    if any(
        not isinstance(value, str) or not MANIFEST_DIGEST_RE.fullmatch(value)
        for value in manifests.values()
    ):
        raise ValueError("provenance contains an invalid manifest digest")

    timestamp = provenance.get("timestamp")
    if not isinstance(timestamp, str) or not timestamp.endswith("Z"):
        raise ValueError("provenance timestamp is missing or is not UTC")
    actions = _mapping(provenance.get("github_actions"), "provenance.github_actions")
    for key in (
        "run_url",
        "ref",
        "sha",
        "repository_url",
        "workflow_ref",
        "workflow_sha",
    ):
        if not isinstance(actions.get(key), str) or not actions[key]:
            raise ValueError(f"provenance.github_actions.{key} is missing")
    if expected_run_url and actions["run_url"] != expected_run_url:
        raise ValueError("provenance run_url does not identify this workflow run")
    if expected_repository_url and actions["repository_url"] != expected_repository_url:
        raise ValueError("provenance repository_url does not identify this repository")
    if expected_github_sha and actions["sha"] != expected_github_sha:
        raise ValueError("provenance SHA does not identify this workflow revision")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    scenario_parser = subparsers.add_parser("scenario", help="verify release scenario")
    scenario_parser.add_argument("--scenario", type=Path, required=True)

    result_parser = subparsers.add_parser("result", help="verify exact public result")
    result_parser.add_argument("--artifact", type=Path, required=True)
    result_parser.add_argument("--dataset", type=Path, required=True)
    result_parser.add_argument("--provenance", type=Path, required=True)
    result_parser.add_argument("--scenario", type=Path, required=True)
    result_parser.add_argument("--expected-run-url")
    result_parser.add_argument("--expected-repository-url")
    result_parser.add_argument("--expected-github-sha")
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        scenario = _load_json(args.scenario)
        verify_scenario(scenario)
        if args.command == "result":
            rows = load_dataset(args.dataset)
            verify_artifact(_load_json(args.artifact), rows)
            verify_provenance(
                _load_json(args.provenance),
                expected_run_url=args.expected_run_url,
                expected_repository_url=args.expected_repository_url,
                expected_github_sha=args.expected_github_sha,
            )
    except (OSError, TypeError, json.JSONDecodeError, ValueError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    if args.command == "scenario":
        print("PASS: exact full-release scenario preflight")
    else:
        print(
            f"PASS: exact {EXPECTED_ROWS}/{EXPECTED_ROWS}; {EXPECTED_SHARDS} shards; "
            f"participant {PURPLE_AGENT_ID}; runtime provenance pinned"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
