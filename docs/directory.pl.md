---
source_sha: "786dab540111"
---

# Logowanie katalogowe i grupy { #directory-sign-in-and-groups }

Firma, która prowadzi Active Directory, OpenLDAP albo FreeIPA, już wie, kto w niej
pracuje i do jakich zespołów należy. Ta strona opisuje trzy sposoby, na jakie
AgenticOS może z tej wiedzy skorzystać. Ludzie mogą logować się kontem
katalogowym. Przeglądarka na komputerze w domenie może zalogować ich biletem
Kerberos. A grupy katalogowe mogą decydować, do których organizacji ludzie
dołączają, z jaką rolą i w jakich grupach się znajdują.

Składają się na to trzy elementy, działające niezależnie od siebie:

| Element | Co robi | Kto konfiguruje |
|---|---|---|
| [Grupy](#groups) | Nazwane zbiory członków organizacji, którym można udostępnić zasób | Członkowie z `members:manage`, w konsoli |
| [Mapowania grup katalogowych](#directory-group-mappings) | „Każdy w tej grupie katalogowej dołącza z tą rolą, do tej grupy” | Członkowie z `members:manage` i `roles:manage` |
| [Logowanie katalogowe](#signing-in-with-a-directory-account) | Logowanie hasłem przez LDAP i logowanie Kerberos (SPNEGO) | Operator, w `backend/.env` |

Mapowania dotyczą także ludzi, którzy logują się przez
[OIDC](configuration.md#single-sign-on-generic-oidc), jeśli dostawca tożsamości
podaje ich grupy. Jeśli twoja firma już ma Keycloak albo Entra ID przed swoim
katalogiem, natywne logowanie LDAP może w ogóle nie być potrzebne. Zobacz
[Zamiast tego przez dostawcę tożsamości](#through-an-identity-provider-instead).

## Grupy { #groups }

Grupa to nazwany zbiór członków w obrębie jednej organizacji: *Finance*,
*Support team*, *Platform admins*. Agenta, skill, kolekcję, plik kontekstu,
sekret w vault albo artefakt udostępniasz grupie tak samo jak osobie, z panelu
**Sharing** danego zasobu. Jeden grant sięga wtedy do każdego w grupie.

Grant dla grupy sięga do tego, kto jest w grupie **w chwili sprawdzania
dostępu**. Ktoś, kto dołączy do grupy w przyszłym miesiącu, dostaje dostęp do
zasobu; ktoś, kto z niej odejdzie, go traci. Nie ma niczego do odbierania osobno
każdej osobie.

Grupa nie niesie żadnej roli. To, co członek może robić w organizacji, nadal
wynika z roli jego członkostwa, a grupa dodaje jedynie granty, które jej nadano.
Efektywny dostęp pozostaje regułą opisaną w
[Uprawnieniach](permissions.md#how-the-layers-combine):

```
effective access to one row = max(role scope, the person's grant, their groups' grants)
```

Gdy osoba sięga do wiersza przez kilka grantów, wygrywa najwyższy poziom. Odczyt
przez własny grant i edycja przez grant grupy daje edycję.

| Czynność | Kto może |
|---|---|
| Listować grupy i widzieć, kto w nich jest | Każdy członek organizacji |
| Utworzyć grupę, zmienić jej nazwę albo ją usunąć; dodawać i usuwać ludzi | `members:manage` |
| Udostępnić zasób grupie | Każdy, kto może edytować ten zasób |

Grupy znajdują się w **Organizations → Members → Groups**. Dodać można tylko
członków organizacji, a usunięcie kogoś z organizacji usuwa go ze wszystkich jej
grup. Usunięcie grupy usuwa każdy nadany jej grant i każde mapowanie katalogowe,
które ją wskazuje.

## Mapowania grup katalogowych { #directory-group-mappings }

Mapowanie mówi, co jedna grupa katalogowa znaczy w obrębie jednej organizacji:

> Każdy w `CN=Finance,OU=Groups,DC=corp,DC=example,DC=com` jest tutaj
> **członkiem** (member) i należy do grupy **Finance**.

Mapowania znajdują się w **Organizations → Members → Directory**. Ich odczyt
wymaga `members:manage`. Utworzenie albo usunięcie mapowania wymaga
`members:manage` i `roles:manage`, bo mapowanie jednocześnie wpuszcza ludzi i
nadaje im rolę.

Rola jest ograniczona tak samo jak rola w zaproszeniu. Grupę katalogową możesz
zmapować tylko na rolę, którą twoja własna rola ściśle przewyższa. Nikt nie może
zmapować grupy na `owner`, a Admin nie może zmapować grupy na Admina. Usunięcie
mapowania wymaga tej samej władzy, bo degraduje każdego, kogo ono umieściło.

### Co się dzieje przy logowaniu { #what-happens-at-sign-in }

Za każdym razem, gdy ktoś loguje się przez LDAP, przez Kerberos albo przez OIDC
z ustawionym [`OIDC_GROUPS_CLAIM`](#the-groups-claim-over-oidc), jego grupy
katalogowe są porównywane z mapowaniami każdej organizacji:

1. **Do organizacji z pasującym mapowaniem** osoba dołącza, jeśli jeszcze nie
   jest członkiem, ze zmapowaną rolą. Członkostwo jest oznaczone jako
   **directory**.
2. **Członkostwo katalogowe** ma rolę aktualizowaną zgodnie z mapowaniami.
3. **Osoba dołącza do zmapowanych grup** i opuszcza te utworzone przez katalog
   członkostwa w grupach, których żadne mapowanie już nie wskazuje.
4. **Członkostwo katalogowe, do którego nie pasuje już żadne mapowanie**, jest
   usuwane razem z członkostwami tej osoby w grupach tej organizacji.

Grupy są porównywane bez względu na wielkość liter i otaczające spacje, bo każdy
katalog porównuje je w ten sposób.

Gdy w jednej organizacji pasuje kilka mapowań, rolą jest pierwsza z poniższych,
którą wskazuje którekolwiek z nich:

**admin → builder → operator → member → viewer**

Role nie układają się w jedną linię władzy. Builder i operator mają każdy coś,
czego drugi nie ma, więc kolejność jest tu podana wprost, a nie wyliczana.

### Czego synchronizacja nigdy nie dotyka { #what-the-sync-never-touches }

Synchronizacja zmienia tylko wiersze, które sama utworzyła. Wynikają z tego
cztery reguły:

- **Członkostwo utworzone przez administratora zachowuje swoją rolę.** Ktoś
  zaproszony ręcznie zachowuje nadaną mu rolę, nawet jeśli pasuje do niego
  mapowanie. Nadal dołącza do zmapowanych grup.
- **Ręczna zmiana roli członka katalogowego przejmuje członkostwo.** Staje się
  ono członkostwem ręcznym i kolejne logowania nie ruszają już jego roli.
- **Członkostwo w grupie dodane ręcznie zostaje**, nawet gdy katalog wyjąłby
  osobę z tej grupy.
- **Owner nigdy nie jest degradowany ani usuwany** i żadne mapowanie nie może
  nikogo ownerem uczynić. Własność przechodzi wyłącznie przez **Transfer
  ownership**.

Do organizacji osobistej nigdy nie dołącza się przez mapowanie i nie można dla
niej utworzyć mapowania.

!!! warning "Usunięcie mapowania usuwa ludzi, których ono umieściło"

    Usunięcie następuje przy **następnym logowaniu** każdej osoby, a nie od razu.
    Żeby zatrzymać kogoś po usunięciu mapowania, które go wprowadziło, najpierw
    zmień jego rolę ręcznie. To przejmuje członkostwo.

### Mapowania wpuszczają nowe konta { #mappings-admit-new-accounts }

Mapowanie liczy się jako zaproszenie. Na wdrożeniu `invite_only` albo takim z
listą dozwolonych domen pierwsze logowanie, którego grupy pasują do mapowania
dowolnej organizacji, tworzy konto. Ktoś, kto trzyma zarówno `members:manage`,
jak i `roles:manage`, zdecydował, że każdy w tej grupie tu należy. Wdrożenie
`closed` nadal takie logowanie odrzuca. Zobacz
[Kto może się zarejestrować](deployment.md#who-may-register).

## Logowanie kontem katalogowym { #signing-in-with-a-directory-account }

Ustaw `LDAP_URL`, a strona logowania pokaże formularz katalogowy. Ludzie wpisują
nazwę użytkownika, której używają wszędzie indziej, i swoje hasło katalogowe.
AgenticOS sprawdza hasło standardowym dwuetapowym bindem:

1. Przeszukuje `LDAP_USER_BASE_DN` filtrem `LDAP_USER_FILTER`, używając konta
   serwisowego (`LDAP_BIND_DN`), w poszukiwaniu dokładnie jednego konta
   pasującego do nazwy użytkownika.
2. Wykonuje bind **jako to konto** z wpisanym hasłem. Hasło sprawdza wyłącznie
   katalog. Nie jest tutaj przechowywane, hashowane ani logowane.

Konto jest kluczowane po stabilnym identyfikatorze samego katalogu:
`LDAP_ID_ATTRIBUTE`, czyli `objectGUID` w Active Directory i `entryUUID` w
OpenLDAP i FreeIPA. Nie jest kluczowane po adresie, więc osoba, której zmieniono
nazwę, zachowuje swoją historię. Przy pierwszym logowaniu konto jest tworzone
zgodnie z [polityką rejestracji](deployment.md#who-may-register), a istniejące
konto z tym samym adresem jest z nim łączone.

```bash
# backend/.env - Active Directory over LDAPS
LDAP_URL=ldaps://dc01.corp.example.com
LDAP_CA_CERT_FILE=/etc/ssl/certs/corp-ca.pem
LDAP_BIND_DN=CN=agenticos,OU=Service Accounts,DC=corp,DC=example,DC=com
LDAP_BIND_PASSWORD=...
LDAP_USER_BASE_DN=OU=Staff,DC=corp,DC=example,DC=com
LDAP_ID_ATTRIBUTE=objectGUID
```

```bash
# frontend - show the form on the sign-in page
OAUTH_PROVIDERS=ldap
LDAP_DISPLAY_NAME=Active Directory
```

Każde ustawienie i jego wartość domyślna są w
[Konfiguracji](configuration.md#directory-sign-in-ldap).

### Czego logowanie odmawia { #what-the-sign-in-refuses }

| Odrzucane | Dlaczego |
|---|---|
| Puste hasło | Bind LDAP z nazwą i bez hasła to bind *nieuwierzytelniony*, który wiele serwerów akceptuje (RFC 4513). Nigdy nie dociera do katalogu |
| Dwa konta pasujące do jednej nazwy użytkownika | Bind jako to, które wróciło pierwsze, mógłby zalogować jedną osobę jako inną |
| Nazwa użytkownika zawierająca składnię filtra | Jest escapowana (RFC 4515), więc `*` nie znajduje nikogo zamiast wszystkich |
| Konto bez adresu albo bez identyfikatora | Konto, zaproszenie i polityka rejestracji są kluczowane właśnie po nich |
| `ldap://` bez StartTLS | Wysyła każde hasło otwartym tekstem. Proces odmawia startu, chyba że `LDAP_ALLOW_PLAINTEXT=true` mówi, że to celowe |

Błędna nazwa użytkownika i błędne hasło dostają tę samą odpowiedź. Katalog, który
nie działa, odrzucone konto serwisowe i wyszukiwanie, na które katalog nie umiał
odpowiedzieć (na przykład błędny base DN), są zgłaszane jako niedostępność
katalogu. Nie są zgłaszane jako błędne hasło, co wysłałoby każdą osobę w firmie do
resetowania swojego.

Certyfikat jest weryfikowany względem systemowego magazynu zaufanych certyfikatów
albo względem `LDAP_CA_CERT_FILE` dla firmowego CA — i tak samo nazwa hosta.
Logowanie ma limit żądań na adres i na nazwę użytkownika, tak jak logowanie
hasłem.

### Grupy z katalogu { #groups-from-the-directory }

Domyślnie grupami osoby są DN-y z jej atrybutu `memberOf`. Katalog bez `memberOf`
można zamiast tego przeszukać: ustaw `LDAP_GROUP_BASE_DN` oraz `LDAP_GROUP_FILTER`
z `{dn}` albo `{username}` w środku. Dla zagnieżdżonych grup Active Directory
szukaj z regułą dopasowania, która podąża za łańcuchem:

```bash
LDAP_GROUP_BASE_DN=OU=Groups,DC=corp,DC=example,DC=com
LDAP_GROUP_FILTER=(member:1.2.840.113556.1.4.1941:={dn})
```

Żeby w ogóle logować się mogła tylko jedna grupa, umieść ją w `LDAP_USER_FILTER`:
`(&(objectClass=user)(sAMAccountName={username})(memberOf=CN=AgenticOS Users,OU=Groups,DC=corp,DC=example,DC=com))`.

## Zintegrowane logowanie Windows (Kerberos) { #integrated-windows-sign-in-kerberos }

Na komputerze w domenie przeglądarka skierowana na host, któremu ufa jej polityka,
odpowiada na `WWW-Authenticate: Negotiate` biletem Kerberos. Przy
`KERBEROS_ENABLED=true` strona logowania pokazuje przycisk, który loguje osobę tym
biletem, i nikt nie wpisuje hasła.

Bilet wskazuje principal, `jane@CORP.EXAMPLE.COM`. AgenticOS rozwiązuje go przez
opisany wyżej katalog, filtrem `LDAP_KERBEROS_FILTER`
(domyślnie `(userPrincipalName={principal})`), do **tego samego konta**, do
którego prowadzi logowanie hasłem LDAP. Kerberos wymaga więc również `LDAP_URL`,
a katalog decyduje o adresie i grupach w ten sam sposób dla obu.

Czego to wymaga:

1. **Obrazu zbudowanego z extra `kerberos`.** `gssapi` kompiluje się względem
   systemowych bibliotek Kerberos, więc nie ma go w domyślnym obrazie:
   `docker build --build-arg EXTRAS="--extra kerberos" -f backend/Dockerfile .`
2. **Service principala i jego keytabu.** W Active Directory utwórz konto
   serwisowe, nadaj mu SPN `HTTP/agenticos.corp.example.com` i wyeksportuj keytab
   przez `ktpass`. Zamontuj go w kontenerze backendu.
3. **Ustawień backendu.**

    ```bash
    KERBEROS_ENABLED=true
    KERBEROS_KEYTAB=/etc/agenticos/http.keytab
    KERBEROS_SERVICE_PRINCIPAL=HTTP/agenticos.corp.example.com@CORP.EXAMPLE.COM
    ```

4. **Przycisku** — z `kerberos` w `OAUTH_PROVIDERS` frontendu i
   `KERBEROS_DISPLAY_NAME=Windows sign-in`, jeśli ma się tak nazywać.
5. **Polityki przeglądarki**, która pozwala jej negocjować z hostem API. To
   strefa lokalnego intranetu w Windows albo `AuthServerAllowlist` dla Chrome i
   Edge, albo `network.negotiate-auth.trusted-uris` dla Firefoksa.

Service principal musi wskazywać host, pod którym przeglądarka dociera do
**API**. To `PUBLIC_API_URL`, bo negocjacja odbywa się tam, a nie na hoście
konsoli.

Przeglądarka, która nie umie odpowiedzieć na wyzwanie, jest odsyłana prosto z
powrotem na stronę logowania ze zdaniem, które to mówi. Dotyczy to każdego
komputera spoza domeny i każdej przeglądarki, której polityka nie wymienia hosta.
Akceptowany jest wyłącznie bilet przyjęty w jednym kroku. NTLM nie jest oferowany.

## Zamiast tego przez dostawcę tożsamości { #through-an-identity-provider-instead }

Jeśli twoja firma już stawia dostawcę tożsamości przed swoim katalogiem, skieruj
AgenticOS na niego, przez [OIDC](configuration.md#single-sign-on-generic-oidc).
Do mapowań użyj jego claimu grup. Natywne logowanie LDAP i Kerberos nie są wtedy
potrzebne. To także odpowiedź w sprawie uwierzytelniania wieloskładnikowego,
którego natywne logowanie nie zapewnia.

**Keycloak** federuje oba. W **User federation** dodaj providera **LDAP** dla
swojego katalogu i włącz tam **Allow Kerberos authentication**, jeśli chcesz
zintegrowanego logowania. Jego **group-ldap-mapper** przenosi grupy z katalogu.
Potem daj klientowi AgenticOS mapper **Group Membership**, którego claim w tokenie
to `groups`, i ustaw:

```bash
OIDC_ISSUER=https://id.corp.example.com/realms/staff
OIDC_GROUPS_CLAIM=groups
```

Grupą katalogową mapowania jest wtedy to, co Keycloak umieszcza w claimie:
ścieżka grupy, na przykład `/Finance`, albo sama nazwa, jeśli **Full group path**
jest wyłączone.

**Microsoft Entra ID** z grupami synchronizowanymi z Active Directory umieszcza w
tokenie claim `groups`, gdy tylko rejestracja aplikacji ma go w **Token
configuration**. Domyślnie niesie on object id każdej grupy i to ten identyfikator
mapujesz.

### Claim grup przez OIDC { #the-groups-claim-over-oidc }

`OIDC_GROUPS_CLAIM` nazywa claim, który listuje grupy osoby. Gdy jest
nieustawiony, logowania OIDC zostawiają członkostwa w spokoju. Gdy jest
ustawiony, każde logowanie przez własnego dostawcę wdrożenia stosuje mapowania
dokładnie tak, jak robi to logowanie katalogowe. Logowanie Google nigdy tego nie
robi, bo tylko własnemu dostawcy wdrożenia ufa się w kwestii tego, w których jego
grupach ktoś jest.

Claim jest czytany z ID tokena albo z endpointu UserInfo, gdy token go nie niesie.
Skonfigurowany claim, którego brakuje, liczy się jako **brak grup**. Keycloak i
Okta pomijają pustą listę zamiast ją wysłać, a ktoś usunięty ze swojej ostatniej
grupy musi stracić to, co ona mu dawała.

!!! warning "Przekroczenie limitu grup w Entra ID jest odrzucane"

    Powyżej 200 grup Entra ID zamiast grup wysyła wskaźnik do Microsoft Graph
    (`_claim_names`). Taki token nie mówi, w których grupach jest osoba, więc
    logowanie jest odrzucane ze zdaniem proszącym o poprawkę. Odczytanie go jako
    „brak grup” odebrałoby każde członkostwo, które dał jej katalog, a
    zignorowanie go zachowałoby te, które katalog mógł już odebrać. Skonfiguruj
    rejestrację aplikacji tak, żeby wysyłała **groups assigned to the
    application**.

## Czego to jeszcze nie robi { #what-this-does-not-do-yet }

- **Nic nie sprawdza katalogu ponownie między logowaniami.** Wyłączenie konta w
  katalogu zatrzymuje jego następne logowanie, a następne logowanie to moment,
  w którym mapowania są czytane od nowa. Sesja już otwarta trwa, dopóki nie
  wygaśnie jej refresh token, czyli `REFRESH_TOKEN_EXPIRE_MINUTES`, domyślnie
  siedem dni. Żeby ją zakończyć wcześniej, dezaktywuj konto w **Admin → Users**,
  co odrzuca je wszędzie naraz. Nie ma SCIM ani zaplanowanej synchronizacji
  katalogu.
- **Konto katalogowe nadal może używać resetu hasła i magic linka.** Trafiają one
  na adres konta, jak w przypadku każdego innego konta. Jeśli katalog ma być
  jedyną drogą wejścia, trzymaj te adresy pod kontrolą samej firmy, tak jak
  zrobiłbyś to dla kont OIDC.
- **Brak SAML.** Dostawca tożsamości obsługujący wyłącznie SAML może dotrzeć do
  AgenticOS przez Keycloak, który mówi do niego po SAML, a do AgenticOS po OIDC.
