# Security

## Reporting a vulnerability

Email: **kacper.wlodarczyk@vstorm.co** (or open a private security advisory on the repo). Please include:

- Affected version / commit
- Steps to reproduce
- Impact assessment (data exposure / privilege escalation / DoS / …)

We aim to acknowledge within 48h and ship a fix within 7 days for high-severity issues.

---

## Security model

### Authentication
- **JWT (`HS256`)** signed with `SECRET_KEY`. Access token TTL = `ACCESS_TOKEN_EXPIRE_MINUTES` (default 30 min). Refresh token TTL = `REFRESH_TOKEN_EXPIRE_MINUTES` (default 7 days).
- **Password hashing:** bcrypt via `passlib`. Plain passwords never persisted.
- **OAuth 2.0 (Google)** — auth-code flow. Token validated server-side, internal user record looked up/created by email.
- **Session management** — DB-backed sessions with revocation. Each refresh-token issuance creates a session row; `/sessions` endpoint lets users see + revoke devices.
- **Admin API key** — static `settings.API_KEY` matched via `X-API-Key` header for service-to-service calls. Constant-time compared with `secrets.compare_digest()`.

### Authorization

- **Permission-based** — authority inside an organization is a membership row plus the permission catalog (`app/core/permissions.py`). There is no role column on the user and no role-based route dependency.
- **Org roles** — a role is a name on the membership (`owner` / `admin` / `builder` / `operator` / `member` / `viewer`) that maps to a set of permissions. Collection routes gate on a permission; per-resource access resolves the role together with explicit grants, and a grant widens what a role allows — it never narrows it. See [Permissions](docs/permissions.md).
- **Workspace scope** — every authenticated request resolves an `ActiveOrg` (default = personal org). Resources scoped by `organization_id` foreign key.
- **Deployment administration** — the `is_app_admin` flag on a user, checked by its own dependency; not a role.

### Transport / network

- **CORS** — origin list from `settings.CORS_ORIGINS`. Restrict to your domains in production.
- **HTTPS** — enforce via reverse proxy (Nginx / Traefik / ALB). Strict-Transport-Security header set in middleware when `ENVIRONMENT=production`.
- **CSP** — frontend sets `frame-ancestors 'none'` by default to prevent click-jacking. See `frontend/next.config.ts` headers block.

### Data

- **Secrets** — read from environment via `pydantic-settings`. Never committed. See `backend/.env.example` and [Configuration](docs/configuration.md).
- **Audit log** — app-admin actions (user updates, deletes, impersonations) recorded in the `app_admin_audit_logs` table with actor + IP + payload snapshot. Organization-level actions that change access or spend money carry their own trail, gated by `audit:read` — see [Governance](docs/governance.md).
- **RAG documents** — file uploads scoped per-org. No public read endpoint; all retrieval happens server-side during chat.

### Hardening checklist for production

- [ ] Rotate `SECRET_KEY` and `API_KEY` from generated defaults.
- [ ] Set `DEBUG=false` and `ENVIRONMENT=production`.
- [ ] Restrict `CORS_ORIGINS` to your domain(s).
- [ ] Review the rate limits on every public surface — the embed widget's messages-per-visitor limit and each channel bot's per-sender `rate_limit_rpm`. The console's own routes are not metered.
- [ ] Enforce HTTPS at the proxy layer.
- [ ] Run `pip-audit` / `bun audit` in CI for dependency vulnerabilities.
- [ ] Configure database backups + restore test schedule.

## Known limitations

- **No 2FA / MFA** out of the box.
- **No SAML / OIDC** beyond Google OAuth. Enterprise SSO needs custom IdP integration.
- **No automatic PII redaction** in logs — be careful what you log.
