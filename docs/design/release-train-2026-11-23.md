# Release train — 2026-11-23

Repository-only operator planning snapshot. These are candidate changes, not a record of completed review, merges or deployment. Refresh each PR status before acting.

The [maintainer decision](https://github.com/vstorm-co/agenticos/discussions/3208#discussioncomment-19796269) separates independent green PR merges from one manual daily release cut. Keep the work in separate PRs; merge stacks in dependency order. This train contains features and changed defaults, so use a minor bump from the then-current `main`. A production deployment has its own approval.

| PR | Change | Depends on | Snapshot / remaining work |
|---|---|---|---|
| [#3255](https://github.com/vstorm-co/agenticos/pull/3255) | Routine execution, MCP Inbox reporting and simpler setup | main | Local acceptance tests and final CI in progress |
| [#3251](https://github.com/vstorm-co/agenticos/pull/3251) | feat(i18n): add French console locale | main | Reported checks green; verify review and required checks |
| [#3250](https://github.com/vstorm-co/agenticos/pull/3250) | fix(rag): search the checked base in gap drafts and workflow search | main | Reported checks green; verify review and required checks |
| [#3247](https://github.com/vstorm-co/agenticos/pull/3247) | fix(stats): leave system agents out of what needs attention | main | Reported checks green; verify review and required checks |
| [#3186](https://github.com/vstorm-co/agenticos/pull/3186) | feat(improve): measure criteria, costs and missing knowledge | main | Reported checks green; verify review and required checks |
| [#3237](https://github.com/vstorm-co/agenticos/pull/3237) | feat(improve): search many variants of an agent's instructions | #3186 | Reported checks green; verify review and required checks |
| [#3238](https://github.com/vstorm-co/agenticos/pull/3238) | feat(improve): choose Search variants and follow the search in the console | #3237 | Reported checks green; verify review and required checks |
| [#3240](https://github.com/vstorm-co/agenticos/pull/3240) | feat(datasets): grade the keys a written document must carry | #3186 | Reported checks green; verify review and required checks |
| [#3241](https://github.com/vstorm-co/agenticos/pull/3241) | feat(datasets): draft a case's keys from its reference answer | #3240 | Reported checks green; verify review and required checks |
| [#3242](https://github.com/vstorm-co/agenticos/pull/3242) | feat(datasets): report which keys none of an agent's sources covers | #3241 | Failing: backend-shards (1), test |
| [#3137](https://github.com/vstorm-co/agenticos/pull/3137) | feat(providers): add subscription access and external runtimes | main | Failing: e2e-shards (4), e2e; merge conflicts; complete the deferred credential/Vault review |

Integration order: merge #3186 before either improvement/dataset branch; then #3237 → #3238 and #3240 → #3241 → #3242. Retarget or refresh each dependent PR after its base merges and validate its new head. Other main-based PRs can merge independently once reviewed and green.

After the selected PRs land, cut once from fresh `origin/main`, preserving all `[Unreleased]` entries and operator upgrade notes. Require successful CI and CodeQL on the cut merge SHA, reusing only valid checked-source proof. Publish the release and tag together, wait for images/SBOMs, then perform the separately approved production deploy and smoke checks. Urgent hotfixes may use the same process outside this cadence.
