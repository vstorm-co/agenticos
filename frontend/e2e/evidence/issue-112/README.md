# Issue #112: rendered evidence for browser credential fill and protected continuation

These images are fixture-backed rendered UI evidence. They use synthetic metadata and receipts only, at desktop (1440x900) and mobile (390x844) widths.

They show layout and copy on the real routes. They do not prove a live credential fill, a site submission, cookie export, or a deployment output purge.

| File (desktop and mobile)                                 | Route and step                                  | Shows                                                                                         |
| --------------------------------------------------------- | ----------------------------------------------- | --------------------------------------------------------------------------------------------- |
| `browser-login-form-fixture-*.png`                        | `/vault`, Add browser login                     | Username and password typed into password-type fields                                         |
| `browser-destination-review-fixture-*.png`                | `/runs?tab=approvals`, Review destination       | Exact origin, saved credential and fields, with a Confirm fill action                         |
| `browser-separate-submit-fixture-*.png`                   | Same dialog, after Confirm fill                 | Selected fields filled; Submit this form is a separate action                                 |
| `browser-protected-view-fixture-*.png`                    | `/browse/{run}/{call}`                          | Protected summary: page text, images and ordinary browser controls stay hidden                |
| `browser-protected-loading-heading-{before,after}-*.png`  | `/browse/{run}/{call}`, while the output loads  | Loading heading: "Live browser" before the fix, "Protected browser" after                     |
| `browser-protected-view-one-heading-{before,after}-*.png` | `/browse/{run}/{call}`, loaded protected browse | One "Protected browser" heading, the page title: the window bar named it twice before the fix |
| `continuation-consent-fixture-*.png`                      | Review continuation, before any choice          | Exact origin; Keep me signed in unchecked                                                     |
| `continuation-continued-receipt-fixture-*.png`            | Same panel, after Continue                      | Protected continuation outcome; cookies saved only with explicit consent                      |

## How these were produced

```bash
cd frontend
E2E_PORT=3100 bunx playwright test e2e/browser-credential-visual-fixtures.spec.ts e2e/browser-continuation-visual-fixtures.spec.ts --project=chromium --no-deps --workers=1 --timeout=120000
```

- The run used `next dev` on the local stack, not a production build. CI runs the standalone build.
- `--no-deps` skipped the seed project. Its "a colleague is a member" step timed out on the local stack. These fixture specs do not depend on that step.
- `--timeout=120000` gave slow on-demand compiles on this machine more room. The 15-second expect timeout in `playwright.config.ts` is unchanged.
- Each PNG is copied unchanged from `frontend/test-results/`.
- `browser-protected-view-heading-fixture-*.png` is the #174 state. The page title and the protected window both read "Protected browser", which the window bar no longer repeats; `browser-protected-view-one-heading-*.png` below is the current state. The `browser-protected-view-fixture-*.png` pair above shows "Live browser" as the title. It came from the protected-view test alone: `E2E_PORT=3100 bun run test:e2e e2e/browser-credential-visual-fixtures.spec.ts --project=chromium --no-deps --workers=1 --timeout=120000 -g "protected live view"`.
- `browser-protected-view-one-heading-{before,after}-*.png` show a loaded protected browse. They come from `e2e/browser-protected-heading-visual-fixtures.spec.ts`, which needs no backend, as the loading pair does. The before pair was captured on the base commit `88ca8cfa4`. The spec takes its screenshot before the heading assertions, so a failing run still leaves the picture. Command: `E2E_PORT=3100 bun run test:e2e e2e/browser-protected-heading-visual-fixtures.spec.ts --project=chromium --no-deps --workers=1 --timeout=120000`.
- `browser-protected-loading-heading-before-*.png` and `browser-protected-loading-heading-after-*.png` show a protected browse while its output still loads. They come from `e2e/browser-loading-visual-fixtures.spec.ts`, which needs no backend: `/api/auth/me` and the browse socket are synthetic, and every other API call answers 404, so the sidebar reads "Select organization". The before pair was captured with the loading title expression reverted to `t("title")`, which matches the code at `e48ac367f`. Command: `E2E_PORT=3100 bun run test:e2e e2e/browser-loading-visual-fixtures.spec.ts --project=chromium --no-deps --workers=1 --timeout=120000`.
