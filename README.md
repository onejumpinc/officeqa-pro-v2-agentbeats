# OfficeQA Pro v2 AgentBeats Leaderboard

This directory contains the OfficeQA Pro v2 files that replace the defaults in a
standalone repository created from
`RDI-Foundation/agentbeats-leaderboard-template`.

The assessment runs all 90 questions in 10 deterministic shards. The green
agent downloads the gated answer CSV at its pinned Hugging Face revision during
the run. The answer key is not included in either public container image.

Both public workflows are full-release-only. Before any result commit, branch,
or pull-request link can be created, they require an exact 90/90 result over the
pinned 90-row dataset, all 10 deterministic shards, zero evaluation errors, the
approved purple AgentBeats ID, and the pinned gateway, green, and proxy image
digests. A smoke or partial run cannot pass this gate.

## Required setup

1. Create a public repository from the official AgentBeats leaderboard template.
2. Keep the repository-owned workflows and `tools/` verifier files together;
   `quick-submit.yml` intentionally calls the local reusable runner rather than
   the mutable template runner.
3. Register the green agent using the immutable `green-agent.json5` URL, then
   replace `REPLACE_WITH_GREEN_AGENT_ID` in `scenario.json5`. The approved
   purple agent ID is already fixed in the scenario and verifier.
4. Add `OFFICEQA_PRO_V2_HF_TOKEN` as a leaderboard repository secret. The token must have accepted access to `databricks/officeqa-pro-v2`.
5. Install the AgentBeats GitHub App on the leaderboard repository.
6. Paste `leaderboard-query.json` into the green agent's leaderboard configuration on AgentBeats.
7. Protect `main`: require pull requests and the `@onejumpinc` CODEOWNERS
   review for changes under `results/`, `submissions/`, `.github/workflows/`,
   and `tools/`. This prevents a hand-written result PR from bypassing the run
   gate. Repository settings are part of the release control and are not
   established by the workflow itself.

For a local or manual scenario run, also add these repository secrets:

- `GREEN_HF_TOKEN`
- `PARTICIPANT_API_URL`
- `PARTICIPANT_API_TOKEN`

The checked-in public workflows reject `num_instances` and any shard count other
than 10. If a private smoke test is needed, run it outside these submission
workflows; smoke output must not be committed or proposed for leaderboard merge.

Until the green AgentBeats registration ID replaces the remaining placeholder,
the scenario preflight deliberately fails before starting benchmark containers.
