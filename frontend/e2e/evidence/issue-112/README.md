# Issue #112: rendered evidence for browser credential fill and protected continuation

These images are fixture-backed rendered UI evidence. They use synthetic metadata and receipts only, at desktop (1440x900) and mobile (390x844) widths.

They show layout and copy on the real routes. They do not prove a live credential fill, a site submission, cookie export, or a deployment output purge.

| File (desktop and mobile) | Route and step | Shows |
|---|---|---|
| `browser-login-form-fixture-*.png` | `/vault`, Add browser login | Username and password typed into password-type fields |
| `browser-destination-review-fixture-*.png` | `/runs?tab=approvals`, Review destination | Exact origin, saved credential and fields, with a Confirm fill action |
| `browser-separate-submit-fixture-*.png` | Same dialog, after Confirm fill | Selected fields filled; Submit this form is a separate action |
| `browser-protected-view-fixture-*.png` | `/browse/{run}/{call}` | Protected summary: page text, images and ordinary browser controls stay hidden |
| `continuation-consent-fixture-*.png` | Review continuation, before any choice | Exact origin; Keep me signed in unchecked |
| `continuation-continued-receipt-fixture-*.png` | Same panel, after Continue | Protected continuation outcome; cookies saved only with explicit consent |

## How these were produced

```bash
cd frontend
E2E_PORT=3100 bunx playwright test e2e/browser-credential-visual-fixtures.spec.ts e2e/browser-continuation-visual-fixtures.spec.ts --project=chromium --no-deps --workers=1 --timeout=120000
```

- The run used `next dev` on the local stack, not a production build. CI runs the standalone build.
- `--no-deps` skipped the seed project. Its "a colleague is a member" step timed out on the local stack. These fixture specs do not depend on that step.
- `--timeout=120000` gave slow on-demand compiles on this machine more room. The 15-second expect timeout in `playwright.config.ts` is unchanged.
- Each PNG is copied unchanged from `frontend/test-results/`.
