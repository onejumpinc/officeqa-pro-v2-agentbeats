#!/usr/bin/env python3
"""Fail closed unless an OfficeQA Pro v2 public run is the exact 90/90 release."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import sys
from collections import Counter
from datetime import datetime
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
GREEN_AGENT_ID = "01a0db6d-5b2b-7551-9ab3-45b9ae72080c"

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
PINNED_PURPLE_MANIFEST = (
    "https://raw.githubusercontent.com/onejumpinc/officeqa-agentbeats/"
    "d376c66f2be259674704ae4cc71df1fe3c9b54ce/amber-manifest.json5"
)
COMPILE_MANIFESTS = {
    "gateway": "release-manifests/gateway.json5",
    "green": "release-manifests/green.json5",
    "purple": "release-manifests/purple.json5",
}
AMBER_CLI_IMAGE = (
    "ghcr.io/rdi-foundation/amber-cli@"
    "sha256:3514b6cf27896e8cc9a148e8ebdc96ae5a15fe36deec69b7250ab25e126511ca"
)
GATEWAY_COMPILED_IMAGE = "ghcr.io/rdi-foundation/agentbeats-gateway:v0.3"
GATEWAY_RUNTIME_IMAGE = (
    "ghcr.io/rdi-foundation/agentbeats-gateway@"
    "sha256:3f9976889c598092dc4273312ec431cbc48bbe064ff65b5613425f4990bc1d4c"
)
GREEN_RUNTIME_IMAGE = (
    "ghcr.io/onejumpinc/officeqa-pro-v2-benchmark@"
    "sha256:79db435c4a563090391fcbc3b9b656850efc3a04746de6e20982c39702740ff7"
)
PURPLE_RUNTIME_IMAGE = (
    "ghcr.io/onejumpinc/officeqa-proxy-agent@"
    "sha256:7a6d2d64b9a582b0a57460d13ecb5ef4641afdac8d71d864007c2ce7380ce8fa"
)
EXPECTED_IMAGES = {
    GATEWAY_RUNTIME_IMAGE,
    GREEN_RUNTIME_IMAGE,
    PURPLE_RUNTIME_IMAGE,
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
        "url": PINNED_PURPLE_MANIFEST,
        "raw_sha256": "7175137be7a12305c47f0535f7ece1130dace1bc2537ebd0bcc849021579b4c5",
    },
}
EXPECTED_TOOL_IMAGES = {"amber_cli": AMBER_CLI_IMAGE}
EXPECTED_FRAMEWORK_IMAGES = {
    "amber_control_curl": (
        "curlimages/curl@"
        "sha256:94e9e444bcba979c2ea12e27ae39bee4cd10bc7041a472c4727a558e213744e6"
    ),
    "amber_helper": (
        "ghcr.io/rdi-foundation/amber-helper@"
        "sha256:135c9ec8b7ff5670d28a1b7b081571843e46605051ffea7adb36f5694265d905"
    ),
    "amber_otelcol": (
        "otel/opentelemetry-collector-contrib@"
        "sha256:3bc07732530c87c53f9103b01a3afed972fdeba26087a590c1098781736e58c2"
    ),
    "amber_provisioner": (
        "ghcr.io/rdi-foundation/amber-provisioner@"
        "sha256:c17f4496f5cd9750155224d79bfc35ff48ec215dd83e8031a8c75694c76cb113"
    ),
    "amber_router": (
        "ghcr.io/rdi-foundation/amber-router@"
        "sha256:5406fcb7c5d944f46c31b0131b37e14951fd7336fe71d24ee1a18b62f91e1482"
    ),
    "busybox": (
        "busybox@"
        "sha256:73aaf090f3d85aa34ee199857f03fa3a95c8ede2ffd4cc2cdb5b94e566b11662"
    ),
}

_COMPOSE_SOURCE_IMAGE_COUNTS = {
    "${AMBER_OTELCOL_IMAGE:-otel/opentelemetry-collector-contrib:0.143.0}": 1,
    "busybox:1.36.1": 1,
    GATEWAY_COMPILED_IMAGE: 1,
    GREEN_RUNTIME_IMAGE: 1,
    PURPLE_RUNTIME_IMAGE: 1,
    "ghcr.io/rdi-foundation/amber-helper:v0.3": 4,
    "ghcr.io/rdi-foundation/amber-provisioner:v0.1": 1,
    "ghcr.io/rdi-foundation/amber-router:v0.1": 4,
}
_COMPOSE_IMAGE_REPLACEMENTS = {
    "${AMBER_OTELCOL_IMAGE:-otel/opentelemetry-collector-contrib:0.143.0}": (
        EXPECTED_FRAMEWORK_IMAGES["amber_otelcol"]
    ),
    "busybox:1.36.1": EXPECTED_FRAMEWORK_IMAGES["busybox"],
    GATEWAY_COMPILED_IMAGE: GATEWAY_RUNTIME_IMAGE,
    GREEN_RUNTIME_IMAGE: GREEN_RUNTIME_IMAGE,
    PURPLE_RUNTIME_IMAGE: PURPLE_RUNTIME_IMAGE,
    "ghcr.io/rdi-foundation/amber-helper:v0.3": EXPECTED_FRAMEWORK_IMAGES[
        "amber_helper"
    ],
    "ghcr.io/rdi-foundation/amber-provisioner:v0.1": EXPECTED_FRAMEWORK_IMAGES[
        "amber_provisioner"
    ],
    "ghcr.io/rdi-foundation/amber-router:v0.1": EXPECTED_FRAMEWORK_IMAGES[
        "amber_router"
    ],
}

_CHILD_MANIFEST_DIGESTS = {
    "gateway": "sha256:Ba99ymNGSymbrF9jGwLfnZaSnzPrw9sTJ5veaYMxV2Q=",
    "green": "sha256:k05m8xoHnYoPwBfLrP2fhAa8ipVxIn+S4UuicaSJNvo=",
    "purple": "sha256:FqVrezifzyqnAacQEFw0fUNChsSTaeIEZ09JCLa7SRo=",
}
_GENERATED_ROOT_DIGESTS = (
    "sha256:kStPbprHWRBrnvgZhZqLnS3w0N9ctMv68h+Q1clHmKc=",
    "sha256:tr0X8h6cCMKY4Ko/Dh6433AKOUL70SJJ4A176x3jPwA=",
    "sha256:8UM6HHbYMG0Y+4UaQ2WFT2n4XHmj45f4Tx05eK8Tbpw=",
    "sha256:CjrZXS/AEE0ZK1Pd2tgEVMdzmTR5KQ682et44/WBBzA=",
    "sha256:fydWDF5VERvyZlEpgb017ptwqUDaqvoCLWYPbYljleQ=",
    "sha256:bbIA6sRFJk+PTlVotewqTfvbnHMUl/1buGEkH35SfuY=",
    "sha256:EIfufeXStQo2fKgn+vLzoY5w3RbRL/t19TAeSGcoFQw=",
    "sha256:BDIpek59EeluMeV9MZuRhgkyQ5bFjQ0g7uzxvlxHNR8=",
    "sha256:ytTSdTEuOwHj6PynSLQ2WeEZLq3/d71mYDrYxnMraIY=",
    "sha256:an+gsMw/eXyuimzyDBojv8/NAamNdsFe33woJV/GH40=",
)
_SELF_RUN_ROOT_DIGESTS = (
    "sha256:pptFjLMiNouuAUsBgAMR56nvLSqDXB6yiPeNEOUQQk0=",
    "sha256:yQfKfGw0AZ+6WaNnyoU/e10ISLt7/rtyDkObCB0hY7I=",
    "sha256:q4TJOjKXW8FTPvZD4kTn0M9dYz1p3e6JBwz6MZCHkzU=",
    "sha256:nbUAK6HYJQGVKG/ZGtHgx4qe3OMh5e/ad9lRb4qAIYI=",
    "sha256:0gvDIPfhn4yDU4JAsFUyllsbls5L0EAue+l8GS8sAtI=",
    "sha256:BK/fbM0XvaQZBjTYCn/6NETDYmTy+713yweb/fosTCE=",
    "sha256:gCmBLKiaqR3VBX3tIufokvvG2gBpHBeydtMZ+kLTTpE=",
    "sha256:jTr0ujgBmyunhuUtGKMRCq9IQUVOxZZIGlXHYZ/ohFo=",
    "sha256:9SGRbIhFaaBNK9yE2vUacEuQggrgwa5sleB3rivpjhI=",
    "sha256:UGT+s+Gw4sNF8h/otEoYpaf013e2wLCNcKy4a3z6C40=",
)


def _expected_manifest_digests(kind: str) -> dict[str, dict[str, str]]:
    if kind == "generated":
        roots = _GENERATED_ROOT_DIGESTS
        children = {
            "/agent": _CHILD_MANIFEST_DIGESTS["purple"],
            "/gateway": _CHILD_MANIFEST_DIGESTS["gateway"],
            "/green": _CHILD_MANIFEST_DIGESTS["green"],
        }
    elif kind == "self-run":
        roots = _SELF_RUN_ROOT_DIGESTS
        children = {
            "/gateway": _CHILD_MANIFEST_DIGESTS["gateway"],
            "/officeqa_pro_v2_green": _CHILD_MANIFEST_DIGESTS["green"],
            "/opencode_agent": _CHILD_MANIFEST_DIGESTS["purple"],
        }
    else:
        raise ValueError(f"unknown scenario kind: {kind!r}")
    return {str(index): {"/": root, **children} for index, root in enumerate(roots)}


def _expected_compiled_images(kind: str) -> dict[str, str]:
    if kind == "generated":
        return {
            "/agent": PURPLE_RUNTIME_IMAGE,
            "/gateway": GATEWAY_COMPILED_IMAGE,
            "/green": GREEN_RUNTIME_IMAGE,
        }
    if kind == "self-run":
        return {
            "/gateway": GATEWAY_COMPILED_IMAGE,
            "/officeqa_pro_v2_green": GREEN_RUNTIME_IMAGE,
            "/opencode_agent": PURPLE_RUNTIME_IMAGE,
        }
    raise ValueError(f"unknown scenario kind: {kind!r}")


def _expected_runtime_images(kind: str) -> dict[str, str]:
    expected = _expected_compiled_images(kind)
    return {
        moniker: GATEWAY_RUNTIME_IMAGE if image == GATEWAY_COMPILED_IMAGE else image
        for moniker, image in expected.items()
    }


UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
MANIFEST_DIGEST_RE = re.compile(r"^sha256:[A-Za-z0-9+/]{43}=$")
GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMPOSE_IMAGE_RE = re.compile(
    r"^(?P<prefix>[ \t]+image:[ \t]+)(?P<image>[^ \t\r\n]+)(?P<suffix>[ \t]*)$",
    re.MULTILINE,
)


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


def pin_compose_images(compose_path: Path, framework_output: Path) -> None:
    """Replace every compiler-emitted mutable image tag with an exact digest."""
    if compose_path.is_symlink() or not compose_path.is_file():
        raise ValueError("compiled Compose file must be a regular non-symlink file")
    source = compose_path.read_text(encoding="utf-8")
    source_counts = Counter(
        match.group("image") for match in COMPOSE_IMAGE_RE.finditer(source)
    )
    if source_counts != Counter(_COMPOSE_SOURCE_IMAGE_COUNTS):
        raise ValueError(
            "compiled Compose image references differ from the exact compiler output"
        )

    def replace_image(match: re.Match[str]) -> str:
        image = match.group("image")
        replacement = _COMPOSE_IMAGE_REPLACEMENTS.get(image)
        if replacement is None:
            raise ValueError("compiled Compose contains an unapproved image reference")
        return f"{match.group('prefix')}{replacement}{match.group('suffix')}"

    pinned = COMPOSE_IMAGE_RE.sub(replace_image, source)
    expected_pinned_counts: Counter[str] = Counter()
    for image, count in _COMPOSE_SOURCE_IMAGE_COUNTS.items():
        expected_pinned_counts[_COMPOSE_IMAGE_REPLACEMENTS[image]] += count
    pinned_counts = Counter(
        match.group("image") for match in COMPOSE_IMAGE_RE.finditer(pinned)
    )
    if pinned_counts != expected_pinned_counts:
        raise ValueError("pinned Compose image references are not exact")

    temporary = compose_path.with_name(f".{compose_path.name}.pinned.tmp")
    with temporary.open("x", encoding="utf-8") as handle:
        handle.write(pinned)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, compose_path)

    with framework_output.open("x", encoding="utf-8") as handle:
        json.dump(
            EXPECTED_FRAMEWORK_IMAGES, handle, sort_keys=True, separators=(",", ":")
        )
        handle.write("\n")


def verify_rendered_compose(rendered_path: Path) -> None:
    """Verify Docker Compose resolved only the exact digest-pinned services."""
    rendered = _load_json(rendered_path)
    if "include" in rendered:
        raise ValueError("rendered Compose configuration must not contain include")
    services = _mapping(rendered.get("services"), "rendered Compose services")
    if not services:
        raise ValueError("rendered Compose configuration has no services")

    top_level_volumes = _mapping(
        rendered.get("volumes", {}), "rendered Compose volumes"
    )
    for name, raw_volume in top_level_volumes.items():
        volume = _mapping(raw_volume, f"rendered Compose volume {name}")
        if volume.get("driver_opts"):
            raise ValueError(f"rendered Compose volume {name} uses driver options")
    top_level_configs = _mapping(
        rendered.get("configs", {}), "rendered Compose configs"
    )
    for name, raw_config in top_level_configs.items():
        config = _mapping(raw_config, f"rendered Compose config {name}")
        if "file" in config or config.get("external"):
            raise ValueError(f"rendered Compose config {name} reads an external file")
    if rendered.get("secrets"):
        raise ValueError("rendered Compose configuration must not define secrets")

    actual_images: Counter[str] = Counter()
    for name, raw_service in services.items():
        service = _mapping(raw_service, f"rendered Compose service {name}")
        if "build" in service or "extends" in service:
            raise ValueError(f"rendered Compose service {name} uses build or extends")
        image = service.get("image")
        if not isinstance(image, str) or not image:
            raise ValueError(f"rendered Compose service {name} has no exact image")
        actual_images[image] += 1

        if service.get("privileged") is True:
            raise ValueError(f"rendered Compose service {name} is privileged")
        network_mode = service.get("network_mode")
        if network_mode == "host" or (
            isinstance(network_mode, str) and network_mode.startswith("container:")
        ):
            raise ValueError(
                f"rendered Compose service {name} uses an external network namespace"
            )
        for namespace in ("cgroup", "ipc", "pid", "userns_mode", "uts"):
            mode = service.get(namespace)
            if mode == "host" or (
                isinstance(mode, str) and mode.startswith("container:")
            ):
                raise ValueError(
                    f"rendered Compose service {name} uses external {namespace}"
                )
        if service.get("devices"):
            raise ValueError(f"rendered Compose service {name} exposes host devices")
        if service.get("device_cgroup_rules") or service.get("volumes_from"):
            raise ValueError(
                f"rendered Compose service {name} inherits host device or volume access"
            )
        security_options = service.get("security_opt", [])
        if not isinstance(security_options, list) or any(
            not isinstance(option, str) or "unconfined" in option
            for option in security_options
        ):
            raise ValueError(
                f"rendered Compose service {name} disables a security profile"
            )
        capabilities = service.get("cap_add", [])
        if not isinstance(capabilities, list) or not set(capabilities) <= {"NET_ADMIN"}:
            raise ValueError(
                f"rendered Compose service {name} adds an unapproved capability"
            )
        if "docker.sock" in json.dumps(service, sort_keys=True):
            raise ValueError(
                f"rendered Compose service {name} exposes the Docker socket"
            )

        volumes = service.get("volumes", [])
        if not isinstance(volumes, list):
            raise TypeError(f"rendered Compose service {name} volumes are invalid")
        for volume in volumes:
            if not isinstance(volume, dict):
                raise TypeError(
                    f"rendered Compose service {name} has an invalid volume"
                )
            if volume.get("type") != "bind":
                continue
            if (
                name != "amber-otelcol"
                or volume.get("source") != "/var/lib/docker/containers"
                or volume.get("target") != "/var/lib/docker/containers"
                or volume.get("read_only") is not True
            ):
                raise ValueError(
                    f"rendered Compose service {name} has an unapproved host bind"
                )

        ports = service.get("ports", [])
        if not isinstance(ports, list):
            raise TypeError(f"rendered Compose service {name} ports are invalid")
        for port in ports:
            if not isinstance(port, dict) or port.get("host_ip") != "127.0.0.1":
                raise ValueError(
                    f"rendered Compose service {name} publishes a non-loopback port"
                )

    expected_images: Counter[str] = Counter()
    for image, count in _COMPOSE_SOURCE_IMAGE_COUNTS.items():
        expected_images[_COMPOSE_IMAGE_REPLACEMENTS[image]] += count
    if actual_images != expected_images:
        raise ValueError(
            "rendered Compose service images are not the exact release set"
        )


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
    assessment: dict[str, Any],
    *,
    require_shard_index: bool,
    expected_shard_index: int | None,
) -> None:
    if "num_instances" in assessment:
        raise ValueError("num_instances is forbidden for a scored public run")
    base_keys = {"tolerance", "timeout_seconds", "num_shards"}
    allowed_keys = base_keys | {"shard_index"}
    if require_shard_index and set(assessment) != allowed_keys:
        raise ValueError("self-run assessment_config keys are not exact")
    if not require_shard_index and set(assessment) not in (base_keys, allowed_keys):
        raise ValueError("generated assessment_config keys are not exact")

    num_shards = assessment.get("num_shards")
    if (
        isinstance(num_shards, bool)
        or not isinstance(num_shards, int)
        or num_shards != EXPECTED_SHARDS
    ):
        raise ValueError(f"num_shards must be exactly {EXPECTED_SHARDS}")
    shard_index = assessment.get("shard_index")
    if expected_shard_index is not None:
        if (
            isinstance(expected_shard_index, bool)
            or not isinstance(expected_shard_index, int)
            or not 0 <= expected_shard_index < EXPECTED_SHARDS
        ):
            raise ValueError("expected shard index is invalid")
        if (
            isinstance(shard_index, bool)
            or not isinstance(shard_index, int)
            or shard_index != expected_shard_index
        ):
            raise ValueError(
                f"scenario shard_index must be exactly {expected_shard_index}"
            )
    elif require_shard_index and (
        isinstance(shard_index, bool)
        or not isinstance(shard_index, int)
        or shard_index != 0
    ):
        raise ValueError("unpatched scenario shard_index must be exactly 0")
    elif (
        not require_shard_index
        and shard_index is not None
        and (
            isinstance(shard_index, bool)
            or not isinstance(shard_index, int)
            or shard_index != 0
        )
    ):
        raise ValueError("generated scenario shard_index must be absent or 0")
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
        expected_keys = (
            {"to", "from", "weak"} if item.get("weak") is True else {"to", "from"}
        )
        if set(item) != expected_keys:
            raise ValueError("scenario binding fields are not exact")
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


def _verify_green_id(value: Any, label: str) -> str:
    if not UUID_RE.fullmatch(GREEN_AGENT_ID):
        raise ValueError(
            "release gate green AgentBeats ID is not configured; registration placeholder remains"
        )
    registered = _verify_registered_id(value, label)
    if registered != GREEN_AGENT_ID:
        raise ValueError(f"{label} does not match the pinned green AgentBeats ID")
    return registered


def _verify_component_shape(component: dict[str, Any], label: str) -> None:
    if set(component) != {"manifest", "config"}:
        raise ValueError(f"{label} fields are not exact")


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
    scenario: dict[str, Any],
    components: dict[str, Any],
    *,
    expected_shard_index: int | None,
    compile_manifests: bool,
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
    _verify_component_shape(gateway, "components.gateway")
    expected_gateway_manifest = (
        COMPILE_MANIFESTS["gateway"] if compile_manifests else GATEWAY_MANIFEST
    )
    if gateway.get("manifest") != expected_gateway_manifest:
        raise ValueError("gateway manifest is not pinned to the approved commit")
    gateway_config = _mapping(gateway.get("config"), "gateway.config")
    if set(gateway_config) != {"assessment_config", "participant_roles"}:
        raise ValueError("self-run gateway config has unexpected fields")
    assessment = _mapping(
        gateway_config.get("assessment_config"),
        "gateway.config.assessment_config",
    )
    _verify_assessment(
        assessment,
        require_shard_index=True,
        expected_shard_index=expected_shard_index,
    )
    expected_roles = {"green": "officeqa_pro_v2_green", "purple1": "agent"}
    if gateway_config.get("participant_roles") != expected_roles:
        raise ValueError("gateway participant_roles do not match the self-run release")

    green = _mapping(
        components["officeqa_pro_v2_green"], "components.officeqa_pro_v2_green"
    )
    _verify_component_shape(green, "components.officeqa_pro_v2_green")
    expected_green_manifest = (
        COMPILE_MANIFESTS["green"] if compile_manifests else GREEN_MANIFEST
    )
    if green.get("manifest") != expected_green_manifest:
        raise ValueError("green manifest is not pinned to the approved commit")
    if green.get("config") != {"hf_token": "${config.green_hf_token}"}:
        raise ValueError("green dataset token binding is not exact")

    purple = _mapping(components["opencode_agent"], "components.opencode_agent")
    _verify_component_shape(purple, "components.opencode_agent")
    approved_purple_manifests = (
        {COMPILE_MANIFESTS["purple"]} if compile_manifests else PURPLE_MANIFESTS
    )
    if purple.get("manifest") not in approved_purple_manifests:
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
    if set(metadata) != {"agentbeats_ids"}:
        raise ValueError("self-run metadata fields are not exact")
    ids = _mapping(metadata.get("agentbeats_ids"), "metadata.agentbeats_ids")
    if set(ids) != {"officeqa_pro_v2_green", "agent", "opencode_agent"}:
        raise ValueError("self-run agentbeats_ids keys are not exact")
    if ids["agent"] != PURPLE_AGENT_ID or ids["opencode_agent"] != PURPLE_AGENT_ID:
        raise ValueError(
            "self-run metadata does not identify the approved purple agent"
        )
    green_id = _verify_green_id(
        ids["officeqa_pro_v2_green"], "the registered green AgentBeats ID"
    )
    if green_id == PURPLE_AGENT_ID:
        raise ValueError("green and purple AgentBeats IDs must differ")


def _verify_generated_scenario(
    scenario: dict[str, Any],
    components: dict[str, Any],
    *,
    expected_shard_index: int | None,
    compile_manifests: bool,
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
    _verify_component_shape(gateway, "components.gateway")
    approved_gateway_manifests = (
        {COMPILE_MANIFESTS["gateway"]}
        if compile_manifests
        else {GATEWAY_MANIFEST, GENERATED_GATEWAY_MANIFEST}
    )
    if gateway.get("manifest") not in approved_gateway_manifests:
        raise ValueError("generated gateway manifest is not the approved v0.3 manifest")
    gateway_config = _mapping(gateway.get("config"), "gateway.config")
    if set(gateway_config) != {
        "assessment_config",
        "participant_roles",
        "callback_urls",
    }:
        raise ValueError("generated gateway config fields are not exact")
    if gateway_config.get("callback_urls") != {}:
        raise ValueError("generated callback_urls must be empty")
    assessment = _mapping(
        gateway_config.get("assessment_config"),
        "gateway.config.assessment_config",
    )
    _verify_assessment(
        assessment,
        require_shard_index=False,
        expected_shard_index=expected_shard_index,
    )
    if gateway_config.get("participant_roles") != {
        "green": "green",
        "purple1": "agent",
    }:
        raise ValueError("generated gateway participant_roles are not exact")

    green = _mapping(components["green"], "components.green")
    _verify_component_shape(green, "components.green")
    expected_green_manifest = (
        COMPILE_MANIFESTS["green"] if compile_manifests else GREEN_MANIFEST
    )
    if green.get("manifest") != expected_green_manifest:
        raise ValueError("generated green manifest is not the approved pinned manifest")
    if green.get("config") != {"hf_token": "${config.green_hf_token}"}:
        raise ValueError("generated green dataset token binding is not exact")

    purple = _mapping(components["agent"], "components.agent")
    _verify_component_shape(purple, "components.agent")
    approved_purple_manifests = (
        {COMPILE_MANIFESTS["purple"]} if compile_manifests else PURPLE_MANIFESTS
    )
    if purple.get("manifest") not in approved_purple_manifests:
        raise ValueError("generated purple manifest is not approved")
    if purple.get("config") != {
        "officeqa_api_url": "${config.agent_officeqa_api_url}",
        "officeqa_api_token": "${config.agent_officeqa_api_token}",
    }:
        raise ValueError("generated purple endpoint secret bindings are not exact")

    expected_bindings = {
        ("#gateway.green", "#green.a2a", False),
        ("#gateway.purple1", "#agent.a2a", False),
        ("#green.proxy", "#gateway.proxy", True),
        ("#agent.proxy", "#gateway.proxy", True),
    }
    if _binding_set(scenario) != expected_bindings:
        raise ValueError("scenario bindings do not match generated release topology")
    if scenario.get("exports") != {"results": "#gateway.results"}:
        raise ValueError("generated scenario exports are not exact")

    metadata = _mapping(scenario.get("metadata"), "scenario.metadata")
    if set(metadata) != {"agentbeats_ids"}:
        raise ValueError("generated metadata fields are not exact")
    ids = _mapping(metadata.get("agentbeats_ids"), "metadata.agentbeats_ids")
    if set(ids) != {"green", "agent"}:
        raise ValueError("generated agentbeats_ids keys are not exact")
    if ids["agent"] != PURPLE_AGENT_ID:
        raise ValueError("generated scenario does not use the approved purple agent")
    green_id = _verify_green_id(ids["green"], "the generated green AgentBeats ID")
    if green_id == PURPLE_AGENT_ID:
        raise ValueError("green and purple AgentBeats IDs must differ")


def scenario_kind(scenario: dict[str, Any]) -> str:
    components = _mapping(scenario.get("components"), "scenario.components")
    component_names = set(components)
    if component_names == {"gateway", "officeqa_pro_v2_green", "opencode_agent"}:
        return "self-run"
    if component_names == {"gateway", "green", "agent"}:
        return "generated"
    raise ValueError(f"unexpected scenario components: {sorted(components)}")


def verify_scenario(
    scenario: dict[str, Any],
    *,
    expected_shard_index: int | None = None,
    compile_manifests: bool = False,
    require_kind: str | None = None,
) -> None:
    expected_top_level = {
        "manifest_version",
        "experimental_features",
        "config_schema",
        "components",
        "bindings",
        "exports",
        "metadata",
    }
    if set(scenario) != expected_top_level:
        raise ValueError("scenario top-level fields are not exact")
    components = _mapping(scenario.get("components"), "scenario.components")
    kind = scenario_kind(scenario)
    if require_kind is not None and kind != require_kind:
        raise ValueError(
            f"scenario kind is {kind!r}, required exact kind is {require_kind!r}"
        )
    if kind == "self-run":
        _verify_self_run_scenario(
            scenario,
            components,
            expected_shard_index=expected_shard_index,
            compile_manifests=compile_manifests,
        )
    elif kind == "generated":
        _verify_generated_scenario(
            scenario,
            components,
            expected_shard_index=expected_shard_index,
            compile_manifests=compile_manifests,
        )
    else:
        raise AssertionError(f"unhandled scenario kind: {kind}")


def verify_compiled_ir(
    ir: dict[str, Any],
    *,
    scenario_kind: str,
    shard_index: int,
    runtime_images: dict[str, Any] | None = None,
) -> None:
    """Verify compiler output and, when supplied, resolved runtime images."""
    if isinstance(shard_index, bool) or not 0 <= shard_index < EXPECTED_SHARDS:
        raise ValueError("compiled IR shard index is invalid")
    components = ir.get("components")
    if not isinstance(components, list):
        raise TypeError("compiled IR components must be an array")

    manifest_digests: dict[str, str] = {}
    compiled_images: dict[str, str] = {}
    for raw_component in components:
        component = _mapping(raw_component, "compiled IR component")
        moniker = component.get("moniker")
        digest = component.get("digest")
        if not isinstance(moniker, str) or not moniker:
            raise ValueError("compiled IR component moniker is missing")
        if moniker in manifest_digests:
            raise ValueError(f"compiled IR contains duplicate component {moniker!r}")
        if not isinstance(digest, str):
            raise TypeError(f"compiled IR digest is missing for {moniker!r}")
        manifest_digests[moniker] = digest

        program = component.get("program")
        if program is not None:
            program_mapping = _mapping(program, f"compiled IR program {moniker}")
            image = program_mapping.get("image")
            if not isinstance(image, str) or not image:
                raise ValueError(f"compiled IR image is missing for {moniker!r}")
            compiled_images[moniker] = image

    expected_manifests = _expected_manifest_digests(scenario_kind)[str(shard_index)]
    if manifest_digests != expected_manifests:
        raise ValueError(
            "compiled IR manifest digests differ from the exact release shard: "
            f"got={json.dumps(manifest_digests, sort_keys=True, separators=(',', ':'))} "
            f"expected={json.dumps(expected_manifests, sort_keys=True, separators=(',', ':'))}"
        )
    if compiled_images != _expected_compiled_images(scenario_kind):
        raise ValueError("compiled IR program images differ from the exact release set")

    if runtime_images is not None and runtime_images != _expected_runtime_images(
        scenario_kind
    ):
        raise ValueError("resolved runtime images differ from the exact release set")


def verify_artifact(
    artifact: dict[str, Any],
    rows: list[dict[str, str]],
    expected_participants: dict[str, Any] | None = None,
) -> None:
    if set(artifact) != {"status", "participants", "results"}:
        raise ValueError("result artifact top-level fields are not exact")
    if artifact.get("status") != "completed":
        raise ValueError(f"result status is {artifact.get('status')!r}, not completed")
    participants = _mapping(artifact.get("participants"), "result participants")
    if expected_participants is not None and participants != expected_participants:
        raise ValueError(
            "result participants do not exactly match the release scenario"
        )
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
    shards = artifact.get("results")
    if not isinstance(shards, list) or len(shards) != EXPECTED_SHARDS:
        raise ValueError(
            f"result must contain exactly {EXPECTED_SHARDS} direct shard objects"
        )

    seen_indices: set[int] = set()
    seen_uids: set[str] = set()
    total_score = 0.0
    total_max = 0.0
    for shard in shards:
        if not isinstance(shard, dict):
            raise TypeError("each shard result must be an object")
        expected_shard_keys = {
            "benchmark",
            "dataset_revision",
            "shard_index",
            "num_shards",
            "score",
            "max_score",
            "pass_rate",
            "time_used",
            "task_rewards",
            "error_count",
            "error_types",
        }
        if set(shard) != expected_shard_keys:
            raise ValueError("shard result fields are not exact")
        if shard.get("benchmark") != BENCHMARK:
            raise ValueError(f"unexpected benchmark {shard.get('benchmark')!r}")
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
    scenario_kind: str,
    expected_run_url: str | None = None,
    expected_repository_url: str | None = None,
    expected_github_sha: str | None = None,
    expected_github_ref: str | None = None,
    expected_workflow_ref: str | None = None,
    expected_workflow_sha: str | None = None,
    expected_job_workflow_ref: str | None = None,
    expected_job_workflow_sha: str | None = None,
    expected_submission_id: str | None = None,
    expected_pr_number: int | None = None,
    expected_actor: str | None = None,
    expected_head_repository: str | None = None,
    expected_base_sha: str | None = None,
    expected_head_sha: str | None = None,
    expected_results_sha256: str | None = None,
) -> None:
    quick_submit = expected_submission_id is not None
    expected_top_level = {
        "image_digests",
        "framework_image_digests",
        "manifest_digests",
        "manifest_digests_by_shard",
        "release_manifests",
        "tool_images",
        "results_sha256",
        "timestamp",
        "github_actions",
    }
    if quick_submit:
        expected_top_level.add("pull_request")
    if set(provenance) != expected_top_level:
        raise ValueError("provenance top-level fields are not exact")

    images = _mapping(provenance.get("image_digests"), "provenance.image_digests")
    expected_images = _expected_runtime_images(scenario_kind)
    if images != expected_images:
        raise ValueError(
            "runtime image digests differ from the exact release set: "
            f"got={sorted(images.values())}"
        )

    framework_images = _mapping(
        provenance.get("framework_image_digests"),
        "provenance.framework_image_digests",
    )
    if framework_images != EXPECTED_FRAMEWORK_IMAGES:
        raise ValueError("framework runtime images differ from the exact release set")

    tool_images = _mapping(provenance.get("tool_images"), "provenance.tool_images")
    if tool_images != EXPECTED_TOOL_IMAGES:
        raise ValueError("release tool images differ from the exact pinned set")

    results_sha256 = provenance.get("results_sha256")
    if not isinstance(results_sha256, str) or not SHA256_RE.fullmatch(results_sha256):
        raise ValueError("provenance results_sha256 is not a lowercase SHA-256")
    if expected_results_sha256 and results_sha256 != expected_results_sha256:
        raise ValueError("provenance results_sha256 does not match the result artifact")

    release_manifests = _mapping(
        provenance.get("release_manifests"), "provenance.release_manifests"
    )
    if release_manifests != EXPECTED_MANIFEST_SOURCES:
        raise ValueError(
            "release manifest sources do not match the immutable release set"
        )

    expected_manifests = _expected_manifest_digests(scenario_kind)
    manifests_by_shard = _mapping(
        provenance.get("manifest_digests_by_shard"),
        "provenance.manifest_digests_by_shard",
    )
    if manifests_by_shard != expected_manifests:
        raise ValueError("compiled manifest digests differ from the exact release set")
    manifests = _mapping(provenance.get("manifest_digests"), "manifest_digests")
    if manifests != expected_manifests["0"]:
        raise ValueError("flat manifest digests do not match release shard 0")
    if any(
        not MANIFEST_DIGEST_RE.fullmatch(value)
        for shard in manifests_by_shard.values()
        for value in _mapping(shard, "manifest digest shard").values()
        if isinstance(value, str)
    ):
        raise ValueError("provenance contains an invalid manifest digest")

    timestamp = provenance.get("timestamp")
    if not isinstance(timestamp, str) or not TIMESTAMP_RE.fullmatch(timestamp):
        raise ValueError("provenance timestamp is not an exact UTC timestamp")
    datetime.fromisoformat(timestamp)

    actions = _mapping(provenance.get("github_actions"), "provenance.github_actions")
    action_keys = {
        "run_url",
        "ref",
        "sha",
        "repository_url",
        "workflow_ref",
        "workflow_sha",
        "job_workflow_ref",
        "job_workflow_sha",
        "run_attempt",
    }
    if set(actions) != action_keys:
        raise ValueError("provenance.github_actions fields are not exact")
    for key in action_keys - {"run_attempt"}:
        if not isinstance(actions.get(key), str) or not actions[key]:
            raise ValueError(f"provenance.github_actions.{key} is missing")
    if isinstance(actions.get("run_attempt"), bool) or actions.get("run_attempt") != 1:
        raise ValueError("provenance run_attempt must be exactly 1")
    if expected_run_url and actions["run_url"] != expected_run_url:
        raise ValueError("provenance run_url does not identify this workflow run")
    if expected_repository_url and actions["repository_url"] != expected_repository_url:
        raise ValueError("provenance repository_url does not identify this repository")
    if expected_github_sha and actions["sha"] != expected_github_sha:
        raise ValueError("provenance SHA does not identify this workflow revision")
    if expected_github_ref and actions["ref"] != expected_github_ref:
        raise ValueError("provenance ref does not identify the expected workflow ref")
    if expected_workflow_ref and actions["workflow_ref"] != expected_workflow_ref:
        raise ValueError("provenance workflow_ref is not the trusted caller")
    if expected_workflow_sha and actions["workflow_sha"] != expected_workflow_sha:
        raise ValueError("provenance workflow_sha is not the trusted caller revision")
    if (
        expected_job_workflow_ref
        and actions["job_workflow_ref"] != expected_job_workflow_ref
    ):
        raise ValueError("provenance job_workflow_ref is not the pinned runner")
    if (
        expected_job_workflow_sha
        and actions["job_workflow_sha"] != expected_job_workflow_sha
    ):
        raise ValueError(
            "provenance job_workflow_sha is not the pinned runner revision"
        )

    if quick_submit:
        if not all(
            value is not None
            for value in (
                expected_pr_number,
                expected_actor,
                expected_head_repository,
                expected_github_sha,
                expected_base_sha,
                expected_head_sha,
            )
        ):
            raise ValueError("quick-submit provenance expectations are incomplete")
        if not UUID_RE.fullmatch(expected_submission_id):
            raise ValueError("expected submission ID is not a canonical UUID")
        pull_request = _mapping(
            provenance.get("pull_request"), "provenance.pull_request"
        )
        expected_pull_request = {
            "number": expected_pr_number,
            "event_name": "pull_request_target",
            "actor": expected_actor,
            "author": expected_actor,
            "head_ref": f"quick-submit-{expected_submission_id}",
            "head_sha": expected_head_sha,
            "head_repository": expected_head_repository,
            "base_ref": "main",
            "base_sha": expected_base_sha,
        }
        if pull_request != expected_pull_request:
            raise ValueError("pull-request provenance does not match the trusted event")
        for label, value in (
            ("head SHA", expected_head_sha),
            ("GitHub SHA", expected_github_sha),
            ("base SHA", expected_base_sha),
            ("workflow SHA", actions["workflow_sha"]),
            ("job workflow SHA", actions["job_workflow_sha"]),
        ):
            if not GIT_SHA_RE.fullmatch(value):
                raise ValueError(f"provenance {label} is not a full Git SHA")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    scenario_parser = subparsers.add_parser("scenario", help="verify release scenario")
    scenario_parser.add_argument("--scenario", type=Path, required=True)
    scenario_parser.add_argument("--expected-shard-index", type=int)
    scenario_parser.add_argument("--compile-manifests", action="store_true")
    scenario_parser.add_argument("--require-kind", choices=("generated", "self-run"))

    ir_parser = subparsers.add_parser("ir", help="verify compiled release IR")
    ir_parser.add_argument("--ir", type=Path, required=True)
    ir_parser.add_argument(
        "--scenario-kind", choices=("generated", "self-run"), required=True
    )
    ir_parser.add_argument("--shard-index", type=int, required=True)
    ir_parser.add_argument("--runtime-images", type=Path)
    ir_parser.add_argument("--write-runtime-images", type=Path)

    compose_parser = subparsers.add_parser(
        "compose", help="pin compiler-emitted Compose images"
    )
    compose_parser.add_argument("--compose", type=Path, required=True)
    compose_parser.add_argument("--framework-images", type=Path, required=True)

    compose_config_parser = subparsers.add_parser(
        "compose-config", help="verify rendered digest-pinned Compose services"
    )
    compose_config_parser.add_argument("--rendered-compose", type=Path, required=True)

    result_parser = subparsers.add_parser("result", help="verify exact public result")
    result_parser.add_argument("--artifact", type=Path, required=True)
    result_parser.add_argument("--dataset", type=Path, required=True)
    result_parser.add_argument("--provenance", type=Path, required=True)
    result_parser.add_argument("--scenario", type=Path, required=True)
    result_parser.add_argument("--require-kind", choices=("generated", "self-run"))
    result_parser.add_argument("--expected-run-url")
    result_parser.add_argument("--expected-repository-url")
    result_parser.add_argument("--expected-github-sha")
    result_parser.add_argument("--expected-github-ref")
    result_parser.add_argument("--expected-workflow-ref")
    result_parser.add_argument("--expected-workflow-sha")
    result_parser.add_argument("--expected-job-workflow-ref")
    result_parser.add_argument("--expected-job-workflow-sha")
    result_parser.add_argument("--expected-submission-id")
    result_parser.add_argument("--expected-pr-number", type=int)
    result_parser.add_argument("--expected-actor")
    result_parser.add_argument("--expected-head-repository")
    result_parser.add_argument("--expected-base-sha")
    result_parser.add_argument("--expected-head-sha")
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.command == "compose":
            pin_compose_images(args.compose, args.framework_images)
            print("PASS: every Compose image is pinned to the exact release digest")
            return 0
        if args.command == "compose-config":
            verify_rendered_compose(args.rendered_compose)
            print("PASS: rendered Compose services use the exact release images")
            return 0
        if args.command == "ir":
            runtime_images = (
                _load_json(args.runtime_images) if args.runtime_images else None
            )
            verify_compiled_ir(
                _load_json(args.ir),
                scenario_kind=args.scenario_kind,
                shard_index=args.shard_index,
                runtime_images=runtime_images,
            )
            if args.write_runtime_images:
                with args.write_runtime_images.open("x", encoding="utf-8") as handle:
                    json.dump(
                        _expected_runtime_images(args.scenario_kind),
                        handle,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    handle.write("\n")
            detail = " and runtime images" if runtime_images is not None else ""
            print(f"PASS: compiled IR{detail} match the exact release")
            return 0

        scenario = _load_json(args.scenario)
        verify_scenario(
            scenario,
            expected_shard_index=getattr(args, "expected_shard_index", None),
            compile_manifests=getattr(args, "compile_manifests", False),
            require_kind=getattr(args, "require_kind", None),
        )
        if args.command == "result":
            kind = scenario_kind(scenario)
            rows = load_dataset(args.dataset)
            metadata = _mapping(scenario.get("metadata"), "scenario.metadata")
            expected_participants = _mapping(
                metadata.get("agentbeats_ids"), "metadata.agentbeats_ids"
            )
            verify_artifact(_load_json(args.artifact), rows, expected_participants)
            verify_provenance(
                _load_json(args.provenance),
                scenario_kind=kind,
                expected_run_url=args.expected_run_url,
                expected_repository_url=args.expected_repository_url,
                expected_github_sha=args.expected_github_sha,
                expected_github_ref=args.expected_github_ref,
                expected_workflow_ref=args.expected_workflow_ref,
                expected_workflow_sha=args.expected_workflow_sha,
                expected_job_workflow_ref=args.expected_job_workflow_ref,
                expected_job_workflow_sha=args.expected_job_workflow_sha,
                expected_submission_id=args.expected_submission_id,
                expected_pr_number=args.expected_pr_number,
                expected_actor=args.expected_actor,
                expected_head_repository=args.expected_head_repository,
                expected_base_sha=args.expected_base_sha,
                expected_head_sha=args.expected_head_sha,
                expected_results_sha256=_sha256(args.artifact),
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
