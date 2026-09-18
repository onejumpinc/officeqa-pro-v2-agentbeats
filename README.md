# OfficeQA Pro v2 AgentBeats Leaderboard

This directory contains the OfficeQA Pro v2 files that replace the defaults in a
standalone repository created from
`RDI-Foundation/agentbeats-leaderboard-template`.

The assessment runs all 90 questions in 10 deterministic shards. The green
agent downloads the gated answer CSV at its pinned Hugging Face revision during
the run. The answer key is not included in either public container image.

## Required setup

1. Create a public repository from the official AgentBeats leaderboard template.
2. Copy `scenario.json5`, `green-agent.json5`, `leaderboard-query.json`, and `.github/workflows/quick-submit.yml` into it. Keep the template's other workflows and directories.
3. Replace both `REPLACE_WITH_*_AGENT_ID` values in `scenario.json5` after the green and OpenCode agents are registered on AgentBeats.
4. Add `OFFICEQA_PRO_V2_HF_TOKEN` as a leaderboard repository secret. The token must have accepted access to `databricks/officeqa-pro-v2`.
5. Install the AgentBeats GitHub App on the leaderboard repository.
6. Paste `leaderboard-query.json` into the green agent's leaderboard configuration on AgentBeats.

For a local or manual scenario run, also add these repository secrets:

- `GREEN_HF_TOKEN`
- `PARTICIPANT_API_URL`
- `PARTICIPANT_API_TOKEN`

Use `num_instances: 10` for the first smoke run. Remove it for the scored
90-question run.
