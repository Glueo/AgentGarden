---
name: distill-experience
description: Inspect newly committed OpenViking trajectories, classify useful sessions, and distill repeated evidence into memory, Obsidian knowledge, provisional experience, validated skills, or human review. Use for the scheduled Agent Garden Dream, after a cluster of corrected or successful tasks, or when explicitly asked to absorb recent experience.
---

# Distill Experience

Turn raw practice into durable assets without treating every plausible idea as truth. Keep trajectories in OpenViking; write only stable, useful outputs to the Garden.

## Run the Dream gate

From the project root, run:

```bash
python garden/skills/distill-experience/scripts/dream_state.py check
```

Inspect OpenViking sessions not yet recorded in the state output. Count a session as useful only if it contains at least one of: a tool call, user correction, non-trivial artifact, failure retrospective, or explicit new knowledge. Record each decision exactly once:

```bash
python garden/skills/distill-experience/scripts/dream_state.py record SESSION_KEY --useful
python garden/skills/distill-experience/scripts/dream_state.py record SESSION_KEY --not-useful
```

Stop after the lightweight scan unless `check` reports `due: true`. A user request to run a full Dream overrides the time/count gate, but never overrides the safety rules.

## Build evidence groups

Search trajectories and experiences semantically, then group candidates by the behavior or claim that would be reused. Treat two traces as independent only when they are separate attempts and the later success did not merely copy the earlier output.

For every candidate, capture source URIs and one concrete counterexample or failure condition. Read [promotion-policy.md](references/promotion-policy.md) before writing or promoting anything.

## Route candidates

- Write explicit user preferences, entities, and events to OpenViking memory.
- Merge stable, attributable knowledge into `garden/wiki/` with the minimal Garden frontmatter.
- Keep a one-off process lesson as a provisional OpenViking experience.
- Create or update a skill only after two independent successful trajectories and one isolated forward test.
- Write conflicts, weak evidence, and all high-risk subjects to `garden/reviews/`; never overwrite a competing claim silently.

Do not invent subject folders. Add links and topics first; create a directory or Hub only after a stable content cluster appears, and record the schema migration.

## Validate a skill candidate

Keep each skill minimal: `SKILL.md` plus only required scripts, references, or assets. Run the format validator and representative tests in an isolated temporary directory. Reject any skill whose test requires an unauthorized external write.

Record the validation command, exit status, representative input, and observed output in the Dream audit.

## Commit an accepted Dream

Before changing OpenViking or the Garden, create an OpenViking snapshot. After all accepted changes:

1. Run `python automation/sync_garden.py`.
2. Append a concise entry to `garden/_system/dream-log.md`.
3. Stage only this Dream's Garden changes and create one Git commit.
4. Run `python garden/skills/distill-experience/scripts/dream_state.py complete --snapshot SNAPSHOT_ID --git-commit COMMIT_ID`.

If validation, synchronization, or Git commit fails, keep the candidate provisional or in review and do not mark the Dream complete.
