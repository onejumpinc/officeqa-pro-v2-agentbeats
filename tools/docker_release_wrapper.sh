#!/usr/bin/env bash
# Force Amber's internal mutable control-helper tag to the audited image digest.

set -euo pipefail

if [[ "${0##*/}" == "podman" ]]; then
  echo "Podman fallback is disabled by the exact release gate" >&2
  exit 1
fi

real_docker="${AGENTBEATS_REAL_DOCKER_BIN:?missing exact real Docker path}"
if [[ ! -x "${real_docker}" || "${real_docker}" -ef "${BASH_SOURCE[0]}" ]]; then
  echo "Invalid real Docker binary for the release wrapper" >&2
  exit 1
fi

mutable_control_image='curlimages/curl:8.12.1'
exact_control_image='curlimages/curl@sha256:94e9e444bcba979c2ea12e27ae39bee4cd10bc7041a472c4727a558e213744e6'
args=("$@")
rewritten=0
run_command=false

if [[ "${args[0]:-}" == "run" ||
      ("${args[0]:-}" == "container" && "${args[1]:-}" == "run") ]]; then
  run_command=true
fi

for index in "${!args[@]}"; do
  case "${args[index]}" in
    "${mutable_control_image}")
      if [[ "${run_command}" != true ]]; then
        echo "Mutable Amber control helper image used outside docker run" >&2
        exit 1
      fi
      args[index]="${exact_control_image}"
      rewritten=$((rewritten + 1))
      ;;
    "${exact_control_image}")
      ;;
    curlimages/curl:* | curlimages/curl@* | docker.io/curlimages/curl:* | docker.io/curlimages/curl@*)
      echo "Amber attempted to run an unapproved curl helper image" >&2
      exit 1
      ;;
  esac
done
if [[ "${rewritten}" -gt 1 ]]; then
  echo "Amber supplied the control helper image more than once" >&2
  exit 1
fi

exec "${real_docker}" "${args[@]}"
