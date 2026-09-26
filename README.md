# OfficeQA Pro v2 AgentBeats Leaderboard

This repository is the exact-release leaderboard for OfficeQA Pro v2. A scored
release must answer all 90 pinned questions correctly across 10 deterministic
shards, with no evaluation errors. Smoke runs and partial results cannot pass
the release verifier.

Two official public execution paths are enabled. Quick Submit uses AgentBeats'
required official v2 reusable runner and receives participant secrets from the
encrypted AgentBeats submission bundle. The hardened fork/self-run path uses
only secrets owned by the submitter's public fork, runs the same exact 10-shard
release, and opens an upstream result pull request after the 90/90 verifier
passes.

## Current release state

The green benchmark is registered on AgentBeats as
`01a0db6d-5b2b-7551-9ab3-45b9ae72080c`, and that UUID is pinned in both
`scenario.json5` and `tools/verify_exact_result.py`.

The registered scenario and exact verifier are frozen at
`94a8460f564887bbdcb8819e1b0368da6e89c46a`. Quick Submit delegates to
`RDI-Foundation/agentbeats-leaderboard-template/.github/workflows/quick-submit-runner.yml@v2`,
as required by the AgentBeats submission service.

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
   branch. A fork/self-run pushes its generated `submission-*` branch only to
   the submitter's fork. Compare-and-swap leases prevent overwriting an
   unexpected branch state.
4. Install the AgentBeats GitHub App with minimum repository permissions. It
   must not have Actions/workflow-dispatch permission beyond what the service
   explicitly requires.
5. Keep CodeQL's GitHub Actions analysis enabled and review Actions policy
   insights before enforcement.

Quick Submit accepts only a first-attempt, `opened`, same-repository pull
request authored and triggered by `agentbeats-dev[bot]`, targeting `main`, with
a canonical `quick-submit-<uuid>` branch. AgentBeats' official reusable runner
derives the submission ID from that branch and authenticates its secret-bundle
request with GitHub OIDC.

## Secret boundary

Quick Submit obtains participant secrets from AgentBeats' encrypted,
submission-scoped bundle. The fork/self-run route does not call AgentBeats'
Quick Submit secrets endpoint and cannot read secrets from this upstream
repository. Each submitter stores these three Actions secrets in their own
fork:

- `GREEN_HF_TOKEN`
- `PARTICIPANT_API_URL`
- `PARTICIPANT_API_TOKEN`

The workflow validates and masks the values, writes them to a mode-0600
temporary env file, deletes that file immediately after container startup, and
never commits them. The result PR contains only the result JSON, the exact
scenario, and provenance JSON. Keep the fork public so the upstream gate can
verify the source workflow run; never put a token directly in `scenario.json5`.

## External identity checks

The production AgentBeats backend and GCP Workload Identity provider must
validate, at minimum:

- audience `agentbeats-quick-submit-production`
- repository name and immutable repository ID
- `event_name == pull_request`
- actor, triggering actor, and pull-request author `agentbeats-dev[bot]`
- head repository, canonical head branch, base branch, event ref, and event SHA
- caller `workflow_ref` and `workflow_sha`
- reusable `job_workflow_ref` and `job_workflow_sha`
- `run_attempt == 1` and the expected runner environment
- GitHub's immutable repository subject format for repositories created after
  July 15, 2026

The workflow's own claim checks are defense in depth; the backend and WIF
attribute conditions are the actual authorization boundary.

## Hardened fork/self-run submission

The manual route follows AgentBeats' official fork workflow while retaining the
OfficeQA exact-release controls:

1. Create a **public fork** of this repository and enable read/write Workflow
   permissions in the fork's Actions settings.
2. Sync the fork with current upstream `main`, create a non-`main` branch, and
   add the three fork-owned secrets listed above.
3. Keep `scenario.json5` on the approved OfficeQA Pro v2 topology and registered
   participant. The verifier rejects partial runs, alternate images, changed
   release controls, and unapproved participant identities.
4. Run **Run Scenario** with `workflow_dispatch` while the non-`main` branch is
   selected. A push changing `scenario.json5` on a non-`main` branch also
   triggers it.
5. Ten shards start concurrently. The workflow aggregates only ten completed
   shards, checks all 90 pinned tasks, requires 90/90 with zero errors, and
   records immutable image, manifest, tool, workflow, and result hashes.
6. After verification, use the Actions summary link to open the generated
   `submission-<owner>-<run-id>` branch as a pull request to upstream `main`.
   Leave **Allow edits and access to secrets by maintainers** unchecked.

The upstream `Verify Release Gate` checks that the PR adds exactly
`results/<submission>.json`, `submissions/<submission>.json5`, and
`submissions/<submission>-provenance.json`. It retrieves the referenced public
Actions run, requires a successful first attempt, compares the run's workflow
and release tools byte-for-byte with trusted upstream files, and re-validates
the exact result and provenance without executing code from the fork.

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
leaderboard configuration. Before accepting a result, verify the green ID,
branch rules, Quick Submit OIDC/WIF conditions, and fork-run provenance.
