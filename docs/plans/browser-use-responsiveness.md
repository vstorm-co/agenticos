# Browser responsiveness — 26 October 2026

This change improves the current remote browser viewer and execution adapter.
Browser sessions still end with their run. Persistent conversation sessions,
embedded native rendering, binary/video transport and immediate interruption of
an in-flight model request remain separate work.

## Local measurement

The baseline is PR #2326 at `14c831d0d`; both versions ran against an isolated,
headless Chromium test process and the same local HTML form. No model was called.
Five successive form-entry steps included typing, settling and reading the DOM.
Explicit navigations used the normal adapter wait and the baseline's additional
outer wait. Five distinct-address samples were collected; reopening the same
address was measured once. These samples describe adapter overhead, not production
latency, cloud transport, task success rates or model performance.

| Measurement | Baseline | Changed adapter |
|---|---:|---:|
| Median form-entry step, five samples | 405 ms | 405 ms |
| Median distinct-address navigation, five samples | 817 ms | 413 ms |
| Reopen the same address, one sample | 5,904 ms | 416 ms |

The form samples were 448/405/405/406/405 ms before and
409/407/405/405/405 ms after. Distinct-address navigation samples were
844/817/822/813/813 ms before and 417/413/412/413/421 ms after.
The same-address result fixes a URL-change timeout. An initial 80 ms quiet-only
readiness window was rejected during review because it could miss delayed DOM
updates. The final policy retains a 400 ms initial grace when no mutations have
arrived, then waits for 80 ms of quiet after mutations, bounded at 1.5 seconds
for changing DOM and 5 seconds for document loading. This explains the unchanged
static form latency; navigation improves by removing the duplicate wait.

## Verification

`backend/tests/test_browser_interaction.py` covers document identity, history,
refusals, preview ownership, input independent of capture, and stale decisions
following human control. The existing browser, routing, local-device and live-view
tests cover the integration contracts. `test_browser_preview.py` covers reader
loss, reconnection, SPA metadata and preview lifecycle; live-view tests verify
that trace consumers do not count as image viewers and metadata keeps the last
JPEG available. Held previews also recover after transient metadata failures.

`backend/tests/test_browser_interaction_live.py` runs the real CDP adapter against
an HTTP fixture and a new Chromium profile. It covers same-address navigation,
history, reload, delayed DOM mutations and paints arriving without agent actions.
To opt in, install the repository's `browser` extra, set
`AGENTICOS_TEST_CHROMIUM` to a test Chromium executable, and run that file from
`backend/`. It never attaches to an existing browser.

Next measure real tasks on Built in, hosted and local targets. Separate model time,
cold start, action/readiness, image encoding and transport, and compare p50/p95,
success and retries. Do not select a new model or transport from these local
samples alone.

The viewer was also rendered with production CSS at 320, 390 and 900 px: controls
stay within the viewport and the address remains usable. A regression test
reproduced a 2560 by 2160 px viewer sending dimensions beyond the server's
1600 by 2000 px bounds. Clamping those requests avoids waiting for a rejected
first fit; this is separate from the adapter measurements above.
