# Localized Improve and eval failures — 26 November 2026

Reviewed source deltas against `3a916cd0ff91b71d4ed58d661715e8b473d48c29`:

- #3451: `5027d7981bc8527928433df4eb9366378c5f0401`;
- #3452: `825955b700e8a091800cf0eabc649177d6a4e495`;
- #3453: `413a651ce82a9ea981fe77aa0a9ef1ac7e1229a0`.

Only each PR's own commits are included. French and Turkish screen catalogs are
aligned with this train's English vocabulary rather than importing untranslated
features from the source parent. New regression checks preserve the current
screen arguments and selector branches in both languages. They exposed an
unsupported set of Turkish reasons inherited from that parent. The copy now
matches the reasons this train actually emits. The existing Turkish contract
check also exposed a missing exact singular branch in the new catalog selector;
that translation is repaired without weakening the check.

Comparison/refusal codes are closed schema types; interpolated parameters hold
counts, not user-authored names or error messages. Legacy/unknown codes and
missing counts retain the server's sentence. A known refusal can keep its
original technical detail separately instead of losing which resource failed.
Retries clear the message, code and parameters together.

Migration `0369_run_error_code.py` retains its source revision identity and
branches from this train's `0370_console_role_presentation`. Its historical-row
test exercises this exact revision, including downgrade/re-upgrade, rather than
assuming that an in-flight multi-head tree has one `head`. The final integration
joins the independent heads explicitly.

Verification: 42 code/reason/migration tests, 192 real-PostgreSQL eval/holdout/
retrieval/skill tests, 73 real-PostgreSQL authoring tests and 270 focused frontend/
translation tests pass. Type checking passes. A broader Improve integration
batch was interrupted to reduce laptop contention and is not reported as a pass;
full aggregate CI is still owed. No paid provider calls were used.
