---
name: distill-experience
description: Inspect newly committed OpenViking trajectories, classify useful sessions, and distill repeated evidence into memory, Obsidian knowledge, provisional experience, validated skills, or human review. Use for the scheduled Agent Garden Dream, after a cluster of corrected or successful tasks, or when explicitly asked to absorb recent experience.
---

# Distill Experience

Turn raw practice into durable assets without treating every plausible idea as truth. Keep trajectories in OpenViking; write only stable, useful outputs to the Garden.

## Capture new evidence

From the project root, run:

```bash
python garden/skills/distill-experience/scripts/dream_state.py check
```

Inspect OpenViking sessions not yet recorded in the state output. Count a session as useful only if it contains at least one of: a tool call, user correction, non-trivial artifact, failure retrospective, or explicit new knowledge. Record each decision exactly once:

```bash
python garden/skills/distill-experience/scripts/dream_state.py record SESSION_KEY --useful
python garden/skills/distill-experience/scripts/dream_state.py record SESSION_KEY --not-useful
```

For each newly useful session, search trajectories and experiences semantically, then group reusable candidates by behavior or claim. Treat two traces as independent only when they are separate attempts and the later success did not merely copy the earlier output. Do this lightweight capture on every scheduled scan; do not wait for the periodic full-Dream threshold.

For every candidate, capture source URIs and one concrete counterexample or failure condition. Read [promotion-policy.md](references/promotion-policy.md) before writing or promoting anything.

Record each independent outcome with `scripts/promotion_gate.py observe`. A single success remains provisional and must not change an active Skill.

## Run the Dream gates

After recording all new sessions and candidate observations, run both gates:

```bash
python garden/skills/distill-experience/scripts/dream_state.py check
python garden/skills/distill-experience/scripts/promotion_gate.py ready
```

Run a full Dream when the periodic gate reports `due: true` or the event gate reports `ready: true`. The event gate becomes ready when a candidate has at least two independent successful trajectories not handled by an earlier Dream. Stop after the lightweight scan when neither gate is ready. A user request to run a full Dream overrides these timing gates, but never overrides the evidence or safety rules.

For every candidate handled by the full Dream, run `evaluate`. Treat its route as a hard ceiling: never promote beyond `provisional_experience`, `validated_experience`, or `review` when the gate returns that route. A Skill may be created only when the gate returns `promote_skill` after `--skill-validation passed`.

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
5. For each event candidate durably recorded by that commit, run `python garden/skills/distill-experience/scripts/promotion_gate.py resolve CANDIDATE --route ROUTE`.

Resolve an event only after its outcome is durable in the Garden audit. If validation, synchronization, or Git commit fails, keep the candidate provisional or in review, do not mark the Dream complete, and do not resolve the event; it must remain ready for retry.
