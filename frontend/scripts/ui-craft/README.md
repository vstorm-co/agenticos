# UI craft browser fixture

This runs the real Next chat page with synthetic conversation data, explicit browser API routes, and a mocked chat WebSocket. It is a frontend browser/API fixture, **not backend E2E**. The existing backend-seeded Playwright tests remain under `frontend/e2e`.

Start the app from `frontend` with `BACKEND_URL=http://127.0.0.1:9` and port 3217. Browser routing cannot intercept server-side branding/bootstrap requests, so that loopback-only backend setting matters.

```powershell
$env:BACKEND_URL = 'http://127.0.0.1:9'
npx bun run dev --hostname 127.0.0.1 --port 3217
```

In another terminal, from `frontend`:

```powershell
node scripts/ui-craft/capture.mjs --stage baseline
node scripts/ui-craft/capture.mjs --stage iteration-1
node scripts/ui-craft/capture.mjs --stage iteration-2 --extra-states
```

Use `--channel msedge` if the Playwright Chromium browser is not installed. The harness launches one headless browser, reuses it for five viewport contexts (1440×1000, 1024×768, 768×1024, 390×844, and 320×740), and closes it. `--viewport 1440` limits a diagnostic run; `--capture-only` skips interaction checks but still records geometry and network failures. Neither option qualifies as a complete verification run.

Evidence is written to `frontend/.qa/ui-craft/<stage>/`: viewport PNGs, long-content PNGs, menu PNGs, a JSON report, and a readable summary. Each report records revision and source hashes so separate improvement stages can be compared. A failing check does not prevent screenshots; the process exits nonzero after recording all results.

`--extra-states` additionally captures a new empty chat and a focused multiline draft at 1440×1000 and 390×844. These states use the same browser and never submit the draft. The runner waits for the local TCP listener before launching the browser, then waits for the real Markdown table and code block before conversation captures; raw Markdown loading fallbacks do not qualify as ready.

## Coverage

- Seed assertions ensure the real conversation is present before capture.
- Page, transcript, composer, and control measurements reveal horizontal overflow and clipping.
- Long agent title, filename, URL, code line, and Markdown table stress narrow layouts.
- Typing, Shift+Enter, composition Enter, send, keyboard message actions, attachment/agent/model menu containment, and reading position during streamed growth are checked.
- Every browser API response comes from an explicit fixture. Unknown API routes return 501 and fail the report. External HTTP is blocked and recorded. App WebSockets are mocked, and only the local Next development socket may connect.
- The script does not inject layout CSS, conceal overflow, or call model providers.

## Limits

The fixture does not prove backend authorization, database persistence, real uploads/downloads, provider behavior, reconnect correctness, or native mobile keyboard/IME behavior. The composition check dispatches DOM composition events. The mobile captures are narrow desktop-browser viewports; they are not physical-device tests. Synthetic identities and messages are deliberately neutral. Do not treat screenshots as production user data or the API fixture as a substitute for the backend E2E suite.
