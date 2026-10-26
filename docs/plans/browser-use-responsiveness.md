# Browser responsiveness — 26 October 2026

This change improves the current remote browser viewer and execution adapter.
Browser sessions still end with their run. Persistent conversation sessions,
embedded native rendering, binary/video transport and immediate interruption of
an in-flight model request remain separate work.

## Local measurement

The baseline is PR #2326 at `14c831d0d`; both versions ran against an isolated,
headless Chromium test process and the same local HTML form. No model was called.
Five successive form-entry steps included typing, settling and reading the DOM.
The same-address navigation used the normal adapter wait and the baseline's
additional outer wait. These samples describe adapter overhead, not production
latency, cloud transport, task success rates or model performance.

| Measurement | Baseline | Changed adapter |
|---|---:|---:|
| Median form-entry step, five samples | 413 ms | 100 ms |
| Reopen the same address, one sample | 5,886 ms | 111 ms |

The form samples were 439/413/413/412/407 ms before and
100/89/101/126/94 ms after. The same-address result fixes a URL-change timeout;
it is not a general navigation speedup claim.

## Verification

`backend/tests/test_browser_interaction.py` covers document identity, history,
refusals, preview ownership, input independent of capture, and stale decisions
following human control. The existing browser, routing, local-device and live-view
tests cover the integration contracts.

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
