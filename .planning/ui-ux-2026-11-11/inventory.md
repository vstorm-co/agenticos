# Console UI/UX inventory — 2026-11-11

99 page routes; 1193 component modules in 57 families.

Generated from local TypeScript imports and re-exports. Layout dependencies include shared providers and barrel exports, so reachability is deliberately broader than actual rendering. Runtime status belongs in the audit report; source mapping does not mean a screen was tested. Dynamic imports require runtime verification.

## Routes

| Route | Page components (static reachability) | Source |
| --- | ---: | --- |
| `/` | 0 | `frontend/src/app/[locale]/page.tsx` |
| `/a/[publicKey]` | 153 | `frontend/src/app/[locale]/a/[publicKey]/page.tsx` |
| `/admin` | 0 | `frontend/src/app/[locale]/(dashboard)/admin/page.tsx` |
| `/admin/background-jobs` | 155 | `frontend/src/app/[locale]/(dashboard)/admin/background-jobs/page.tsx` |
| `/admin/organizations` | 145 | `frontend/src/app/[locale]/(dashboard)/admin/organizations/page.tsx` |
| `/admin/organizations/[id]` | 145 | `frontend/src/app/[locale]/(dashboard)/admin/organizations/[id]/page.tsx` |
| `/admin/settings` | 155 | `frontend/src/app/[locale]/(dashboard)/admin/settings/page.tsx` |
| `/admin/system` | 145 | `frontend/src/app/[locale]/(dashboard)/admin/system/page.tsx` |
| `/admin/users` | 146 | `frontend/src/app/[locale]/(dashboard)/admin/users/page.tsx` |
| `/agents` | 158 | `frontend/src/app/[locale]/(dashboard)/agents/page.tsx` |
| `/agents/[id]` | 517 | `frontend/src/app/[locale]/(dashboard)/agents/[id]/page.tsx` |
| `/agents/[id]/evals/[runId]` | 178 | `frontend/src/app/[locale]/(dashboard)/agents/[id]/evals/[runId]/page.tsx` |
| `/agents/[id]/improve/[session]` | 198 | `frontend/src/app/[locale]/(dashboard)/agents/[id]/improve/[session]/page.tsx` |
| `/apps` | 158 | `frontend/src/app/[locale]/(dashboard)/apps/page.tsx` |
| `/apps/[id]` | 197 | `frontend/src/app/[locale]/(viewer)/apps/[id]/page.tsx` |
| `/auth/callback` | 145 | `frontend/src/app/[locale]/auth/callback/page.tsx` |
| `/auth/email-change` | 145 | `frontend/src/app/[locale]/auth/email-change/page.tsx` |
| `/auth/magic-link` | 145 | `frontend/src/app/[locale]/auth/magic-link/page.tsx` |
| `/auth/pair` | 146 | `frontend/src/app/[locale]/auth/pair/page.tsx` |
| `/browse/[runId]/[callId]` | 152 | `frontend/src/app/[locale]/(dashboard)/browse/[runId]/[callId]/page.tsx` |
| `/channels` | 161 | `frontend/src/app/[locale]/(dashboard)/channels/page.tsx` |
| `/chat` | 324 | `frontend/src/app/[locale]/(dashboard)/chat/page.tsx` |
| `/context` | 178 | `frontend/src/app/[locale]/(dashboard)/context/page.tsx` |
| `/dashboard` | 306 | `frontend/src/app/[locale]/(dashboard)/dashboard/page.tsx` |
| `/datasets` | 152 | `frontend/src/app/[locale]/(dashboard)/datasets/page.tsx` |
| `/datasets/[id]` | 229 | `frontend/src/app/[locale]/(dashboard)/datasets/[id]/page.tsx` |
| `/desktop/blobby` | 148 | `frontend/src/app/[locale]/desktop/blobby/page.tsx` |
| `/desktop/quick-ask` | 322 | `frontend/src/app/[locale]/desktop/quick-ask/page.tsx` |
| `/desktop/readiness` | 147 | `frontend/src/app/[locale]/desktop/readiness/page.tsx` |
| `/desktop/welcome` | 147 | `frontend/src/app/[locale]/desktop/welcome/page.tsx` |
| `/dev/components` | 69 | `frontend/src/app/[locale]/(dashboard)/dev/components/page.tsx` |
| `/documents` | 150 | `frontend/src/app/[locale]/(dashboard)/documents/page.tsx` |
| `/documents/[id]` | 150 | `frontend/src/app/[locale]/(dashboard)/documents/[id]/page.tsx` |
| `/e/[publicKey]` | 212 | `frontend/src/app/[locale]/e/[publicKey]/page.tsx` |
| `/evals` | 152 | `frontend/src/app/[locale]/(dashboard)/evals/page.tsx` |
| `/f/[token]` | 64 | `frontend/src/app/[locale]/f/[token]/page.tsx` |
| `/forgot-password` | 154 | `frontend/src/app/[locale]/(auth)/forgot-password/page.tsx` |
| `/groups` | 155 | `frontend/src/app/[locale]/(dashboard)/groups/page.tsx` |
| `/groups/[id]` | 164 | `frontend/src/app/[locale]/(dashboard)/groups/[id]/page.tsx` |
| `/inbox` | 173 | `frontend/src/app/[locale]/(dashboard)/inbox/page.tsx` |
| `/invitations/[token]` | 147 | `frontend/src/app/[locale]/(dashboard)/invitations/[token]/page.tsx` |
| `/invitations/pending` | 147 | `frontend/src/app/[locale]/(dashboard)/invitations/pending/page.tsx` |
| `/kb` | 0 | `frontend/src/app/[locale]/(dashboard)/kb/page.tsx` |
| `/kb/[id]` | 0 | `frontend/src/app/[locale]/(dashboard)/kb/[id]/page.tsx` |
| `/legal/cookies` | 2 | `frontend/src/app/[locale]/legal/cookies/page.tsx` |
| `/legal/privacy` | 2 | `frontend/src/app/[locale]/legal/privacy/page.tsx` |
| `/legal/terms` | 2 | `frontend/src/app/[locale]/legal/terms/page.tsx` |
| `/link/[token]` | 145 | `frontend/src/app/[locale]/(dashboard)/link/[token]/page.tsx` |
| `/login` | 154 | `frontend/src/app/[locale]/(auth)/login/page.tsx` |
| `/magic-link-sent` | 0 | `frontend/src/app/[locale]/(auth)/magic-link-sent/page.tsx` |
| `/mcp-servers` | 172 | `frontend/src/app/[locale]/(dashboard)/mcp-servers/page.tsx` |
| `/oauth/consent` | 147 | `frontend/src/app/[locale]/(viewer)/oauth/consent/page.tsx` |
| `/onboarding` | 203 | `frontend/src/app/[locale]/onboarding/page.tsx` |
| `/onboarding/[...step]` | 0 | `frontend/src/app/[locale]/onboarding/[...step]/page.tsx` |
| `/orgs` | 165 | `frontend/src/app/[locale]/(dashboard)/orgs/page.tsx` |
| `/orgs/[id]/directory` | 149 | `frontend/src/app/[locale]/(dashboard)/orgs/[id]/directory/page.tsx` |
| `/orgs/[id]/groups` | 154 | `frontend/src/app/[locale]/(dashboard)/orgs/[id]/groups/page.tsx` |
| `/orgs/[id]/members` | 169 | `frontend/src/app/[locale]/(dashboard)/orgs/[id]/members/page.tsx` |
| `/orgs/[id]/retention` | 148 | `frontend/src/app/[locale]/(dashboard)/orgs/[id]/retention/page.tsx` |
| `/orgs/[id]/roles` | 147 | `frontend/src/app/[locale]/(dashboard)/orgs/[id]/roles/page.tsx` |
| `/profile` | 0 | `frontend/src/app/[locale]/(dashboard)/profile/page.tsx` |
| `/projects` | 153 | `frontend/src/app/[locale]/(dashboard)/projects/page.tsx` |
| `/projects/[id]` | 188 | `frontend/src/app/[locale]/(dashboard)/projects/[id]/page.tsx` |
| `/rag` | 178 | `frontend/src/app/[locale]/(dashboard)/rag/page.tsx` |
| `/rag/[id]` | 204 | `frontend/src/app/[locale]/(dashboard)/rag/[id]/page.tsx` |
| `/register` | 154 | `frontend/src/app/[locale]/(auth)/register/page.tsx` |
| `/remote-agents` | 149 | `frontend/src/app/[locale]/(dashboard)/remote-agents/page.tsx` |
| `/reset-password` | 146 | `frontend/src/app/[locale]/(auth)/reset-password/page.tsx` |
| `/routines` | 188 | `frontend/src/app/[locale]/(dashboard)/routines/page.tsx` |
| `/runs` | 195 | `frontend/src/app/[locale]/(dashboard)/runs/page.tsx` |
| `/sandboxes` | 154 | `frontend/src/app/[locale]/(dashboard)/sandboxes/page.tsx` |
| `/settings` | 0 | `frontend/src/app/[locale]/(dashboard)/settings/page.tsx` |
| `/settings/account` | 146 | `frontend/src/app/[locale]/(dashboard)/settings/account/page.tsx` |
| `/settings/api-keys` | 152 | `frontend/src/app/[locale]/(dashboard)/settings/api-keys/page.tsx` |
| `/settings/api-keys/reference` | 150 | `frontend/src/app/[locale]/(dashboard)/settings/api-keys/reference/page.tsx` |
| `/settings/assistant` | 148 | `frontend/src/app/[locale]/(dashboard)/settings/assistant/page.tsx` |
| `/settings/blobby` | 148 | `frontend/src/app/[locale]/(dashboard)/settings/blobby/page.tsx` |
| `/settings/desktop` | 151 | `frontend/src/app/[locale]/(dashboard)/settings/desktop/page.tsx` |
| `/settings/mcp` | 149 | `frontend/src/app/[locale]/(dashboard)/settings/mcp/page.tsx` |
| `/settings/memory` | 155 | `frontend/src/app/[locale]/(dashboard)/settings/memory/page.tsx` |
| `/settings/mobile` | 151 | `frontend/src/app/[locale]/(dashboard)/settings/mobile/page.tsx` |
| `/settings/notifications` | 155 | `frontend/src/app/[locale]/(dashboard)/settings/notifications/page.tsx` |
| `/settings/profile` | 155 | `frontend/src/app/[locale]/(dashboard)/settings/profile/page.tsx` |
| `/settings/shortcuts` | 146 | `frontend/src/app/[locale]/(dashboard)/settings/shortcuts/page.tsx` |
| `/settings/sign-ins` | 147 | `frontend/src/app/[locale]/(dashboard)/settings/sign-ins/page.tsx` |
| `/settings/slash-commands` | 146 | `frontend/src/app/[locale]/(dashboard)/settings/slash-commands/page.tsx` |
| `/shared/[token]` | 160 | `frontend/src/app/[locale]/shared/[token]/page.tsx` |
| `/skills` | 179 | `frontend/src/app/[locale]/(dashboard)/skills/page.tsx` |
| `/tables` | 172 | `frontend/src/app/[locale]/(dashboard)/tables/page.tsx` |
| `/tables/[id]` | 198 | `frontend/src/app/[locale]/(dashboard)/tables/[id]/page.tsx` |
| `/vault` | 161 | `frontend/src/app/[locale]/(dashboard)/vault/page.tsx` |
| `/work` | 157 | `frontend/src/app/[locale]/(dashboard)/work/page.tsx` |
| `/workflows` | 161 | `frontend/src/app/[locale]/(dashboard)/workflows/page.tsx` |
| `/workflows/[id]` | 276 | `frontend/src/app/[locale]/(dashboard)/workflows/[id]/page.tsx` |
| `/workflows/[id]/form-preview` | 150 | `frontend/src/app/[locale]/(dashboard)/workflows/[id]/form-preview/page.tsx` |
| `/workflows/[id]/logs` | 154 | `frontend/src/app/[locale]/(dashboard)/workflows/[id]/logs/page.tsx` |
| `/workflows/[id]/runs` | 155 | `frontend/src/app/[locale]/(dashboard)/workflows/[id]/runs/page.tsx` |
| `/workflows/[id]/runs/[runId]` | 268 | `frontend/src/app/[locale]/(dashboard)/workflows/[id]/runs/[runId]/page.tsx` |
| `/workflows/runs` | 150 | `frontend/src/app/[locale]/(dashboard)/workflows/runs/page.tsx` |

## Component families

| Family | Modules |
| --- | ---: |
| .. | 1 |
| admin | 15 |
| agents | 102 |
| artifacts | 29 |
| assistant | 9 |
| auth | 8 |
| authoring | 24 |
| branding | 5 |
| browser | 2 |
| channels | 12 |
| charts | 1 |
| chat | 133 |
| context | 4 |
| dashboard | 99 |
| datasets | 56 |
| desktop | 27 |
| evals | 36 |
| files | 9 |
| groups | 6 |
| hosted | 1 |
| icons | 4 |
| improvement | 33 |
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
| settings | 28 |
| shared | 1 |
| sharing | 10 |
| skills | 7 |
| states | 6 |
| tables | 40 |
| tasks | 3 |
| teams | 15 |
| theme | 5 |
| triggers | 32 |
| ui | 61 |
| vault | 9 |
| voice | 12 |
| watches | 4 |
| workflows | 98 |

The JSON companion stores the complete local module import graph. Numeric references index `modules[]`; routes identify their page and layout modules, and families identify every component module. Following imports reconstructs each route’s dependencies without duplicating paths.
