<!-- source_sha: c911383112ac -->

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

Model zagrożeń, opis przepływu danych (co opuszcza wdrożenie i do kogo), co jest
gdzie szyfrowane oraz macierz kontroli — każda kontrola zmapowana na mechanizm,
który ją realizuje, i na test, który trzyma ją w mocy — żyją w jednej kopii na
stronie [Bezpieczeństwo](https://vstorm-co.github.io/agenticos/security/)
(`docs/security.md`). Ten plik zostawia tylko dwie rzeczy, po które sięga się do
`SECURITY.md` w repozytorium: jak zgłosić podatność, powyżej, i produkcyjną listę
kontrolną hardeningu, poniżej. Gdzie leżą dane osobowe i co obejmuje usunięcie,
opisuje [Ochrona danych](docs/data-protection.pl.md); komponenty, które wiozą
obrazy, i ich licencje — [Licencje](docs/licenses.pl.md).

## Lista kontrolna hardeningu na produkcję

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
