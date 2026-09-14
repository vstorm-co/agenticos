<!-- source_sha: c911383112ac -->

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

Das Bedrohungsmodell, die Datenfluss-Erklärung (was das Deployment verlässt und
an wen), was wo verschlüsselt ist, und die Kontrollmatrix — jede Kontrolle auf den
Mechanismus abgebildet, der sie erfüllt, und auf den Test, der sie hält — stehen
in einer einzigen Kopie auf der Seite
[Sicherheit](https://vstorm-co.github.io/agenticos/security/) (`docs/security.md`).
Diese Datei behält nur die zwei Dinge, für die man die `SECURITY.md` eines
Repositorys liest: wie man eine Schwachstelle meldet, oben, und die
Härtungs-Checkliste für die Produktion, unten. Wo personenbezogene Daten liegen
und was eine Löschung erreicht, steht in
[Datenschutz](docs/data-protection.de.md); die Komponenten, die die Images
ausliefern, und ihre Lizenzen in [Lizenzen](docs/licenses.de.md).

## Härtungs-Checkliste für die Produktion

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
