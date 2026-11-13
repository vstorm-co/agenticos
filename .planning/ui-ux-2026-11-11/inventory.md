# Console UI/UX inventory — 2026-11-11

101 page routes; 1251 component modules in 58 families.

Generated from local TypeScript imports and re-exports. Layout dependencies include shared providers and barrel exports, so reachability is deliberately broader than actual rendering. Runtime status belongs in the audit report; source mapping does not mean a screen was tested. Dynamic imports require runtime verification.

## Routes

| Route | Page components (static reachability) | Source |
| --- | ---: | --- |
| `/` | 0 | `frontend/src/app/[locale]/page.tsx` |
| `/a/[publicKey]` | 154 | `frontend/src/app/[locale]/a/[publicKey]/page.tsx` |
| `/admin` | 0 | `frontend/src/app/[locale]/(dashboard)/admin/page.tsx` |
| `/admin/background-jobs` | 156 | `frontend/src/app/[locale]/(dashboard)/admin/background-jobs/page.tsx` |
| `/admin/organizations` | 146 | `frontend/src/app/[locale]/(dashboard)/admin/organizations/page.tsx` |
| `/admin/organizations/[id]` | 146 | `frontend/src/app/[locale]/(dashboard)/admin/organizations/[id]/page.tsx` |
| `/admin/settings` | 156 | `frontend/src/app/[locale]/(dashboard)/admin/settings/page.tsx` |
| `/admin/system` | 146 | `frontend/src/app/[locale]/(dashboard)/admin/system/page.tsx` |
| `/admin/users` | 147 | `frontend/src/app/[locale]/(dashboard)/admin/users/page.tsx` |
| `/agents` | 159 | `frontend/src/app/[locale]/(dashboard)/agents/page.tsx` |
| `/agents/[id]` | 521 | `frontend/src/app/[locale]/(dashboard)/agents/[id]/page.tsx` |
| `/agents/[id]/evals/[runId]` | 179 | `frontend/src/app/[locale]/(dashboard)/agents/[id]/evals/[runId]/page.tsx` |
| `/agents/[id]/improve/[session]` | 202 | `frontend/src/app/[locale]/(dashboard)/agents/[id]/improve/[session]/page.tsx` |
| `/apps` | 160 | `frontend/src/app/[locale]/(dashboard)/apps/page.tsx` |
| `/apps/[id]` | 198 | `frontend/src/app/[locale]/(viewer)/apps/[id]/page.tsx` |
| `/auth/callback` | 146 | `frontend/src/app/[locale]/auth/callback/page.tsx` |
| `/auth/email-change` | 146 | `frontend/src/app/[locale]/auth/email-change/page.tsx` |
| `/auth/magic-link` | 146 | `frontend/src/app/[locale]/auth/magic-link/page.tsx` |
| `/auth/pair` | 147 | `frontend/src/app/[locale]/auth/pair/page.tsx` |
| `/browse/[runId]/[callId]` | 153 | `frontend/src/app/[locale]/(dashboard)/browse/[runId]/[callId]/page.tsx` |
| `/channels` | 162 | `frontend/src/app/[locale]/(dashboard)/channels/page.tsx` |
| `/chat` | 327 | `frontend/src/app/[locale]/(dashboard)/chat/page.tsx` |
| `/context` | 180 | `frontend/src/app/[locale]/(dashboard)/context/page.tsx` |
| `/dashboard` | 307 | `frontend/src/app/[locale]/(dashboard)/dashboard/page.tsx` |
| `/datasets` | 154 | `frontend/src/app/[locale]/(dashboard)/datasets/page.tsx` |
| `/datasets/[id]` | 232 | `frontend/src/app/[locale]/(dashboard)/datasets/[id]/page.tsx` |
| `/desktop/blobby` | 149 | `frontend/src/app/[locale]/desktop/blobby/page.tsx` |
| `/desktop/quick-ask` | 325 | `frontend/src/app/[locale]/desktop/quick-ask/page.tsx` |
| `/desktop/readiness` | 148 | `frontend/src/app/[locale]/desktop/readiness/page.tsx` |
| `/desktop/welcome` | 148 | `frontend/src/app/[locale]/desktop/welcome/page.tsx` |
| `/dev/components` | 69 | `frontend/src/app/[locale]/(dashboard)/dev/components/page.tsx` |
| `/documents` | 151 | `frontend/src/app/[locale]/(dashboard)/documents/page.tsx` |
| `/documents/[id]` | 151 | `frontend/src/app/[locale]/(dashboard)/documents/[id]/page.tsx` |
| `/e/[publicKey]` | 213 | `frontend/src/app/[locale]/e/[publicKey]/page.tsx` |
| `/evals` | 153 | `frontend/src/app/[locale]/(dashboard)/evals/page.tsx` |
| `/f/[token]` | 64 | `frontend/src/app/[locale]/f/[token]/page.tsx` |
| `/forgot-password` | 155 | `frontend/src/app/[locale]/(auth)/forgot-password/page.tsx` |
| `/groups` | 156 | `frontend/src/app/[locale]/(dashboard)/groups/page.tsx` |
| `/groups/[id]` | 165 | `frontend/src/app/[locale]/(dashboard)/groups/[id]/page.tsx` |
| `/inbox` | 174 | `frontend/src/app/[locale]/(dashboard)/inbox/page.tsx` |
| `/invitations/[token]` | 148 | `frontend/src/app/[locale]/(dashboard)/invitations/[token]/page.tsx` |
| `/invitations/pending` | 148 | `frontend/src/app/[locale]/(dashboard)/invitations/pending/page.tsx` |
| `/kb` | 0 | `frontend/src/app/[locale]/(dashboard)/kb/page.tsx` |
| `/kb/[id]` | 0 | `frontend/src/app/[locale]/(dashboard)/kb/[id]/page.tsx` |
| `/legal/cookies` | 2 | `frontend/src/app/[locale]/legal/cookies/page.tsx` |
| `/legal/privacy` | 2 | `frontend/src/app/[locale]/legal/privacy/page.tsx` |
| `/legal/terms` | 2 | `frontend/src/app/[locale]/legal/terms/page.tsx` |
| `/link/[token]` | 146 | `frontend/src/app/[locale]/(dashboard)/link/[token]/page.tsx` |
| `/login` | 155 | `frontend/src/app/[locale]/(auth)/login/page.tsx` |
| `/magic-link-sent` | 0 | `frontend/src/app/[locale]/(auth)/magic-link-sent/page.tsx` |
| `/mcp-servers` | 173 | `frontend/src/app/[locale]/(dashboard)/mcp-servers/page.tsx` |
| `/oauth/consent` | 148 | `frontend/src/app/[locale]/(viewer)/oauth/consent/page.tsx` |
| `/onboarding` | 204 | `frontend/src/app/[locale]/onboarding/page.tsx` |
| `/onboarding/[...step]` | 0 | `frontend/src/app/[locale]/onboarding/[...step]/page.tsx` |
| `/orgs` | 166 | `frontend/src/app/[locale]/(dashboard)/orgs/page.tsx` |
| `/orgs/[id]/directory` | 150 | `frontend/src/app/[locale]/(dashboard)/orgs/[id]/directory/page.tsx` |
| `/orgs/[id]/groups` | 155 | `frontend/src/app/[locale]/(dashboard)/orgs/[id]/groups/page.tsx` |
| `/orgs/[id]/members` | 170 | `frontend/src/app/[locale]/(dashboard)/orgs/[id]/members/page.tsx` |
| `/orgs/[id]/retention` | 149 | `frontend/src/app/[locale]/(dashboard)/orgs/[id]/retention/page.tsx` |
| `/orgs/[id]/roles` | 148 | `frontend/src/app/[locale]/(dashboard)/orgs/[id]/roles/page.tsx` |
| `/profile` | 0 | `frontend/src/app/[locale]/(dashboard)/profile/page.tsx` |
| `/projects` | 155 | `frontend/src/app/[locale]/(dashboard)/projects/page.tsx` |
| `/projects/[id]` | 190 | `frontend/src/app/[locale]/(dashboard)/projects/[id]/page.tsx` |
| `/rag` | 179 | `frontend/src/app/[locale]/(dashboard)/rag/page.tsx` |
| `/rag/[id]` | 205 | `frontend/src/app/[locale]/(dashboard)/rag/[id]/page.tsx` |
| `/register` | 155 | `frontend/src/app/[locale]/(auth)/register/page.tsx` |
| `/remote-agents` | 150 | `frontend/src/app/[locale]/(dashboard)/remote-agents/page.tsx` |
| `/reset-password` | 147 | `frontend/src/app/[locale]/(auth)/reset-password/page.tsx` |
| `/routines` | 191 | `frontend/src/app/[locale]/(dashboard)/routines/page.tsx` |
| `/runs` | 197 | `frontend/src/app/[locale]/(dashboard)/runs/page.tsx` |
| `/sandboxes` | 155 | `frontend/src/app/[locale]/(dashboard)/sandboxes/page.tsx` |
| `/settings` | 0 | `frontend/src/app/[locale]/(dashboard)/settings/page.tsx` |
| `/settings/account` | 147 | `frontend/src/app/[locale]/(dashboard)/settings/account/page.tsx` |
| `/settings/api-keys` | 153 | `frontend/src/app/[locale]/(dashboard)/settings/api-keys/page.tsx` |
| `/settings/api-keys/reference` | 151 | `frontend/src/app/[locale]/(dashboard)/settings/api-keys/reference/page.tsx` |
| `/settings/assistant` | 149 | `frontend/src/app/[locale]/(dashboard)/settings/assistant/page.tsx` |
| `/settings/blobby` | 149 | `frontend/src/app/[locale]/(dashboard)/settings/blobby/page.tsx` |
| `/settings/desktop` | 152 | `frontend/src/app/[locale]/(dashboard)/settings/desktop/page.tsx` |
| `/settings/mcp` | 150 | `frontend/src/app/[locale]/(dashboard)/settings/mcp/page.tsx` |
| `/settings/memory` | 156 | `frontend/src/app/[locale]/(dashboard)/settings/memory/page.tsx` |
| `/settings/mobile` | 152 | `frontend/src/app/[locale]/(dashboard)/settings/mobile/page.tsx` |
| `/settings/notifications` | 159 | `frontend/src/app/[locale]/(dashboard)/settings/notifications/page.tsx` |
| `/settings/profile` | 157 | `frontend/src/app/[locale]/(dashboard)/settings/profile/page.tsx` |
| `/settings/shortcuts` | 147 | `frontend/src/app/[locale]/(dashboard)/settings/shortcuts/page.tsx` |
| `/settings/sign-ins` | 148 | `frontend/src/app/[locale]/(dashboard)/settings/sign-ins/page.tsx` |
| `/settings/slash-commands` | 147 | `frontend/src/app/[locale]/(dashboard)/settings/slash-commands/page.tsx` |
| `/shared/[token]` | 161 | `frontend/src/app/[locale]/shared/[token]/page.tsx` |
| `/skills` | 178 | `frontend/src/app/[locale]/(dashboard)/skills/page.tsx` |
| `/skills/[id]` | 200 | `frontend/src/app/[locale]/(dashboard)/skills/[id]/page.tsx` |
| `/skills/[id]/improve/[session]` | 191 | `frontend/src/app/[locale]/(dashboard)/skills/[id]/improve/[session]/page.tsx` |
| `/tables` | 175 | `frontend/src/app/[locale]/(dashboard)/tables/page.tsx` |
| `/tables/[id]` | 200 | `frontend/src/app/[locale]/(dashboard)/tables/[id]/page.tsx` |
| `/vault` | 161 | `frontend/src/app/[locale]/(dashboard)/vault/page.tsx` |
| `/work` | 158 | `frontend/src/app/[locale]/(dashboard)/work/page.tsx` |
| `/workflows` | 161 | `frontend/src/app/[locale]/(dashboard)/workflows/page.tsx` |
| `/workflows/[id]` | 278 | `frontend/src/app/[locale]/(dashboard)/workflows/[id]/page.tsx` |
| `/workflows/[id]/form-preview` | 151 | `frontend/src/app/[locale]/(dashboard)/workflows/[id]/form-preview/page.tsx` |
| `/workflows/[id]/logs` | 155 | `frontend/src/app/[locale]/(dashboard)/workflows/[id]/logs/page.tsx` |
| `/workflows/[id]/runs` | 156 | `frontend/src/app/[locale]/(dashboard)/workflows/[id]/runs/page.tsx` |
| `/workflows/[id]/runs/[runId]` | 269 | `frontend/src/app/[locale]/(dashboard)/workflows/[id]/runs/[runId]/page.tsx` |
| `/workflows/runs` | 151 | `frontend/src/app/[locale]/(dashboard)/workflows/runs/page.tsx` |

