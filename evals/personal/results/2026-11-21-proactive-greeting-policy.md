# Private greeting and useful proposals: candidate verification

This candidate intentionally changes the old strict no-tool greeting contract. The first human greeting in a private conversation can read existing private task boards and the selected board's tasks. An absent board leads to an offer to create one; an empty board leads to an offer to collect tasks; a populated board supports a brief summary of observed priorities. A greeting never grants write consent. Explicit no-tools instructions, repeated greetings and shared/public contexts retain their quiet behavior. Current user/runtime instructions asking for less initiative take precedence.

The starter also suggests one Table as a structured working record for multi-topic research, and answers a recurring-news question before proposing one Routine with a cadence and destination. These are offers, not creation or activation authority. Existing one-off, scope, watch-versus-routine and delegation rules remain in place.

## Deterministic evidence

- Corpus validation: AgenticOS 122, memory 50, briefing 50; 222 cases total.
- Runner unit checks: 32 passed, including the later explicit native-candidate preflight and receipt checks. New checks cover absent/empty/populated task reads, exact private-board selection, no repeated lookup, unrelated operations, no-tool turns, proposal cues and fixture subject/tenant isolation.
- Backend template/defaults/shipped-update tests: 81 passed. The actual new bundled instructions update an untouched managed prompt, while a customized prompt and personal model remain unchanged through the existing fingerprint merge.
- The read fixtures substitute only the selected eval subject's task service reads and restore the originals after each case. They create and delete no task boards or tasks. Other users, tenants and table IDs fall through to the real service. This is a model-routing fixture, not an authorization or persistence certification.

These deterministic checks establish corpus and harness behavior, not a measured model success rate. The earlier [106/110 benchmark and four follow-ups](2026-11-20-personal-benchmark-rerun.md) and [channel/research verification](2026-11-20-channel-research-regressions.md) remain historical results for their own prompt versions.

## Native candidate smoke: measured before the follow-up fixes

One approved process completed all seven cases against the isolated QA database on migration 0348, using `openrouter:deepseek/deepseek-v4-flash-0731`. The exact model was present in the live provider catalog. A named QA profile reused an accessible vault reference without changing the user's selected model or default. No judge ran. The total ceiling was $0.25; complete metered spend was **$0.153621**, with **4/7 passing** the then-current deterministic checks. Wall time was 340.3 seconds; aggregate usage was 1,097,333 input and 3,185 output tokens across all requests, not unique context tokens.

The source publication was `9e185c38-0b0b-4acb-a534-c34ffbe6d087`. Its stored instructions, model, draft and publication were not overwritten. Candidate runs correctly attribute `agent_version=null`; the source version is provenance, not a claim that the published agent passed.

- Measured instructions hash: `cca08d8657bebdf9186deca255fd20b7d0925c9926955a54fede76019a099b5c`.
- Measured ephemeral spec hash: `d8763b1fdeae658baa19f002cfe11d8c54791019fd34d2c68f0bc9d36f5f3955`.
- Exact binding delta: only `browser_use` was omitted through explicit QA-only `--candidate-without-browser`. The source browser endpoint was not allowed in this deployment; neither the allowlist nor saved bindings were changed. Other bindings were retained. This prompt smoke does not establish equivalence to the full publication or validate browser behavior.

| Case | Original result | Calls | Cost USD | Latency s | Evidence |
| --- | --- | ---: | ---: | ---: | --- |
| `natural-hello` | Pass | 1 | 0.023608 | 57.502 | Read absent board; offered setup without creating it. Polish phrasing was occasionally awkward. |
| `hello-empty-board` | Pass | 2 | 0.035441 | 65.782 | Read selected private board and tasks; stated empty and offered collecting work. |
| `hello-priorities` | Fail | 3 | 0.035747 | 78.878 | Summarized both observed tasks with their deadlines, but also attempted an unrelated saved-language change. Isolation blocked the write. |
| `hello-no-tools` | Pass | 0 | 0.011770 | 23.285 | Simple Polish greeting; honored explicit no-tools request. |
| `hello-shared-channel` | Pass | 0 | 0.012000 | 23.566 | Shared-room greeting; no private task lookup. |
| `research-working-table-offer` | Fail | 0 | 0.011562 | 25.505 | Compared supplied options but proposed an unverified existing CSV/worksheet instead of an AgenticOS Table. Also incorrectly called a higher-priced option cheapest in one row; comparison accuracy is separate from the missing platform proposal. |
| `news-routine-offer` | Fail | 1 | 0.023493 | 65.717 | Answered news and named a weekday cadence, but omitted the Inbox destination, attempted `propose_setup` before acceptance and claimed a displayed proposal despite the blocked call. |

No resource write succeeded. Task reads were controlled absent/empty/populated fixtures, not live user task data. Raw receipts and logs remain local outside the repository; the table records synthetic-case findings without copying private runtime context. Read-only greetings still consumed substantial model input and tens of seconds; this run does not demonstrate low-latency or token-efficient operation.

## Follow-up prompt fixes: deterministic checks only

After the immutable smoke finished, the instructions were clarified to keep greeting language/profile/memory changes unsaved unless the current request explicitly asks for settings; name an AgenticOS Table as the persistent working record without inventing an existing file; ground price comparisons in supplied data; and make a Routine offer in the answer with cadence and Inbox destination before any draft/proposal tool. A blocked tool cannot establish a displayed card.

The scorer now rejects unaccepted `propose_setup` attempts in both offer cases and requires the platform to be named for the Table offer. Regression fixtures cover preference writes during a conversation-language greeting, generic spreadsheet substitution and draft creation before acceptance. These checks are independent of the comparison vendor names. Arithmetic and answer quality still require qualitative review; text cues do not certify them.

Final runtime instructions fingerprint (`SHA256(instructions.strip().encode())`): **a3d80a6816eb31fa6e03fc16e091b3bce5a548f08230c6ecb578765f12de9ef6**. The earlier intermediate note `ce407df52dd093a93a0efafe420b377292db2e4394e8127a7ae54dc8f1dd5fba` is the digest of the JSON-encoded instructions string, not the runtime fingerprint; both identify the same text through different encodings.

A free preflight of the three previously failing cases passed with the final runtime fingerprint and candidate spec hash `55b31794b476079b56089924ab76cb8ad8589c65dd335e3362d84f8283b580b4`, retaining the same source publication and explicit browser omission. A paid follow-up was considered within the original $0.25 ceiling, but was **not launched**: the existing model budget guard checks already-booked spend before each request and records the next request's cost after its response. It does not reserve a worst-case next-request charge, so a $0.09 run limit cannot guarantee the requested cumulative hard ceiling. Historical three-case spend is an estimate, not an upper bound.

This later prompt has **not** been measured in a paid rerun. The 4/7 result above belongs only to the measured hash. Total paid spend remains $0.153621; no additional paid retry was performed.
