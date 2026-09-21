from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "tools/docker_release_wrapper.sh"
EXACT_CONTROL_IMAGE = (
    "curlimages/curl@"
    "sha256:94e9e444bcba979c2ea12e27ae39bee4cd10bc7041a472c4727a558e213744e6"
)


def _fake_docker(tmp_path: Path) -> tuple[Path, Path]:
    arguments = tmp_path / "arguments"
    executable = tmp_path / "docker-real"
    executable.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'printf \'%s\\n\' "$@" > "${CAPTURE_PATH}"\n'
    )
    executable.chmod(0o755)
    return executable, arguments


def _run_wrapper(tmp_path: Path, *args: str) -> list[str]:
    executable, arguments = _fake_docker(tmp_path)
    subprocess.run(
        ["bash", str(WRAPPER), *args],
        check=True,
        env={
            **os.environ,
            "AGENTBEATS_REAL_DOCKER_BIN": str(executable),
            "CAPTURE_PATH": str(arguments),
        },
    )
    return arguments.read_text().splitlines()


def test_rewrites_amber_control_helper_to_exact_digest(tmp_path: Path) -> None:
    assert _run_wrapper(
        tmp_path,
        "run",
        "--rm",
        "curlimages/curl:8.12.1",
        "--version",
    ) == ["run", "--rm", EXACT_CONTROL_IMAGE, "--version"]


def test_leaves_non_run_docker_commands_unchanged(tmp_path: Path) -> None:
    assert _run_wrapper(tmp_path, "compose", "version") == [
        "compose",
        "version",
    ]


def test_rejects_unapproved_or_duplicate_control_helper(tmp_path: Path) -> None:
    executable, arguments = _fake_docker(tmp_path)
    environment = {
        **os.environ,
        "AGENTBEATS_REAL_DOCKER_BIN": str(executable),
        "CAPTURE_PATH": str(arguments),
    }
    for args in (
        ("run", "curlimages/curl:latest"),
        ("run", "curlimages/curl:8.12.1", "curlimages/curl:8.12.1"),
    ):
        result = subprocess.run(
            ["bash", str(WRAPPER), *args],
            check=False,
            capture_output=True,
            text=True,
            env=environment,
        )
        assert result.returncode != 0
    assert not arguments.exists()


def test_blocks_podman_fallback(tmp_path: Path) -> None:
    executable, arguments = _fake_docker(tmp_path)
    podman_wrapper = tmp_path / "podman"
    podman_wrapper.write_bytes(WRAPPER.read_bytes())
    podman_wrapper.chmod(0o755)
    result = subprocess.run(
        [str(podman_wrapper), "run", "curlimages/curl:8.12.1"],
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "AGENTBEATS_REAL_DOCKER_BIN": str(executable),
            "CAPTURE_PATH": str(arguments),
        },
    )
    assert result.returncode != 0
    assert not arguments.exists()
