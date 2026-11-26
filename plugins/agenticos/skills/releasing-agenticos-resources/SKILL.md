---
name: releasing-agenticos-resources
description: Takes an AgenticOS agent through datasets, evals, published versions, staging, promotion and rollback. Use when the user wants a tested agent release, regression checks, promotion guards or a previous agent version restored.
---

# Release one measured version

Requires MCP contract 1 and the advertised quality lifecycle tools. Call
`get_platform_context` and `whoami`; assistant-only routes require OAuth.
Use the current tool schemas. Publication mints a version; environment pointers
and `tracks_latest` decide who starts using it.

1. Read the agent, its published version via `get_agent_version`, its draft,
   environments and suites. Preserve unrelated pending edits. Record production's
   current version ID for comparison and potential rollback.
2. If production tracks latest, turn that off before publishing a candidate when
   the task calls for staged release. Describe this operational change first.
3. Find or `create_dataset`, then `add_dataset_case` with real expectations and
   `list_dataset_cases` to verify. Include ordinary, unsupported and refused
   requests. Do not invent expected answers from an unverified policy.
4. Configure staging and test connections with `create_agent_environment` or
   `update_agent_environment`. A name alone does not isolate external effects.
5. `estimate_eval_run` with the exact candidate, dataset and test environment;
   show the estimate. After authorization use the same request for
   `start_eval_run`. Poll `get_eval_run` until settled. Queued is not passed;
   inconclusive, ungraded and partial measurements are not evidence of success.
6. Publish only within the requested release scope. Read the immutable version
   back. Repoint staging to it and check the version actually serving there.
7. For recurring checks, estimate and create a suite with explicit triggers and
   a spending cap. Read the environment's promotion gate for the exact candidate.
   If checks are needed, price the relevant suite configuration before
   `run_promotion_gate`, then poll the gate. Guard configuration and overrides
   keep their stronger permissions and human-session restrictions.
8. Promote production with `update_agent_environment` only when the agreed checks
   pass. Read environments back and report the resulting pointer and live effects.

Do not weaken or remove a guard merely because it blocked promotion. A refusal
requiring the person's console session is a handoff, not a reason to try another
credential. Changing shared Context or main-line skills can affect runs without
an agent publish; include those dependencies in the release assessment.

## Rollback

Read the target immutable version and the environment's current pointer. Repoint
the environment to that existing version through the same promotion policy,
then read it back. Do not republish an old draft, delete history or restore the
platform database to roll back an agent. Refer to the deployment skill only when
the platform code or schema itself must change.
