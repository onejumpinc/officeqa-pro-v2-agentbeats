# OfficeQA Pro v2 AgentBeats Leaderboard

This repository is the exact-release leaderboard for OfficeQA Pro v2. A scored
release must answer all 90 pinned questions correctly across 10 deterministic
shards, with no evaluation errors. Smoke runs and partial results cannot pass
the release verifier.

Both workflows fail closed before writing a result branch unless the scenario,
Git tree, manifests, containers, provenance, dataset, and final score all match
the pinned release. Quick Submit never checks out or executes the submitted pull
request. It treats the one allowed scenario file as data and materializes it by
Git object ID.

## Current release state

The green benchmark is registered on AgentBeats as
`01a0db6d-5b2b-7551-9ab3-45b9ae72080c`, and that UUID is pinned in both
`scenario.json5` and `tools/verify_exact_result.py`.

Public execution remains blocked until the registered scenario, verifier,
tools, tests, and reusable runner are committed together, all 10 shards are
recompiled and validated, and a separate caller-pin commit points
`.github/workflows/quick-submit.yml` at that new frozen runner SHA. The
currently frozen reusable runner is
`88431878691255f904990142f754f45041161e06`; it predates registration and must
not be used for a release.

## Immutable release inputs

- Dataset: `databricks/officeqa-pro-v2/officeqa_pro_v2.csv` at revision
  `65a2b315780417bc50d7bfe6e5bdb904e63fda65`
- Dataset raw SHA-256:
  `7e253ed35c2ad80f365140beacb4549f21733c9072938bf35cea41879b76182b`
- Dataset semantic SHA-256:
  `e8dbf350a9e0dd1be8464744a012f17dba6605cd2a7f1e850c06dcc3562cab54`
- Approved purple AgentBeats ID: `01a05b80-58e6-7e71-95e9-656bde816e85`
- Registered green AgentBeats ID: `01a0db6d-5b2b-7551-9ab3-45b9ae72080c`
- Green image:
  `ghcr.io/onejumpinc/officeqa-pro-v2-benchmark@sha256:79db435c4a563090391fcbc3b9b656850efc3a04746de6e20982c39702740ff7`
- Purple proxy image:
  `ghcr.io/onejumpinc/officeqa-proxy-agent@sha256:7a6d2d64b9a582b0a57460d13ecb5ef4641afdac8d71d864007c2ce7380ce8fa`
- Gateway image:
  `ghcr.io/rdi-foundation/agentbeats-gateway@sha256:3f9976889c598092dc4273312ec431cbc48bbe064ff65b5613425f4990bc1d4c`
- Amber CLI image:
  `ghcr.io/rdi-foundation/amber-cli@sha256:3514b6cf27896e8cc9a148e8ebdc96ae5a15fe36deec69b7250ab25e126511ca`
- Quick Submit KMS key version:
  `projects/komyo-agentbeats/locations/us-central1/keyRings/agentbeats-prod-kms/cryptoKeys/quick-submit/cryptoKeyVersions/1`

`tools/verify_exact_result.py` also pins the complete compiler-produced
framework image multiset:

- `curlimages/curl@sha256:94e9e444bcba979c2ea12e27ae39bee4cd10bc7041a472c4727a558e213744e6`
- `ghcr.io/rdi-foundation/amber-helper@sha256:135c9ec8b7ff5670d28a1b7b081571843e46605051ffea7adb36f5694265d905`
- `ghcr.io/rdi-foundation/amber-provisioner@sha256:c17f4496f5cd9750155224d79bfc35ff48ec215dd83e8031a8c75694c76cb113`
- `ghcr.io/rdi-foundation/amber-router@sha256:5406fcb7c5d944f46c31b0131b37e14951fd7336fe71d24ee1a18b62f91e1482`
- `otel/opentelemetry-collector-contrib@sha256:3bc07732530c87c53f9103b01a3afed972fdeba26087a590c1098781736e58c2`
- `busybox@sha256:73aaf090f3d85aa34ee199857f03fa3a95c8ede2ffd4cc2cdb5b94e566b11662`

## Registration and two-commit freeze

1. Keep the repository public and register the green agent from the immutable
   `green-agent.json5` URL at commit
   `9ac7f2c39d16e13b2e10ddb3f73c63cdc9d278ad`.
2. Replace `REPLACE_WITH_GREEN_AGENT_ID` in both `scenario.json5` and
   `tools/verify_exact_result.py`. The two values must be the same lowercase
   UUID.
3. Recompile and inspect all 10 shards. Re-run the complete local validation
   suite and the exact 90/90 verifier.
4. Commit the registered scenario, verifier, tools, tests, and reusable runner.
   Record that commit's full SHA as the new frozen runner SHA.
5. In a separate commit, update both the `uses: ...@<SHA>` reference and
   `trusted_runner_sha` in `.github/workflows/quick-submit.yml`. Update the test
   constant at the same time. Never point the caller at a branch or tag.
6. Register or publish only after both commits are on protected `main` and all
   external identity conditions below have been verified.

## GitHub repository controls

Configure these controls outside the workflow:

1. Set the default `GITHUB_TOKEN` permission to read-only. The release workflows
   request their narrowly scoped write permissions explicitly.
2. Protect `main` with required pull requests and `@onejumpinc` CODEOWNERS
   review for `.github/workflows/**`, `tools/**`, `scenario.json5`, `results/**`,
   and `submissions/**`. Disable force-push, deletion, and admin bypass.
