---
source_sha: "ebe8092adb19"
---

# Verzeichnisanmeldung und Gruppen { #directory-sign-in-and-groups }

Ein Unternehmen, das Active Directory, OpenLDAP oder FreeIPA betreibt, weiß
bereits, wer dort arbeitet und zu welchen Teams diese Menschen gehören. Diese
Seite beschreibt die drei Wege, auf denen AgenticOS dieses Wissen nutzen kann.
Menschen können sich mit ihrem Verzeichniskonto anmelden. Ein Browser auf einem
Rechner in der Domäne kann sie mit seinem Kerberos-Ticket anmelden. Und
Verzeichnisgruppen können entscheiden, welchen Organisationen Menschen beitreten,
mit welcher Rolle, und in welchen Gruppen sie sind.

Drei Bausteine ergeben das, und sie funktionieren unabhängig voneinander:

| Baustein | Was er tut | Konfiguriert von |
|---|---|---|
| [Gruppen](#groups) | Benannte Mengen von Mitgliedern einer Organisation, mit denen eine Ressource geteilt werden kann | Mitgliedern mit `members:manage`, in der Konsole |
| [Zuordnungen von Verzeichnisgruppen](#directory-group-mappings) | „Jeder in dieser Verzeichnisgruppe tritt mit dieser Rolle bei, in diese Gruppe“ | Mitgliedern mit `members:manage` und `roles:manage` |
| [Verzeichnisanmeldung](#signing-in-with-a-directory-account) | Anmeldung per LDAP-Passwort und per Kerberos (SPNEGO) | Dem Betreiber, in `backend/.env` |

Die Zuordnungen gelten auch für Menschen, die sich über
[OIDC](configuration.md#single-sign-on-generic-oidc) anmelden, wenn der
Identitätsanbieter ihre Gruppen meldet. Betreibt Ihr Unternehmen bereits Keycloak
oder Entra ID vor seinem Verzeichnis, brauchen Sie die native LDAP-Anmeldung
womöglich gar nicht. Siehe
[Stattdessen über einen Identitätsanbieter](#through-an-identity-provider-instead).

## Gruppen { #groups }

Eine Gruppe ist eine benannte Menge von Mitgliedern innerhalb einer Organisation:
*Finance*, *Support team*, *Platform admins*. Einen Agent, einen Skill, eine
Collection, eine Context-Datei, ein Vault-Secret oder ein Artefakt teilen Sie mit
einer Gruppe auf dieselbe Weise wie mit einer Person, über das Panel **Sharing**
der Ressource. Ein Grant erreicht dann jeden in der Gruppe.

Ein Gruppen-Grant erreicht, wer in der Gruppe ist, **wenn der Zugriff geprüft
wird**. Wer der Gruppe nächsten Monat beitritt, erreicht die Ressource; wer sie
verlässt, erreicht sie nicht mehr. Es gibt nichts, was je Person widerrufen
werden müsste.

Eine Gruppe trägt keine Rolle. Was ein Mitglied in der Organisation darf, ist
weiterhin die Rolle seiner Mitgliedschaft, und eine Gruppe fügt nur die Grants
hinzu, die an sie vergeben wurden. Der effektive Zugriff bleibt die Regel, die
unter [Berechtigungen](permissions.md#how-the-layers-combine) beschrieben ist:

```
effective access to one row = max(role scope, the person's grant, their groups' grants)
```

Erreicht eine Person eine Zeile über mehrere Grants, gewinnt die höchste Stufe.
Lesen über den eigenen Grant und Bearbeiten über den der Gruppe ergibt
Bearbeiten.

| Handlung | Wer darf |
|---|---|
| Gruppen auflisten und sehen, wer in ihnen ist | Jedes Mitglied der Organisation |
| Eine Gruppe anlegen, umbenennen oder löschen; Personen hinzufügen oder entfernen | `members:manage` |
| Eine Ressource mit einer Gruppe teilen | Wer diese Ressource bearbeiten darf |

Gruppen liegen unter **Organizations → Members → Groups**. Nur Mitglieder der
Organisation können hinzugefügt werden, und wer aus der Organisation entfernt
wird, wird aus all ihren Gruppen entfernt. Eine Gruppe zu löschen löscht jeden an
sie vergebenen Grant und jede Verzeichniszuordnung, die sie benennt, und verlangt
deshalb dieselbe Berechtigung wie das Löschen dieser Zuordnungen: Ein Admin kann
keine Gruppe löschen, auf die eine Zuordnung auf Admin-Ebene zeigt.

## Zuordnungen von Verzeichnisgruppen { #directory-group-mappings }

Eine Zuordnung sagt, was eine Verzeichnisgruppe innerhalb einer Organisation
bedeutet:

> Jeder in `CN=Finance,OU=Groups,DC=corp,DC=example,DC=com` ist hier **Mitglied**
> (`member`) und ist in der Gruppe **Finance**.

Zuordnungen liegen unter **Organizations → Members → Directory**. Sie zu lesen
verlangt `members:manage`. Eine anzulegen oder zu löschen verlangt
`members:manage` und `roles:manage`, denn eine Zuordnung lässt Menschen sowohl
ein als auch gibt sie ihnen eine Rolle.

Die Rolle ist auf dieselbe Weise begrenzt wie die einer Einladung. Sie können
eine Verzeichnisgruppe nur einer Rolle zuordnen, die Ihre eigene Rolle strikt
übertrifft. Niemand kann eine Gruppe `owner` zuordnen, und ein Admin (`admin`)
kann eine Gruppe nicht Admin zuordnen. Eine Zuordnung zu löschen verlangt
dieselbe Befugnis, denn es stuft jeden herab, den sie eingeordnet hat.

### Was bei der Anmeldung geschieht { #what-happens-at-sign-in }

Jedes Mal, wenn sich jemand per LDAP, per Kerberos oder über OIDC mit gesetztem
[`OIDC_GROUPS_CLAIM`](#the-groups-claim-over-oidc) anmeldet, werden seine
Verzeichnisgruppen gegen die Zuordnungen jeder Organisation gelesen:

1. **Einer Organisation mit passender Zuordnung** wird beigetreten, falls die
   Person noch kein Mitglied ist, mit der zugeordneten Rolle. Die Mitgliedschaft
   wird als **directory** gekennzeichnet.
2. **Bei einer Verzeichnismitgliedschaft** wird die Rolle an die Zuordnungen
   angeglichen.
3. **Die Person tritt den zugeordneten Gruppen bei** und verlässt die vom
   Verzeichnis angelegten Gruppenmitgliedschaften, die keine Zuordnung mehr
   benennt.
4. **Eine Verzeichnismitgliedschaft ohne verbliebene passende Zuordnung** wird
   entfernt, zusammen mit den Gruppenmitgliedschaften der Person in dieser
   Organisation.

Gruppen werden ohne Rücksicht auf Groß- und Kleinschreibung oder umgebende
Leerzeichen verglichen, denn jedes Verzeichnis vergleicht sie so.

Passen in einer Organisation mehrere Zuordnungen, ist die Rolle die erste dieser
Liste, die irgendeine von ihnen benennt:

**admin → builder → operator → member → viewer**

Rollen sind nicht entlang einer einzigen Befugnislinie geordnet. Ein Builder und
ein Operator halten jeweils etwas, das der andere nicht hält, deshalb wird die
Reihenfolge hier festgelegt statt hergeleitet.

### Was die Synchronisierung nie anfasst { #what-the-sync-never-touches }

Die Synchronisierung ändert nur Zeilen, die sie selbst angelegt hat. Daraus
folgen vier Regeln:

- **Eine Mitgliedschaft, die ein Administrator angelegt hat, behält ihre Rolle.**
  Wer von Hand eingeladen wurde, behält die vergebene Rolle, selbst wenn eine
  Zuordnung auf ihn passt. Den zugeordneten Gruppen tritt er trotzdem bei.
- **Die Rolle eines Verzeichnismitglieds von Hand zu ändern übernimmt die
  Mitgliedschaft.** Sie wird zu einer manuellen Mitgliedschaft, und spätere
  Anmeldungen lassen ihre Rolle unberührt.
- **Eine von Hand hinzugefügte Gruppenmitgliedschaft bleibt bestehen**, wenn das
  Verzeichnis die Person aus dieser Gruppe nehmen würde.
- **Ein Owner wird nie herabgestuft oder entfernt**, und keine Zuordnung kann
  einen erzeugen. Eigentum wandert ausschließlich über **Transfer ownership**.

Einer persönlichen Organisation wird nie über eine Zuordnung beigetreten, und für
eine solche kann keine Zuordnung angelegt werden.

!!! warning "Eine Zuordnung zu löschen entfernt die Menschen, die sie eingeordnet hat"

    Das Entfernen geschieht bei der **nächsten Anmeldung** der jeweiligen Person,
    nicht sofort. Um jemanden zu behalten, nachdem Sie die Zuordnung gelöscht
    haben, die ihn hereingebracht hat, ändern Sie vorher seine Rolle von Hand.
    Das übernimmt die Mitgliedschaft.

### Zuordnungen lassen neue Konten zu { #mappings-admit-new-accounts }

Eine Zuordnung zählt als Einladung. Auf einem `invite_only`-Deployment oder einem
mit einer Liste erlaubter Domains legt eine erste Anmeldung, deren Gruppen auf die
Zuordnung irgendeiner Organisation passen, das Konto an. Jemand, der sowohl
`members:manage` als auch `roles:manage` hält, hat entschieden, dass jeder in
dieser Gruppe dazugehört. Ein `closed`-Deployment weist sie trotzdem ab. Siehe
[Wer sich registrieren darf](deployment.md#who-may-register).

## Anmeldung mit einem Verzeichniskonto { #signing-in-with-a-directory-account }

Ist `LDAP_URL` gesetzt, bietet die Anmeldeseite ein Verzeichnisformular an.
Menschen geben den Benutzernamen ein, den sie überall sonst verwenden, und ihr
Verzeichnispasswort. AgenticOS prüft das Passwort mit dem üblichen zweistufigen
Bind:

1. Es durchsucht `LDAP_USER_BASE_DN` mit `LDAP_USER_FILTER`, unter Verwendung des
   Dienstkontos (`LDAP_BIND_DN`), nach genau einem Konto, das auf den
   Benutzernamen passt.
2. Es bindet **als dieses Konto** mit dem eingegebenen Passwort. Nur das
   Verzeichnis prüft das Passwort. Es wird hier weder gespeichert noch gehasht
   noch protokolliert.

Das Konto hängt an der eigenen stabilen Kennung des Verzeichnisses:
`LDAP_ID_ATTRIBUTE`, `objectGUID` bei Active Directory und `entryUUID` bei
OpenLDAP und FreeIPA. Es hängt nicht an der Adresse, sodass eine umbenannte
Person ihre Historie behält. Bei der ersten Anmeldung wird das Konto nach der
[Registrierungsrichtlinie](deployment.md#who-may-register) angelegt, und ein
bestehendes Konto mit derselben Adresse wird damit verknüpft.

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

Jede Einstellung samt ihrem Standardwert steht unter
[Konfiguration](configuration.md#directory-sign-in-ldap).

### Was die Anmeldung abweist { #what-the-sign-in-refuses }

| Abgewiesen | Warum |
|---|---|
| Ein leeres Passwort | Ein LDAP-Bind mit einem Namen und ohne Passwort ist ein *nicht authentifizierter* Bind, den viele Server akzeptieren (RFC 4513). Es erreicht das Verzeichnis nie |
| Zwei Konten, die auf einen Benutzernamen passen | Als dasjenige zu binden, das zuerst zurückkam, könnte eine Person als eine andere anmelden |
| Ein Benutzername mit Filtersyntax | Er wird maskiert (RFC 4515), sodass `*` niemanden findet statt jeden |
| Ein Konto ohne Adresse oder ohne Kennung | Das Konto, die Einladung und die Registrierungsrichtlinie hängen alle daran |
| `ldap://` ohne StartTLS | Es sendet jedes Passwort im Klartext. Der Prozess verweigert den Start, sofern `LDAP_ALLOW_PLAINTEXT=true` das nicht absichtlich erlaubt |

Ein falscher Benutzername und ein falsches Passwort bekommen dieselbe Antwort. Ein
Verzeichnis, das nicht erreichbar ist, ein abgewiesenes Dienstkonto und eine
Suche, die das Verzeichnis nicht beantworten konnte (etwa ein falscher Base DN),
werden als nicht verfügbares Verzeichnis gemeldet. Sie werden nicht als falsches
Passwort gemeldet, denn das würde jede Person im Unternehmen dazu bringen, ihres
zurückzusetzen.

Das Zertifikat wird gegen den Trust Store des Systems geprüft, oder gegen
`LDAP_CA_CERT_FILE` für eine unternehmenseigene CA, und ebenso der Hostname. Die
Anmeldung ist je Adresse und je Benutzername rate-limitiert, wie die
Passwortanmeldung.

### Gruppen aus dem Verzeichnis { #groups-from-the-directory }

Standardmäßig sind die Gruppen einer Person die DNs in ihrem Attribut `memberOf`.
Ein Verzeichnis ohne `memberOf` kann stattdessen durchsucht werden: Setzen Sie
`LDAP_GROUP_BASE_DN` und `LDAP_GROUP_FILTER` mit `{dn}` oder `{username}` darin.
Für die verschachtelten Gruppen von Active Directory suchen Sie mit der Matching
Rule, die der Kette folgt:

```bash
LDAP_GROUP_BASE_DN=OU=Groups,DC=corp,DC=example,DC=com
LDAP_GROUP_FILTER=(member:1.2.840.113556.1.4.1941:={dn})
```

Um überhaupt nur eine Gruppe anmelden zu lassen, setzen Sie sie in
`LDAP_USER_FILTER`:
`(&(objectClass=user)(sAMAccountName={username})(memberOf=CN=AgenticOS Users,OU=Groups,DC=corp,DC=example,DC=com))`.

## Integrierte Windows-Anmeldung (Kerberos) { #integrated-windows-sign-in-kerberos }

Auf einem Rechner in der Domäne beantwortet ein Browser, der auf einen Host
zeigt, dem seine Richtlinie vertraut, `WWW-Authenticate: Negotiate` mit einem
Kerberos-Ticket. Mit `KERBEROS_ENABLED=true` bietet die Anmeldeseite eine
Schaltfläche an, die die Person mit diesem Ticket anmeldet, und niemand tippt ein Passwort.

Das Ticket benennt einen Principal, `jane@CORP.EXAMPLE.COM`. AgenticOS löst ihn
über das Verzeichnis oben auf, mit `LDAP_KERBEROS_FILTER`
(standardmäßig `(userPrincipalName={principal})`), zu **demselben Konto**, das die
LDAP-Passwortanmeldung erreicht. Kerberos braucht also ebenfalls `LDAP_URL`, und
das Verzeichnis entscheidet Adresse und Gruppen für beide auf dieselbe Weise.

Was es braucht:

1. **Ein Image, das mit dem Extra `kerberos` gebaut wurde.** `gssapi` wird gegen
   die Kerberos-Bibliotheken des Systems kompiliert und ist daher nicht im
   Standard-Image:
   `docker build --build-arg EXTRAS="--extra kerberos" -f backend/Dockerfile .`
2. **Einen Service Principal und seine Keytab.** Legen Sie in Active Directory
   ein Dienstkonto an, geben Sie ihm den SPN `HTTP/agenticos.corp.example.com`
   und exportieren Sie mit `ktpass` eine Keytab. Binden Sie sie in den
   Backend-Container ein.
3. **Die Backend-Einstellungen.**

    ```bash
    KERBEROS_ENABLED=true
    KERBEROS_KEYTAB=/etc/agenticos/http.keytab
    KERBEROS_SERVICE_PRINCIPAL=HTTP/agenticos.corp.example.com@CORP.EXAMPLE.COM
    ```

4. **Die Schaltfläche**, mit `kerberos` in `OAUTH_PROVIDERS` des Frontends und
   `KERBEROS_DISPLAY_NAME=Windows sign-in`, falls sie so heißen soll.
5. **Eine Browser-Richtlinie**, die den Browser mit dem API-Host verhandeln
   lässt. Das heißt die lokale Intranetzone unter Windows, oder
   `AuthServerAllowlist` für Chrome und Edge, oder
   `network.negotiate-auth.trusted-uris` für Firefox.

Der Service Principal muss den Host benennen, unter dem der Browser die **API**
erreicht. Das ist `PUBLIC_API_URL`, denn die Verhandlung findet dort statt, nicht
auf dem Host der Konsole.

Ein Browser, der die Challenge nicht beantworten kann, wird direkt zur
Anmeldeseite zurückgeschickt, mit einem Satz, der das sagt. Das betrifft jeden
Rechner außerhalb der Domäne und jeden Browser, dessen Richtlinie den Host nicht
aufführt. Nur ein in einem Schritt angenommenes Ticket wird überhaupt angenommen.
NTLM wird nicht angeboten.

## Stattdessen über einen Identitätsanbieter { #through-an-identity-provider-instead }

Stellt Ihr Unternehmen bereits einen Identitätsanbieter vor sein Verzeichnis,
richten Sie AgenticOS stattdessen auf diesen, über
[OIDC](configuration.md#single-sign-on-generic-oidc). Nutzen Sie seinen
Gruppen-Claim für die Zuordnungen. Die native LDAP- und Kerberos-Anmeldung wird
dann nicht gebraucht. Das ist auch die Antwort auf Multi-Faktor-Authentifizierung,
die die native Anmeldung nicht leistet.

**Keycloak** föderiert beides. Fügen Sie unter **User federation** einen
**LDAP**-Provider für Ihr Verzeichnis hinzu, und schalten Sie dort **Allow
Kerberos authentication** ein, wenn Sie die integrierte Anmeldung wollen. Sein
**group-ldap-mapper** bringt die Gruppen des Verzeichnisses herüber. Geben Sie
dann dem AgenticOS-Client einen **Group Membership**-Mapper, dessen Token-Claim
`groups` ist, und setzen Sie:

```bash
OIDC_ISSUER=https://id.corp.example.com/realms/staff
OIDC_GROUPS_CLAIM=groups
```

Die Verzeichnisgruppe der Zuordnung ist dann das, was Keycloak in den Claim legt:
der Gruppenpfad, etwa `/Finance`, oder der bloße Name, wenn **Full group path**
ausgeschaltet ist.

**Microsoft Entra ID** legt, mit aus Active Directory synchronisierten Gruppen,
einen Claim `groups` ins Token, sobald die App-Registrierung einen unter **Token
configuration** hat. Standardmäßig trägt er die Objekt-ID jeder Gruppe, und diese
ID ist das, was Sie zuordnen.

### Der Gruppen-Claim über OIDC { #the-groups-claim-over-oidc }

`OIDC_GROUPS_CLAIM` benennt den Claim, der die Gruppen einer Person auflistet.
Ist er nicht gesetzt, lassen OIDC-Anmeldungen Mitgliedschaften unberührt. Ist er
gesetzt, wendet jede Anmeldung über den eigenen Provider des Deployments die
Zuordnungen genau so an, wie es eine Verzeichnisanmeldung tut. Die
Google-Anmeldung tut das nie, denn nur dem eigenen Provider des Deployments wird
zugetraut zu sagen, in welchen seiner Gruppen jemand ist.

Der Claim wird aus dem ID-Token gelesen, oder aus dem UserInfo-Endpunkt, wenn das
Token ihn nicht trägt. Ein konfigurierter Claim, der fehlt, zählt als **keine
Gruppen**. Keycloak und Okta lassen eine leere Liste weg, statt eine zu senden,
und wer aus seiner letzten Gruppe entfernt wurde, muss verlieren, was sie ihm
gegeben hat. Fehlt der Claim im Token und ist UserInfo nicht erreichbar, wird die
Anmeldung stattdessen abgewiesen: Das sagt nichts über die Gruppen der Person, und
es als keine zu lesen, würde sie ihr entziehen.

`OIDC_GROUPS_CLAIM` und `LDAP_URL` können nicht zusammen gesetzt werden. Jedes
meldet Gruppen in eigenen Kennungen, und jede Anmeldung würde die Mitgliedschaften
entfernen, die das andere angelegt hat, daher startet der Prozess mit beiden nicht.

!!! warning "Ein Gruppen-Overage von Entra ID wird abgewiesen"

    Ab mehr als 200 Gruppen sendet Entra ID statt der Gruppen einen Verweis auf
    Microsoft Graph (`_claim_names`). Ein solches Token sagt nicht, in welchen
    Gruppen die Person ist, also wird die Anmeldung mit einem Satz abgewiesen,
    der um die Behebung bittet. Es als „keine Gruppen“ zu lesen, würde jede
    Mitgliedschaft entziehen, die das Verzeichnis gegeben hat, und es zu
    ignorieren, würde solche behalten, die es womöglich entzogen hat.
    Konfigurieren Sie die App-Registrierung so, dass sie **groups assigned to
    the application** sendet.

## Was dies noch nicht tut { #what-this-does-not-do-yet }

- **Nichts prüft das Verzeichnis zwischen Anmeldungen erneut.** Ein Konto im
  Verzeichnis zu deaktivieren verhindert seine nächste Anmeldung, und die nächste
  Anmeldung ist der Zeitpunkt, zu dem Zuordnungen neu gelesen werden. Eine bereits
  offene Session hält, bis ihr Refresh Token abläuft, was
  `REFRESH_TOKEN_EXPIRE_MINUTES` ist und standardmäßig sieben Tage. Um eine
  früher zu beenden, deaktivieren Sie das Konto unter **Admin → Users**, was es
  überall sofort abweist. Es gibt kein SCIM und keine geplante
  Verzeichnissynchronisierung.
- **Ein Verzeichniskonto kann weiterhin Passwort-Reset und Magic Link nutzen.**
  Sie gehen an die Adresse des Kontos, wie bei jedem anderen Konto. Soll das
  Verzeichnis der einzige Weg hinein sein, halten Sie diese Adressen unter der
  eigenen Kontrolle des Unternehmens, wie Sie es für OIDC-Konten täten.
- **Kein SAML.** Ein Identitätsanbieter, der nur SAML spricht, kann AgenticOS über
  Keycloak erreichen, das mit ihm SAML und mit AgenticOS OIDC spricht.
