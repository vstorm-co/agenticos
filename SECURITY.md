# Security

**English** · [Polski](SECURITY.pl.md) · [Deutsch](SECURITY.de.md) · [Español](SECURITY.es.md)

> [!IMPORTANT]
> The English text is the authoritative one. A translation is a convenience, and
> where the two disagree, report the vulnerability against what this file says.

## Reporting a vulnerability

Email: **kacper.wlodarczyk@vstorm.co** (or open a private security advisory on the repo). Please include:

- Affected version / commit
- Steps to reproduce
- Impact assessment (data exposure / privilege escalation / DoS / …)

We aim to acknowledge within 48h and ship a fix within 7 days for high-severity issues.

---

## Security model

The threat model, the data-flow statement (what leaves the deployment and to
whom), what is encrypted where, and the controls matrix — each control mapped to
the mechanism that satisfies it and the test that holds it true — live in one
copy on the [Security](https://vstorm-co.github.io/agenticos/security/) page
(`docs/security.md`). This file keeps only the two things a repository's
`SECURITY.md` is read for: how to report a vulnerability, above, and the
production hardening checklist, below. Where personal data lives and what a
deletion reaches is [Data protection](docs/data-protection.md); the components
the images ship and their licences are [Licences](docs/licenses.md).

## Hardening checklist for production

- [ ] Rotate `SECRET_KEY` and `API_KEY` from generated defaults.
- [ ] Set `DEBUG=false` and `ENVIRONMENT=production`.
- [ ] Restrict `CORS_ORIGINS` to your domain(s).
- [ ] Tune `RATE_LIMIT_RUN_PER_MINUTE` / `RATE_LIMIT_EMBED_PER_MINUTE` in `.env`.
- [ ] Review the rate limits on every public surface — the embed widget's
      messages-per-visitor limit and each channel bot's per-sender
      `rate_limit_rpm`. The console's own routes are not metered.
- [ ] Behind a proxy or CDN, set `RATE_LIMIT_TRUST_FORWARDED_FOR=true` **and**
      make sure the API is not also reachable directly — otherwise every
      visitor shares one bucket, or the header can be forged. The limiter reads
      the rightmost `X-Forwarded-For` hop (the one your proxy appended), so put
      exactly one trusted proxy in front; with two, collapse the header to a
      single hop at your edge.
- [ ] Enforce HTTPS at the proxy layer.
- [ ] Run `pip-audit` / `bun audit` in CI for dependency vulnerabilities.
- [ ] Configure database backups + restore test schedule.

## Known limitations

- **No 2FA / MFA** out of the box.
- **No SAML / OIDC** beyond Google OAuth. Enterprise SSO needs custom IdP integration.
- **No automatic PII redaction** in logs — be careful what you log.
