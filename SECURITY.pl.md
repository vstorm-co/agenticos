---
source_sha: "5bb89334b619"
---

<!-- source_sha: 49074c4c262a -->

# Bezpieczeństwo

[English](SECURITY.md) · **Polski** · [Deutsch](SECURITY.de.md) · [Español](SECURITY.es.md)

> [!IMPORTANT]
> Tekst angielski jest tym rozstrzygającym. Tłumaczenie jest udogodnieniem i tam,
> gdzie oba się różnią, zgłoś podatność w oparciu o to, co mówi tekst angielski.

## Zgłaszanie podatności

E-mail: **kacper.wlodarczyk@vstorm.co** (albo załóż prywatne security advisory w repozytorium). Dołącz:

- Wersję / commit, którego to dotyczy
- Kroki do odtworzenia
- Ocenę wpływu (ujawnienie danych / eskalacja uprawnień / DoS / …)

Celujemy w potwierdzenie w ciągu 48h i wypuszczenie poprawki w ciągu 7 dni dla problemów o wysokiej istotności.

---

## Model bezpieczeństwa

### Uwierzytelnianie
- **JWT (`HS256`)** podpisywany `SECRET_KEY`. TTL access tokena = `ACCESS_TOKEN_EXPIRE_MINUTES` (domyślnie 30 min). TTL refresh tokena = `REFRESH_TOKEN_EXPIRE_MINUTES` (domyślnie 7 dni).
- **Haszowanie haseł:** bcrypt przez `passlib`. Hasła w postaci jawnej nigdy nie są zapisywane.
- **OAuth 2.0 (Google)** — flow z kodem autoryzacyjnym. Token walidowany po stronie serwera, wewnętrzny rekord użytkownika wyszukiwany/tworzony po adresie e-mail.
- **Zarządzanie sesjami** — sesje oparte o bazę danych, z unieważnianiem. Każde wydanie refresh tokena tworzy wiersz sesji; endpoint `/sessions` pozwala użytkownikom zobaczyć i unieważnić urządzenia.
- **Administracyjny klucz API** — statyczne `settings.API_KEY` dopasowywane nagłówkiem `X-API-Key` przy wywołaniach między usługami. Porównywane w stałym czasie przez `secrets.compare_digest()`.

### Autoryzacja

- **Oparta o uprawnienia** — władza wewnątrz organizacji to wiersz członkostwa plus katalog uprawnień (`app/core/permissions.py`). Nie ma kolumny z rolą na użytkowniku ani zależności route'u opartej o rolę.
- **Role w organizacji** — rola to nazwa na członkostwie (`owner` / `admin` / `builder` / `operator` / `member` / `viewer`), która mapuje się na zestaw uprawnień. Route'y kolekcji bramkują na uprawnieniu; dostęp do pojedynczego zasobu rozstrzyga rolę razem z jawnymi grantami, a grant poszerza to, na co rola pozwala — nigdy tego nie zawęża. Zobacz [Uprawnienia](docs/permissions.pl.md).
- **Zakres workspace'u** — każde uwierzytelnione żądanie rozstrzyga `ActiveOrg` (domyślnie = organizacja osobista). Zasoby są ograniczone kluczem obcym `organization_id`.
- **Administracja wdrożeniem** — flaga `is_app_admin` na użytkowniku, sprawdzana własną zależnością; nie rola.

### Transport / sieć

- **CORS** — lista originów z `settings.CORS_ORIGINS`. Na produkcji ogranicz ją do swoich domen.
- **HTTPS** — wymuszaj przez reverse proxy (Nginx / Traefik / ALB). Nagłówek Strict-Transport-Security ustawiany w middleware, gdy `ENVIRONMENT=production`.
- **Nagłówki bezpieczeństwa** — frontend serwuje pełne Content-Security-Policy (`default-src 'self'`, `connect-src` wymieniające wyłącznie ten origin oraz skonfigurowane `PUBLIC_API_URL` i `PUBLIC_WS_URL`, `object-src 'none'`, `base-uri 'self'`, `frame-ancestors 'none'`) plus `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin` i `Permissions-Policy`, które odmawia kamery i geolokalizacji, a mikrofon dopuszcza wyłącznie do speech-to-text. Polityka mieszka w `frontend/src/lib/csp.ts`, a nagłówki w `frontend/src/lib/security-headers.ts`; jedne i drugie są potwierdzone testami — zobacz [Wdrożenie](docs/deployment.pl.md#security-headers).

### Dane

- **Sekrety** — czytane ze środowiska przez `pydantic-settings`. Nigdy nie commitowane. Zobacz `backend/.env.example` oraz [Konfigurację](docs/configuration.pl.md).
- **Log audytu** — działania administratora aplikacji (aktualizacje użytkowników, usunięcia, impersonacje) zapisywane w tabeli `app_admin_audit_logs` wraz z aktorem, IP i migawką ładunku. Działania na poziomie organizacji, które zmieniają dostęp albo wydają pieniądze, mają własny ślad, bramkowany uprawnieniem `audit:read` — zobacz [Governance](docs/governance.pl.md).
- **Dokumenty RAG** — wgrane pliki są ograniczone do organizacji. Nie ma publicznego endpointu do odczytu; całe wyszukiwanie odbywa się po stronie serwera w trakcie czatu.
- **Dane osobowe** — gdzie leżą, co opuszcza wdrożenie i przy jakim ustawieniu, co obejmuje usunięcie, a czego nie obejmuje, z nazwanymi otwartymi lukami: [Ochrona danych](docs/data-protection.pl.md).

### Lista kontrolna hardeningu na produkcję

- [ ] Zrotuj `SECRET_KEY` i `API_KEY` z wygenerowanych wartości domyślnych.
- [ ] Ustaw `DEBUG=false` i `ENVIRONMENT=production`.
- [ ] Ogranicz `CORS_ORIGINS` do swojej domeny (lub domen).
- [ ] Dostrój `RATE_LIMIT_RUN_PER_MINUTE` / `RATE_LIMIT_EMBED_PER_MINUTE` w `.env`.
- [ ] Przejrzyj limity zapytań na każdej publicznej powierzchni — limit
      wiadomości na odwiedzającego w widgecie embed oraz `rate_limit_rpm` na
      nadawcę w każdym bocie kanału. Własne route'y konsoli nie są mierzone.
- [ ] Za proxy albo CDN-em ustaw `RATE_LIMIT_TRUST_FORWARDED_FOR=true` **oraz**
      upewnij się, że API nie jest jednocześnie osiągalne bezpośrednio — inaczej
      wszyscy odwiedzający dzielą jeden kubełek albo nagłówek da się podrobić.
      Limiter czyta skrajnie prawy hop `X-Forwarded-For` (ten, który dopisało
      Twoje proxy), więc postaw z przodu dokładnie jedno zaufane proxy; przy
      dwóch zwiń nagłówek do jednego hopa na swoim brzegu.
- [ ] Wymuś HTTPS na warstwie proxy.
- [ ] Uruchamiaj w CI `pip-audit` / `bun audit` pod kątem podatności w zależnościach.
- [ ] Skonfiguruj kopie zapasowe bazy danych i harmonogram testów odtwarzania.

## Znane ograniczenia

- **Brak 2FA / MFA** od ręki.
- **Brak SAML / OIDC** poza Google OAuth. Enterprise SSO wymaga własnej integracji z IdP.
- **Brak automatycznego maskowania PII** w logach — uważaj, co logujesz.