## Component families

| Family | Modules |
| --- | ---: |
| .. | 1 |
| admin | 15 |
| agents | 103 |
| artifacts | 29 |
| assistant | 9 |
| auth | 8 |
| authoring | 24 |
| branding | 5 |
| browser | 2 |
| channels | 12 |
| charts | 2 |
| chat | 133 |
| context | 4 |
| dashboard | 98 |
| datasets | 58 |
| desktop | 27 |
| evals | 36 |
| files | 10 |
| groups | 6 |
| hosted | 1 |
| icons | 4 |
| improvement | 36 |
| inbox | 2 |
| kb | 14 |
| knowledge-gaps | 14 |
| language-switcher.tsx | 1 |
| layout | 32 |
| legal | 6 |
| live-updates | 2 |
| mcp | 8 |
| memory | 12 |
| mobile | 10 |
| oauth | 1 |
| onboarding | 39 |
| orgs | 15 |
| phone | 6 |
| projects | 16 |
| public-config | 1 |
| rag | 20 |
| remote-agents | 2 |
| runs | 24 |
| sandboxes | 21 |
| settings | 29 |
| shared | 1 |
| sharing | 10 |
| skill-improvement | 21 |
| skills | 33 |
| states | 7 |
| tables | 40 |
| tasks | 3 |
| teams | 15 |
| theme | 5 |
| triggers | 34 |
| ui | 62 |
| vault | 8 |
| voice | 12 |
| watches | 4 |
| workflows | 98 |

The JSON companion stores the complete local module import graph. Numeric references index `modules[]`; routes identify their page and layout modules, and families identify every component module. Following imports reconstructs each route’s dependencies without duplicating paths.
