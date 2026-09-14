---
source_sha: "5bb89334b619"
---

<!-- source_sha: 49074c4c262a -->

# Sicherheit

[English](SECURITY.md) · [Polski](SECURITY.pl.md) · **Deutsch** · [Español](SECURITY.es.md)

> [!IMPORTANT]
> Der englische Text ist der maßgebliche. Eine Übersetzung ist eine
> Annehmlichkeit, und wo die beiden voneinander abweichen, melden Sie die
> Schwachstelle gegen das, was der englische Text sagt.

## Eine Schwachstelle melden

E-Mail: **kacper.wlodarczyk@vstorm.co** (oder eröffnen Sie ein privates Security Advisory im Repo). Bitte geben Sie an:

- Betroffene Version / betroffener Commit
- Schritte zur Reproduktion
- Einschätzung der Auswirkung (Datenoffenlegung / Rechteausweitung / DoS / …)

Wir streben an, innerhalb von 48h zu bestätigen und bei Problemen hoher Schwere innerhalb von 7 Tagen einen Fix auszuliefern.

---

## Das Sicherheitsmodell

### Authentifizierung
- **JWT (`HS256`)**, signiert mit `SECRET_KEY`. TTL des Access Tokens = `ACCESS_TOKEN_EXPIRE_MINUTES` (Standard 30 min). TTL des Refresh Tokens = `REFRESH_TOKEN_EXPIRE_MINUTES` (Standard 7 Tage).
- **Passwort-Hashing:** bcrypt über `passlib`. Klartext-Passwörter werden nie gespeichert.
- **OAuth 2.0 (Google)** — Auth-Code-Flow. Das Token wird serverseitig validiert, der interne Benutzerdatensatz wird per E-Mail nachgeschlagen bzw. angelegt.
- **Session-Verwaltung** — Sessions in der Datenbank, mit Widerruf. Jede Ausgabe eines Refresh Tokens legt eine Session-Zeile an; der Endpunkt `/sessions` lässt Benutzer ihre Geräte sehen und widerrufen.
- **Admin-API-Key** — statischer `settings.API_KEY`, für Service-zu-Service-Aufrufe über den Header `X-API-Key` abgeglichen. Der Vergleich läuft in konstanter Zeit mit `secrets.compare_digest()`.

### Autorisierung

- **Permission-basiert** — die Autorität innerhalb einer Organisation ist eine Membership-Zeile plus der Permission-Katalog (`app/core/permissions.py`). Es gibt keine Rollenspalte am Benutzer und keine rollenbasierte Route-Dependency.
- **Org-Rollen** — eine Rolle ist ein Name auf der Membership (`owner` / `admin` / `builder` / `operator` / `member` / `viewer`), der auf eine Menge von Permissions abbildet. Collection-Routen gaten auf eine Permission; der Zugriff je Ressource löst die Rolle zusammen mit expliziten Grants auf, und ein Grant erweitert, was eine Rolle erlaubt — er schränkt es nie ein. Siehe [Berechtigungen](docs/permissions.de.md).
- **Workspace-Scope** — jede authentifizierte Anfrage löst eine `ActiveOrg` auf (Standard = persönliche Org). Ressourcen sind über den Fremdschlüssel `organization_id` gescoped.
- **Administration des Deployments** — das Flag `is_app_admin` am Benutzer, von einer eigenen Dependency geprüft; keine Rolle.

### Transport / Netzwerk

- **CORS** — Origin-Liste aus `settings.CORS_ORIGINS`. Schränken Sie sie in der Produktion auf Ihre Domains ein.
- **HTTPS** — über einen Reverse Proxy erzwingen (Nginx / Traefik / ALB). Der Strict-Transport-Security-Header wird in der Middleware gesetzt, wenn `ENVIRONMENT=production` gilt.
- **Security-Header** — das Frontend liefert eine vollständige Content-Security-Policy aus (`default-src 'self'`, ein `connect-src`, das nur diesen Origin und die konfigurierten `PUBLIC_API_URL` und `PUBLIC_WS_URL` nennt, `object-src 'none'`, `base-uri 'self'`, `frame-ancestors 'none'`) sowie `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin` und eine `Permissions-Policy`, die Kamera und Geolocation verweigert und das Mikrofon nur für Speech-to-Text erlaubt. Die Policy liegt in `frontend/src/lib/csp.ts` und die Header in `frontend/src/lib/security-headers.ts`, beide durch Tests abgesichert; siehe [Deployment](docs/deployment.de.md#security-headers).

### Daten

- **Secrets** — über `pydantic-settings` aus der Umgebung gelesen. Nie eingecheckt. Siehe `backend/.env.example` und [Konfiguration](docs/configuration.de.md).
- **Audit-Log** — App-Admin-Aktionen (Benutzeränderungen, Löschungen, Impersonationen) werden in der Tabelle `app_admin_audit_logs` mit Akteur + IP + Payload-Schnappschuss festgehalten. Aktionen auf Organisationsebene, die Zugriff ändern oder Geld ausgeben, haben ihre eigene Spur, gegatet durch `audit:read` — siehe [Governance](docs/governance.de.md).
- **RAG-Dokumente** — Datei-Uploads sind je Org gescoped. Kein öffentlicher Lese-Endpunkt; das gesamte Retrieval passiert serverseitig während des Chats.
- **Personenbezogene Daten** — wo sie liegen, was das Deployment verlässt und unter welcher Einstellung, was das Löschen erreicht und was nicht, mit den offenen Lücken beim Namen genannt: [Datenschutz](docs/data-protection.de.md).

### Härtungs-Checkliste für die Produktion

- [ ] `SECRET_KEY` und `API_KEY` gegenüber den generierten Standardwerten rotieren.
- [ ] `DEBUG=false` und `ENVIRONMENT=production` setzen.
- [ ] `CORS_ORIGINS` auf Ihre Domain(s) einschränken.
- [ ] `RATE_LIMIT_RUN_PER_MINUTE` / `RATE_LIMIT_EMBED_PER_MINUTE` in `.env` justieren.
- [ ] Die Rate Limits auf jeder öffentlichen Oberfläche prüfen — das Limit an
      Nachrichten je Besucher beim Embed-Widget und das `rate_limit_rpm` je
      Absender bei jedem Channel-Bot. Die Routen der Konsole selbst werden nicht
      gemessen.
- [ ] Hinter einem Proxy oder CDN `RATE_LIMIT_TRUST_FORWARDED_FOR=true` setzen
      **und** sicherstellen, dass die API nicht zusätzlich direkt erreichbar ist
      — sonst teilen sich alle Besucher einen Bucket, oder der Header lässt sich
      fälschen. Der Limiter liest den am weitesten rechts stehenden
      `X-Forwarded-For`-Hop (den, den Ihr Proxy angehängt hat), setzen Sie also
      genau einen vertrauenswürdigen Proxy davor; bei zweien fassen Sie den
      Header an Ihrem Edge zu einem einzigen Hop zusammen.
- [ ] HTTPS auf der Proxy-Ebene erzwingen.
- [ ] `pip-audit` / `bun audit` in der CI auf Schwachstellen in Abhängigkeiten laufen lassen.
- [ ] Datenbank-Backups + einen Zeitplan für Restore-Tests einrichten.

## Bekannte Einschränkungen

- **Kein 2FA / MFA** ab Werk.
- **Kein SAML / OIDC** über Google OAuth hinaus. Enterprise-SSO braucht eine eigene IdP-Integration.
- **Keine automatische PII-Schwärzung** in Logs — achten Sie darauf, was Sie loggen.