3. Permit the GitHub Actions bot to update only the expected `quick-submit-*`
   branch and to create the generated `submission-*` branch. Compare-and-swap
   leases prevent overwriting an unexpected branch state.
4. Install the AgentBeats GitHub App with minimum repository permissions. It
   must not have Actions/workflow-dispatch permission beyond what the service
   explicitly requires.
5. Add an Actions event policy that explicitly allows `pull_request_target`
   only for `.github/workflows/quick-submit.yml` and the expected AgentBeats bot.
   GitHub's public-repository default is currently in evaluation mode and will
   block `pull_request_target` on November 2, 2026 unless an applicable policy
   allows it. See [Securely using `pull_request_target`](https://docs.github.com/en/actions/reference/security/securely-using-pull_request_target)
   and [About Actions policies](https://docs.github.com/en/actions/concepts/about-actions-policies).
6. Keep CodeQL's GitHub Actions analysis enabled and review Actions policy
   insights before enforcement.

Quick Submit accepts only a first-attempt, `opened`, same-repository pull
request authored and triggered by `agentbeats-dev[bot]`, targeting `main`, with
a canonical `quick-submit-<uuid>` branch. The reusable runner additionally
requires the exact caller and runner SHAs, an exact one-file Git tree, and the
expected OIDC claims.

## Secret boundary

Create a GitHub Environment named `officeqa-production`. Its deployment branch
policy must use **Selected branches** with the one exact branch `main`; do not
use a wildcard or “protected branches only.” Do not allow environment bypass.
The manual workflow's `eval` and `summary` jobs reference this environment.
Require a reviewer for manual releases while Quick Submit remains disabled. If
an automatic Quick Submit flow later shares this environment, either retain a
per-release approval or use a separate exact-main environment governed by the
same actor and event policy; do not silently remove the approval boundary.

Store these three values only as environment secrets:

- `GREEN_HF_TOKEN`
- `PARTICIPANT_API_URL`
- `PARTICIPANT_API_TOKEN`

Delete any repository- or organization-level copies and rotate the values after
the move. Explicitly delete, or do not create,
`OFFICEQA_PRO_V2_HF_TOKEN` at repository or organization scope; rotate the
underlying Hugging Face token if that legacy secret ever existed. A
branch-modified manual workflow must receive no usable benchmark secret when the
environment's exact-main rule rejects it.

The current frozen Quick Submit runner still references
`OFFICEQA_PRO_V2_HF_TOKEN` from the caller. Leave it unset: the runner rejects an
empty value safely, and this public path is intentionally disabled. The
preferred final runner stores the raw token as the
environment secret `GREEN_HF_TOKEN`, places only its `eval` and `summary` jobs
in `officeqa-production`, and removes the caller secret mapping. That change
alters the default GitHub OIDC `sub` to
`repo:onejumpinc/officeqa-pro-v2-agentbeats:environment:officeqa-production`.
AgentBeats and the GCP Workload Identity provider must confirm or update their
conditions before that runner is frozen and repinned. The environment-scoped
`eval` token and non-environment `cleanup` token have different `sub` claims;
the backend must authorize each endpoint with the appropriate exact form or the
cleanup call will fail. Never store a JSON-wrapped token as the environment
secret.

## External identity checks

The production AgentBeats backend and GCP Workload Identity provider must
validate, at minimum:

- audience `agentbeats-quick-submit-production`
- repository name and immutable repository ID
- `event_name == pull_request_target`
- actor, triggering actor, and pull-request author `agentbeats-dev[bot]`
- head repository, canonical head branch, base branch, event ref, and event SHA
- caller `workflow_ref` and `workflow_sha`
- reusable `job_workflow_ref` and `job_workflow_sha`
- `run_attempt == 1` and the expected runner environment
- the `officeqa-production` environment claim and revised `sub`, if the final
  environment-secret design is adopted
- the distinct non-environment `sub` for the cleanup-only completion endpoint

The workflow's own claim checks are defense in depth; the backend and WIF
attribute conditions are the actual authorization boundary.

## Manual exact run

`run-scenario.yml` is `workflow_dispatch`-only and accepts no shard or instance
inputs. Dispatch it from protected `main`. It verifies the workflow identity,
pins every action and image, runs exactly 10 shards, validates the final 90/90
artifact against the pinned dataset, and only then creates a new
`submission-<owner>-<run-id>` branch. It never overwrites an existing branch.

## Local validation

Run these checks before freezing either commit:

```sh
actionlint -ignore 'SC2129|SC2004' .github/workflows/*.yml
ruby -e 'require "yaml"; Dir[".github/workflows/*.yml"].each { |f| YAML.safe_load(File.read(f), aliases: true) }'
PYTHONPATH=. uvx --from pytest pytest -q
uvx ruff check tools tests
uvx ruff format --check tools tests
bash -n tools/docker_release_wrapper.sh
python3 -c 'import json; json.load(open("scenario.json5"))'
git diff --check
```

The two ignored ShellCheck codes are style-only findings in the already frozen
runner (`SC2129` and `SC2004`); no security or syntax diagnostic is ignored.

Finally, paste `leaderboard-query.json` into the registered green agent's
leaderboard configuration. Do not start a public Action or submit a leaderboard
run until the green ID, environment policy, OIDC/WIF conditions, branch rules,
and new immutable runner pin have all been independently verified.
