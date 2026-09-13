---
source_sha: e5e660ee22ce
---

# Das Deployment selbst { #the-deployment-itself }

Der größte Teil dieses Produkts handelt von Agents. Diese Seite handelt von dem,
worin sie laufen.

**Eine Installation, mit einem Namen, einer Marke, einer Regel darüber, wer
beitreten darf, und einem Schalter, der sie schließt.** All das liegt in einer
einzigen Datenbankzeile und wird unter `/admin/settings` von demjenigen
bearbeitet, der `is_app_admin` hält — kein Redeploy, keine Umgebungsvariable,
kein Rebuild.

!!! info "Warum diese Autorität und nicht eine Berechtigung"

    Eine Berechtigung gilt innerhalb einer Organisation. Diese Zeile liegt in
    keiner.

    Es ist dieselbe Autorität, die Nutzer und Tenants bereits über die gesamte
    Installation hinweg verwaltet.

## Identität { #identity }

| Feld | Wo es erscheint |
|---|---|
| Name | Die Seitenleiste, die Kopfzeile der Anmeldung, der Browser-Tab, die OpenGraph-Karte und jede E-Mail, die dieses Deployment versendet |
| Tagline | Neben dem Namen im Tab-Titel und auf einem geteilten Link |
| Beschreibung | Die Seitenbeschreibung und Link-Vorschauen |
| Logo | Überall dort, wo der Name erscheint — der Markenlink, die Kopfzeile der Anmeldung, die rechtlichen Seiten |
| Favicon | Der Browser-Tab |
| Fußzeilentext | Unter dem Anmeldeformular |
| Terms URL, Privacy URL | Jeder Link, der sonst die eingebauten `/legal/*`-Seiten anbietet |

!!! note "Eine Null-Spalte bedeutet *den eingebauten Wert*, nicht *leer*"

    Wer als Betreiber ein Feld leert, fordert die Voreinstellung zurück und nicht
    eine Anmelde-Kopfzeile ohne Namen darin. Die API antwortet mit
    *Überschreibungen*, und jeder Renderer löst eine Null gegen seinen eigenen
    eingebauten Wert auf.

Ein Betreiber, der die Seite nie geöffnet hat, hat überhaupt keine Zeile. Die
Konsole löst eine Null gegen `APP_NAME` und `SITE` in `frontend/src/lib/` auf;
das Backend löst sie gegen `settings.PROJECT_NAME` für die Mail auf, die es
selbst versendet.

Zwei Konstanten für einen Produktnamen können auseinanderlaufen, deshalb hält
`backend/tests/test_deployment_settings.py` sie gleich. Der Test liest die
`constants.ts` des Frontends und vergleicht sie mit dem Klassen-Default von
`Settings.PROJECT_NAME` — dieselbe Abmachung, die `TestFrontendToolCatalog` mit
dem Tool-Katalog eingeht.

### Die zwei Bilder { #the-two-images }

Hochgeladen über `POST /api/v1/admin/settings/{logo,favicon}` und gespeichert wie
jedes andere Bild dieser Plattform: die Bytes gehen in den konfigurierten
Dateispeicher, der Schlüssel geht in eine Spalte. **Der Schlüssel wird niemals
einem Request-Body entnommen** — wer ihn benennen könnte, könnte das öffentliche
Logo dieses Deployments auf beliebige Inhalte des Speicher-Backends richten — und
der gespeicherte Dateiname wird aus dem validierten Content-Type geprägt statt aus
dem Namen des Uploads, denn diese Dateien werden von derselben Origin
ausgeliefert, unter der die Seiten der App laufen, und `logo.html` ist dort ein
Skript.

JPEG, PNG, WebP und GIF, bis 2MB, was die eine Definition von „ein Bild, das
diese Plattform annimmt" ist.

!!! danger "SVG fehlt absichtlich"

    Es ist ein Dokument, das Skript tragen kann, und diese Dateien werden von
    derselben Origin ausgeliefert, unter der die Seiten der App laufen. ICO
    bringt nichts, was ein PNG-Favicon nicht auch bringt.

Die Branding-Antwort trägt eine **Version**, keine URL. Die Adresse ist konstant
(`GET /api/v1/branding/{logo,favicon}`) und die Bytes werden ein Jahr lang als
`immutable` ausgeliefert; was ein Client also aus der Zeile braucht, ist, ob ein
Bild existiert und wann es sich zuletzt geändert hat. Das daraus gebaute `?v=`
ist der einzige Grund, weshalb ein Ersatz überhaupt jemals sichtbar wird. Eine
URL wäre zudem eine, die jeder Client umschreiben müsste, denn in jedem echten
Deployment liegt die API nicht auf derselben Origin wie die Seiten.

## Security-Header { #security-headers }

Jede Seite der Konsole trägt eine Content-Security-Policy und die üblichen
Härtungs-Header, definiert in `frontend/src/lib/csp.ts` und
`frontend/src/lib/security-headers.ts`, beide durch Tests abgesichert. Die Policy
ist `default-src 'self'` mit einem `connect-src`, das genau diese Origin,
`PUBLIC_API_URL` und `PUBLIC_WS_URL` benennt, einem `img-src`, das `data:` für
die Markenglyphen und Avatare erlaubt, `frame-src 'self' blob:` für
Dokumentvorschauen, `object-src 'none'`, `base-uri 'self'` und
`frame-ancestors 'none'`.

Die Policy wird pro Request von der Middleware des Frontends gesetzt, weil die
beiden öffentlichen URLs zur Laufzeit aus der Umgebung des Servers gelesen werden
und ein zur Build-Zeit gesetzter Header nur `localhost` benennen könnte. Die
übrigen Header sind Konstanten und werden von der Konfiguration von Next gesetzt.
Ändern Sie die öffentlichen URLs, und die Policy folgt beim nächsten Request;
nichts wird neu gebaut.

Daneben stehen `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
`Referrer-Policy: strict-origin-when-cross-origin` und eine
`Permissions-Policy`, die Kamera und Geolocation verweigert und das Mikrofon nur
auf dieser Origin erlaubt, für die Spracherkennung im Chat.

!!! warning "Ein Reverse Proxy darf keine eigenen Kopien davon ergänzen"

    Nginx, Traefik oder ein ALB vor der App reicht diese unverändert durch,
    statt eigene zu setzen. Zwei `Content-Security-Policy`-Header auf einer
    Antwort werden vom Browser zu ihrer Schnittmenge kombiniert, ein Proxy, der
    einen zweiten ergänzt — selbst einen laxeren — verschärft die Policy also nur
    zu etwas, das ein Panel blockiert, das niemand blockieren wollte; und bei
    einem zweiten `X-Frame-Options` sucht sich der Browser einen der beiden Werte
    aus. Die mitgelieferte `nginx/nginx.conf` setzt nur
    `Strict-Transport-Security`, das demjenigen gehört, der TLS terminiert; eine
    bestehende Proxy-Konfiguration, die die anderen ergänzt, sollte sie fallen
    lassen.

## Wer sich registrieren darf { #who-may-register }

`signup_mode`, angewendet in `app/services/signup_policy.py` — der einen Stelle,
und sie kontrolliert **beide** Pfade, die ein Konto prägen.

| Modus | Wirkung |
|---|---|
| `open` | Jeder darf sich registrieren. Die Voreinstellung, und das, was jedes Deployment vor diesem Feature war. |
| `invite_only` | Nur eine Adresse, die irgendeine Organisation tatsächlich eingeladen hat. |
| `closed` | Niemand registriert sich, auf keinem Weg — eine Einladung setzt das nicht außer Kraft. |

Über alle drei hinweg schränkt eine nicht leere `allowed_email_domains` ein, wer
sich überhaupt registrieren darf. **Eine Einladung setzt diese Liste außer
Kraft** — jemand mit `members:invite` hat die Adresse absichtlich benannt, und
eine Domain-Liste ist Deployment-Politik gegenüber Fremden und kein Veto gegen
eine bewusste Handlung. `closed` wird durch nichts außer Kraft gesetzt, denn ein
„geschlossen", das einige Registrierungen durchlässt, ist nicht geschlossen.

**`closed` heißt geschlossen, und es gibt keinen Pfad, auf dem ein Administrator
ein Konto anlegt.** Absichtlich: ein Konto braucht ein Passwort, das sein
Eigentümer gewählt hat, jemanden hinzuzufügen heißt also, die Registrierung *für
ihn* zu öffnen — wofür `invite_only` da ist. Ein Modus, der einen Administrator
Konten prägen ließe, wäre ein dritter Pfad, der eines prägt, und die beiden
bereits vorhandenen sind der ganze Grund, weshalb `signup_policy` ein Modul ist
und keine Prüfung innerhalb von `register`. Ein Deployment, das eine Person mehr
aufnehmen muss, wechselt also zu `invite_only` und lädt sie ein.

Drei weitere Dinge daran sind leicht falsch zu machen und waren es:

**Der erste Nutzer wird immer zugelassen.** Eine frische Installation hat keine
Konten, ihr Administrator existiert also noch nicht; ein geschlossenes Deployment,
das auch die Person abweist, die es öffnen würde, ist eines, das niemand betreten
kann, ohne Konsole, um es zu reparieren. `register` befördert dieses erste Konto
ohnehin zu `is_app_admin`, und die Policy beugt sich derselben Tatsache.

**`invite_only` existiert, weil das Schließen der Registrierung sonst Einladungen
kaputtmachen würde.** `InvitationService.accept` verlangt einen bestehenden,
angemeldeten Nutzer, eine eingeladene Person muss sich also zuerst registrieren.
Die Policy fragt `invitation_repo.first_pending_admitting`, was konstruktionsbedingt
tenant-übergreifend ist — die Registrierung findet statt, bevor eine Organisation
gewählt wird. Sicher bleibt das durch den Ort, an den die Antwort geht: die Policy
verwandelt sie in eine boolesche Ablehnung, ein Fremder, der das Anmeldeformular
sondiert, erfährt also, dass jemand die Adresse eingeladen hat, und nie, welche
Organisation das war.

**Wie eine Einladung erkannt wird, hängt davon ab, ob die Registrierung ihren
Token mitbringt**, und die beiden Antworten decken unterschiedliche Formen ab:

| Kommt an mit | Erkannt durch | Welche Formen sie zulässt |
|---|---|---|
| Einem Token (aufgelöst aus der vorgemerkten Einladung, nie am Anmelde-Body) | `invitation_admission.admits` | Jede lebende Einladung, die die Adresse zulässt — einschließlich eines Links, der **keine** Adresse einschränkt, was die Form ist, die sonst nichts sehen kann |
| Ohne Token | `invitation_repo.first_pending_admitting` | Eine E-Mail-Einladung für diese Adresse oder ein Link, der auf ihre Domain eingegrenzt ist |

Der Token ist der einzige verfügbare Nachweis für einen teilbaren Link, an dem
weder eine Adresse noch eine Domain hängt. Eine Abfrage über die übermittelte
Adresse kann einen solchen nicht erkennen, ihn *ohne* Besitznachweis zu
honorieren würde einen einzelnen offenen Link irgendwo im Deployment also in
offene Registrierung für das gesamte Internet verwandeln. Den Token zu halten ist
dieser Nachweis.

Ein Token, der nichts Lebendes benennt, fällt auf die Adressfrage zurück, statt
abzulehnen: ein veralteter Link in einem Lesezeichen sollte eine ansonsten
erlaubte Registrierung nicht in einen Fehler über etwas verwandeln, das die
Person nicht beheben kann.

**Eine Registrierung mit Token nimmt die Einladung nicht an.** Sie lässt das Konto
zu und sonst nichts; der Beitritt zur Organisation ist weiterhin
`InvitationService.accept`, das der Client aufruft, sobald er eine Session hat.
Ein Token in einem unauthentifizierten Anmelde-Body, der auch noch Mitgliedschaft
gewährte, wäre eine Mitgliedschaftszuteilung auf einer öffentlichen Route.

Die Konsole trägt den Token nie über den Anmelde-Roundtrip. Eine eingeladene
Person ohne Konto öffnet `/invitations/<token>`; `AuthGuard` tauscht den Token
serverseitig gegen einen undurchsichtigen Handle, den er in einem
`httpOnly`-Cookie hält, das der Browser nicht lesen kann, und schickt sie dann zu
`/login?returnTo=/invitations/pending?flow=…` — eine Landeseite ohne Credential
darin, der Token steht also weder im `returnTo` noch im Browserverlauf noch im
Session Storage. Schlägt der Tausch fehl — Server nicht erreichbar, ein Rate
Limit — bleibt der Guard auf dem Einladungslink und bietet einen neuen Versuch
an, statt ohne etwas Vorgemerktes zu gehen, denn der Link ist das einzige
Credential, das die eingeladene Person hält.

Der `flow` ist eine zufällige Id, die der Tausch pro Vormerkung prägt, und das
Cookie ist nach ihr benannt. Er ist kein Credential: ohne das Cookie benennt er
nichts. Er existiert, weil ein fester Cookie-Name ein einziger Platz ist — zwei
Einladungslinks, im abgemeldeten Zustand nebeneinander geöffnet, haben einander
überschrieben, und beide wartenden Tabs lösten danach den zweiten ein. Jeder Tab
löst jetzt genau das Cookie ein, das sein eigener `flow` benennt.

„Create an account" trägt diese credential-freie Landeseite weiter, und der
Register-Proxy reicht den vorgemerkten Handle des benannten `flow` als Header
weiter, die Zulassung bei der Registrierung hat den benötigten Token also
weiterhin, ohne dass der Token je in einer URL oder im Body steht. Nach der
Anmeldung löst die wartende Seite den Handle ein und nimmt an — dieselbe Form wie
der Tausch des OAuth-Codes, ein undurchsichtiger, einmal verwendbarer,
ablaufender Stellvertreter für ein Credential, damit das Credential nie auf einer
URL mitreist. Das Cookie wird gelöscht, sobald das Einlösen gelaufen ist; ein
401, ein 429 oder ein Serverfehler lässt es stehen, denn der Handle ist
womöglich noch ungenutzt und ein neuer Versuch braucht ihn.

**Ein Link mit `max_uses` begrenzt Konten, nicht nur Beitritte.**

`used_count` zählt Annahmen, und eine Annahme braucht eine Session — eine Obergrenze,
die allein daran abgelesen wird, begrenzte also nichts, was eine Registrierung
tat. Ein einzelner Einmal-Link, in einem Kanal gepostet, ließ so viele Konten zu,
wie irgendjemand anlegen mochte, auf dem Deployment, das die Anmeldung gerade
geschlossen hatte.

Eine Nutzung wird deshalb zuerst für die sich registrierende Adresse
**reserviert**: `reserved_emails` auf der Zeile, und `used_count + reserved_emails`
ist das, was „aufgebraucht" heißt. Die Reservierung ist ein einzelnes bedingtes
`UPDATE`, denn zwei Registrierungen, die um die letzte Nutzung wettlaufen, würden
sonst beide denselben Zählerstand lesen.

Das Annehmen nimmt die Adresse aus der Liste, während es den Zähler erhöht, was
sie erhält — wer sich über einen Einmal-Link registriert hat, kann weiterhin
beitreten.

Eine Reservierung, die niemand annimmt, bleibt verbraucht (`max_uses` ist die
Anzahl der Personen, die ein Link zulässt, und ein damit angelegtes Konto wurde
zugelassen), und sie stirbt mit der Einladung.

**Eine Anmeldung über einen Provider trägt die Einladung ebenfalls, als ihren
Handle.** Die Provider-Anmeldung beginnt auf derselben Origin, unter
`/api/oauth/<provider>/login`, der vorgemerkte `httpOnly`-Handle kann also an den
Origin-übergreifenden Sprung angehängt werden, den der Browser dann macht —
`/oauth/google/login?invitation_handle=…`, das das Backend in den Token
hineinschauen lässt, den es über den Roundtrip in der Session hält. Der Token
steht nie in dieser URL. Ohne das lehnte `invite_only` den Google-Button genau
für die Links ab, die einen Token brauchen — einen, der weder eine Adresse noch
eine Domain einschränkt — während das Passwortformular daneben dieselbe Person
annahm.

**Eine Anmeldung über einen Provider ist ebenfalls eine Registrierung.**
`get_or_create_oauth_user` ist der zweite Pfad, der ein Konto anlegt, und nichts
an einem Google-Callback sieht nach einer Anmeldung aus — ein Deployment mit
`closed` und einem Google-Button war also weit offen, bis beide kontrolliert
wurden. Wer *bereits* ein Konto hat, wird nicht erneut kontrolliert: das
Schließen der Registrierung schließt die Registrierung, und ein Mitglied aus
einem Deployment auszusperren, dem es angehört, ist nicht das, was die
Einstellung sagt.

Das Anmeldeformular liest die Policy vom öffentlichen Branding-Endpunkt und
nennt die Regel, **bevor** jemand tippt. Ein Formular, das eine Adresse annimmt
und dann meldet, „diese E-Mail-Domain darf sich nicht registrieren", ist ein
Formular, das lügt; der Besucher hat keine Möglichkeit zu wissen, dass die Regel
existiert, und liest die Ablehnung als ein kaputtes Produkt. Auch deshalb werden
die erlaubten Domains veröffentlicht: sie sind kein Geheimnis, und das Deployment
läuft auf dem eigenen Host des Unternehmens.

## Einen Tenant unter allen finden { #finding-one-tenant-among-all-of-them }

`GET /admin/organizations` ist die einzige Oberfläche, die beantwortet, *welche
Tenants existieren*, und sie ist aus genau dem Grund App-Admin-only, aus dem sie
nützlich ist: sie ist konstruktionsbedingt tenant-übergreifend. Sie antwortet mit
einer Seite von Organisationen samt der Anzahl ihrer Mitglieder und Agents und
ihres frühesten Owners — wen man dazu fragt. Jedes Owner-Feld ist zugleich null,
bei einer Organisation, deren letzter Owner gegangen ist, was ein Zustand ist, den
nur der Deployment-Admin beheben kann und der ihm deshalb gezeigt werden muss.

| Parameter | |
|---|---|
| `search` | Name, Slug oder die Adresse des Owners. Der Begriff ist Text, kein Muster — `100%` findet den so genannten Tenant und nicht alle |
| `sort_by` | `name`, `slug`, `members`, `agents`, `created_at`. Alles andere ist ein 422 |
| `sort_dir` | `asc` / `desc`, standardmäßig neueste zuerst |
| `kind` | `personal`, `team` oder `all`. Jedes Konto bekommt bei der Anmeldung eine persönliche Organisation, auf den meisten Deployments machen sie also den Großteil der Liste aus |
| `skip`, `limit` | Eine Serverseite, bis zu 100 |

**All das geschieht in SQL, vor `OFFSET`/`LIMIT`**, und `total` zählt das, worauf
eingegrenzt wurde, und nicht das Deployment. Das ist der Unterschied zwischen
einer Sortierung und ihrem Anschein: eine Seite, die nach der Ankunft sortiert
wird, behauptet eine Ordnung über die ganze Sammlung, die fünfzig Zeilen nicht
liefern können, weshalb die Tenant-Liste des Admins gar keine Bedienelemente
trug, solange die Route keine beantwortete (#921). Die Ordnung bricht
Gleichstände über die Id, das Blättern über eine Spalte, in der Zeilen einen Wert
teilen, listet jede von ihnen also genau einmal.

Eine Spalte außerhalb der Menge wird namentlich abgelehnt, statt gegen nichts
abgeglichen zu werden, aus den beiden Gründen, aus denen `GET /runs` eine
ablehnt: eine leere Seite liest sich als *dieses Deployment hat keine Tenants*,
und ein aus einem Query-String zusammengesetztes `ORDER BY` ist eine
Angriffsfläche für Injection.

## Ein App-Admin kann das Deployment über die Konsole nicht aussperren { #an-app-admin-cannot-lock-the-deployment-out-through-the-console }

!!! warning "Die selbstverschuldete Aussperrung, die das verhindert"

    Auf der Installation mit einem einzigen Admin, die `make platform-bootstrap`
    erzeugt, beendete ein versehentlicher Klick auf die eigene Zeile die
    Administration, bis jemand ein Terminal erreichte. Die Wiederherstellung ist
    `agenticos cmd create-app-admin <email>` aus einer Shell — die E-Mail-Adresse
    ist ein Pflichtargument.

`is_active` wird beim nächsten Request durchgesetzt und `is_app_admin` ist das,
was die Admin-Seiten lesen, ein App-Admin, der unter `/admin/users` auf **seiner
eigenen** Zeile handelt, könnte sich also selbst abmelden, `/admin` verlieren
oder das Konto löschen. `UserService.admin_update` und `admin_delete` lehnen die
Selbstsperrung und die Selbstlöschung ab, und die Schublade bietet auf Ihrer
eigenen Zeile weder Suspend noch Demote noch Impersonate an (Delete bleibt,
sichtbar und abgelehnt, denn „warum kann ich mich nicht selbst löschen" hat eine
Antwort, die es wert ist, gezeigt zu werden). Die API lehnt es auch ab, als man
selbst zu handeln — niemand, der als niemand handelt, ist keine Impersonation.

Das Deployment kann über die API überhaupt nicht ohne App-Admin zurückbleiben:
das eine globale Privileg wird nur per CLI vergeben
(`agenticos cmd create-app-admin`) und es gibt keinen Request, der es entfernt,
die Menge der App-Admins schrumpft also nur durch Löschung — und den *letzten* zu
löschen heißt, sich selbst zu löschen, was abgelehnt wird. Einen Admin zu
entfernen, der tatsächlich geht, ist die Handlung eines anderen Admins, was
zugleich den Audit-Trail lesbar hält. Die Wiederherstellung, falls sie je
gebraucht wird, ist weiterhin `create-app-admin` aus einer Shell auf dem
Deployment.

Dieses Argument handelt von der *Menge*, und eine Zeit lang handelte der Code von
einer Zeile.

Zwei Admins, die einander löschten, löschten jeweils nicht sich selbst. Sie
sperrten unterschiedliche Zielzeilen, gerieten nie in Konkurrenz und committeten
beide — null App-Admins, wiederherstellbar nur durch Schreiben in die Datenbank
(#1208).

Eine Admin-Löschung nimmt deshalb `SELECT ... FOR UPDATE` über die Menge der
App-Admins, nach Id geordnet, bevor sie entscheidet. Der zweite Request wartet,
liest die Menge erneut, sobald der erste committet hat, und wird dafür abgelehnt,
dass er sie leeren würde.

Geordnet, denn zwei Requests, die dieselben Zeilen in unterschiedlicher
Reihenfolge nehmen, sind ein Deadlock und keine Warteschlange. Und genommen bei
jeder Nutzerlöschung statt nur bei der eines Admins: einen Nutzer zu löschen ist
die Handlung eines Administrators und kein heißer Pfad, und eine totale Ordnung
ist mehr wert als die Konkurrenz, die sie kostet.

## Als ein anderes Konto handeln { #acting-as-another-account }

**Impersonate** unter `/admin/users` beginnt, aus Ihrem eigenen Browser heraus als
diese Person zu handeln. Nichts wird irgendwohin kopiert: die Konsole tauscht das
Access-Cookie der Session gegen eines, das das Ziel benennt, jede Seite rendert
so, wie diese Person sie sähe, und ein Banner über die volle Breite sagt, wessen
Konto das ist und wer wirklich handelt, mit der einen Schaltfläche, die es
beendet.

Eine Impersonation ist eine **Session**, kein bloßes Credential. Der Token
benennt eine Zeile in `sessions` mit gesetztem `impersonator_user_id`, und die
API lehnt ihn in dem Moment ab, in dem diese Zeile beendet ist oder abgelaufen
ist oder der Administrator dahinter kein aktiver App-Admin mehr ist — sie endet
also, wenn Sie **End impersonation** drücken, wenn die Person sich überall
abmeldet oder ihr Passwort ändert, wenn die Stunde um ist, oder wenn der
Administrator gesperrt, herabgestuft oder gelöscht wird, was auch immer zuerst
eintritt. Sie kann nicht erneuert werden: das Fenster ist das des Access-Tokens
selbst, und die Stunde ist die Obergrenze und keine verlängerbare Leihfrist.

!!! note "Eine offene Chat-Unterhaltung endet mit ihr"

    Eine Chat-Unterhaltung läuft über einen WebSocket, der sich einmal
    authentifiziert, beim Handshake. Er führt diese Prüfung jetzt bei jeder
    Nachricht erneut aus, das Beenden einer Impersonation — oder das Sperren des
    Kontos — schließt also auch einen offenen Chat, statt nur den nächsten
    HTTP-Request abzulehnen, während der Socket weiter antwortet.

!!! note "Die Geräteliste der Person selbst zeigt sie nicht"

    Eine Impersonation ist eine Zeile unter ihrer Id, die ein Administrator hält,
    und kein Gerät, von dem sie sich angemeldet hat — sie steht also nicht in
    ihrer Geräteliste, nicht in der Zahl offener Sessions in der Schublade und
    nicht in ihrem „zuletzt gesehen". Ob sie überhaupt informiert wird, ist die
    Einstellung unten, und eine Zeile in dieser Liste würde das für sie
    entscheiden.

**Ob die Person informiert wird, ist eine Policy, gesetzt auf dieser Zeile.**
`notify_impersonated_users` ist standardmäßig aus; eingeschaltet bekommt die
Person eine einmalige E-Mail, wenn die Impersonation beginnt, mit dem Namen des
Administrators. Der Audit-Trail hält die Impersonation ohnehin fest — sowohl den
Beginn als auch das Ende, mit der Session, zu der sie gehören — was
[Governance](governance.md#audit) beschreibt.

## Hinweise, und das Schließen des Deployments { #notices-and-closing-the-deployment }

**Die Ankündigung** ist ein Satz in einem von drei Stilen, angemeldeten Nutzern
über jeder Seite gezeigt, bis sie ihn ausblenden. Sie ist das eine Feld dieser
Zeile, das *nicht* am öffentlichen Endpunkt hängt: eine Ankündigung ist ein
Betreiber, der zu den Menschen spricht, die das Deployment nutzen — ein
Wartungsfenster, wen man anpingt — sie hat also ihre eigene Route,
`GET /api/v1/branding/notice`, hinter einer Session.

Das Ausblenden hängt an der **Nachricht selbst**, im Speicher des Browsers. Ein
Flag würde die nächste Ankündigung für alle unsichtbar machen, die die letzte
ausgeblendet haben; der Zeitstempel der Einstellungszeile würde einen Hinweis
wieder einblenden, sobald das Deployment umbenannt wird. Der Text ist das, was
sich geändert hat, also ist der Text der Schlüssel. Ein Speicher, der sich
weigert, gelesen oder geschrieben zu werden — ein Privatmodus, eine eingebettete
Webview — bedeutet „nichts ausgeblendet" statt einer Exception: während des
Renderns geworfen, würde sie das Dashboard für jeden angemeldeten Nutzer
lahmlegen, und das Banner lässt sich weiterhin schließen, solange die Seite offen
ist.

**Der Wartungsmodus hält die API zu**, nicht nur die Konsole.
`app/core/maintenance.py` ist eine reine ASGI-Middleware über den Routen, eine
Seite, die jemand bereits offen hat, hört also auf zu funktionieren — was der
ganze Unterschied zwischen einem Wartungsmodus und einem Banner ist. Seine
Allow-List ist kurz und wird Eintrag für Eintrag getestet:

- `/health*` — eine Readiness-Probe, die während eines Fensters fehlschlägt, ist
  ein Orchestrator, der den Container neu startet, in dem der Betreiber arbeitet.
- `/api/v1/branding` — die geschlossene Seite muss sagen können, wie dieses
  Deployment heißt und warum es zu ist.
- `/api/v1/auth/*` — ein Administrator muss sich anmelden können, **während** das
  Fenster offen ist.
- `/api/v1/admin/*` — und dann den Schalter erreichen.
- Die Docs und das OpenAPI-Schema, die keine Daten ausliefern.

Alles andere ist ein 503 mit `Retry-After`. Es liest überhaupt keine Session —
das hieße, einen Token oberhalb des Abhängigkeitsgraphen zu prüfen — das Erweitern
des Pfads auf `/api/v1/admin/*` erweitert also nicht die Autorität:
`CurrentAppAdmin` lehnt dort einen Nicht-Admin genau so ab wie immer.

**Es fällt offen aus.** Ein Tor, das seinen eigenen Schalter nicht lesen kann —
ein Redis-Aussetzer, eine nicht gelaufene Migration — lässt Verkehr durch, denn
die Alternative verwandelt einen Infrastruktur-Schluckauf in einen totalen
Ausfall, den niemand geplant hat.

Das Urteil wird in dem Redis zwischengespeichert, das jeder Worker ohnehin teilt:
geschrieben **nach dem Commit**, der Schalter wirkt also sofort und der Cache kann
nie einen Zustand bewerben, den die Datenbank zurückgerollt hat — eifrig
veröffentlicht ließ ein danach fehlgeschlagener Request ein deaktiviertes Fenster
das Deployment für bis zu die TTL wieder öffnen. Es trägt zusätzlich eine TTL von
30 Sekunden, ein Schreibvorgang, der Redis nie erreichte, heilt sich also selbst,
statt das Deployment durch ein von jemandem geplantes Fenster hindurch offen zu
lassen.

**Und eine bereits offene Seite erfährt davon.** Der Branding-Kontext wird einmal
vom Root-Server-Layout aufgelöst und ändert sich für die Lebensdauer einer Seite
nie, ein danach geöffnetes Fenster ließ also jeden offenen Tab auf einem Dashboard
zurück, dessen sämtliche Requests mit 503 zu antworten begannen, ohne dass etwas
auf dem Bildschirm sagte, warum — und das Schließen eines Fensters ließ einen Tab
auf dem Wartungsbildschirm zurück, bis jemand neu lud.
`GET /api/v1/branding/notice` trägt das Wartungsurteil neben der Ankündigung und
wird einmal pro Minute abgefragt, was ein Request für beide Antworten ist statt
zwei, die über eine Zeile uneins sein können.

In der Konsole sieht der Administrator einen Streifen statt der geschlossenen
Seite. Er ist die einzige Person, die das Fenster beenden kann, und ein
Wartungsmodus, der auch den Schalter verbirgt, ist ein Ausfall.

## Wie viel ein Konto belegen darf { #how-much-one-account-may-take-up }

Zwei Obergrenzen, beide auf derselben Zeile und beide **standardmäßig null — und
null heißt keine Grenze statt „nicht konfiguriert"**. Ein selbst gehostetes
Deployment für ein Unternehmen will keine von beiden; ein für Anmeldungen offenes
Deployment will beide, denn ein Konto kann sonst unbegrenzt Tenants prägen.

| Einstellung | Zählt | Zählt nicht |
|---|---|---|
| Organisationen pro Konto | Die Organisationen, die ein Konto **besitzt**, die persönliche eingeschlossen | Solche, in die jemand anderes es eingeladen hat |
| Agents pro Organisation | Agents, die die Organisation hält | Archivierte Agents |

**Jeder Übergang in den gezählten Zustand wird geprüft, nicht nur ein Anlegen.**
Eine Obergrenze, die allein auf neuen Zeilen durchgesetzt wird, ist eine, an der
man seitlich vorbeigeht: eine Organisation an ihrem Agent-Limit archiviert einen,
legt einen Ersatz an und stellt den archivierten wieder her, und einem Konto an
seinem Organisationslimit wird über `transfer_ownership` die eines anderen
überreicht. `unarchive` und `transfer_ownership` stellen deshalb dieselbe Frage
wie `create`.

**Und die Zählung erfolgt unter einer Sperre.** `count(...) >= limit` zu lesen und
dann zu schreiben sind zwei Statements, zwei Requests bestehen also beide die
Zählung und fügen beide ein — die Obergrenze deterministisch überschritten, durch
zweimaliges Klicken. Kein Constraint kann „höchstens N solche Zeilen" ausdrücken,
`app/db/locks.py` nimmt deshalb eine transaktionsbezogene Advisory Lock auf den
*Gegenstand* der Obergrenze: zwei Requests zu einem Konto stellen sich an,
Requests zu unterschiedlichen Konten begegnen einander nie, und die Sperre wird
vom Commit oder vom Rollback freigegeben. Nur dort, wo ein Limit gesetzt ist, ein
ungedeckeltes Deployment zahlt also nichts.

Beide Ausschlüsse sind der Sinn des Entwurfs und nicht Details daran. In zehn
Organisationen eingeladen zu werden ist die Entscheidung von jemand anderem, und
eine Obergrenze, die eine Person nicht steuern kann, ist eine Obergrenze, die sie
davon aussperrt, eigene anzulegen. Und das Archivieren ist die Art, wie ein Agent
in Rente geht — eine Obergrenze, die ein Agent in Rente weiterhin belegte, machte
den einzigen Weg zurück unter sie zu einer Löschung, die die Versionshistorie und
die Zuordnung der Runs mitnimmt.

Die Ablehnung benennt die Obergrenze und den Zählerstand, gegen den sie gemessen
wurde (`{"limit": 5, "held": 5}`), „warum kann ich nicht" wird also von der
Antwort beantwortet und nicht vom Gedächtnis eines Administrators. Sie wird in dem
Service ausgelöst, der die Sache anlegt, und nicht an der Route, denn die Route
ist nicht der einzige Weg hinein.

Null wird vom Schema abgelehnt: ein Konto, das keine Organisation besitzen darf,
ist ein Konto, das nicht angelegt werden kann, denn die Anmeldung gibt jedem von
ihnen eine persönliche Organisation.

## Die Zeile { #the-row }

Eine Zeile für die gesamte Installation, von der Datenbank bewacht statt von einer
Konvention, die niemand sehen kann: `singleton` ist unique und auf wahr
eingeschränkt, eine zweite Identität ist also ein `IntegrityError` statt eines
Deployments, das stillschweigend zwei hat und diejenige ausliefert, die eine
Abfrage zuerst sortiert hat. Der Schreibvorgang ist ein einzelnes
`INSERT ... ON CONFLICT DO UPDATE`, denn ein Lesen-dann-Einfügen läuft gegen sich
selbst, sobald zwei Administratoren aus zwei Tabs speichern.

**Nichts wird vorbelegt.** Keine Zeile bedeutet lauter Voreinstellungen, was genau
der Zustand eines Deployments ist, das niemand konfiguriert hat — und es ist
wichtig, weil der öffentliche Branding-Endpunkt unauthentifiziert ist und bei
jedem kalten Seitenaufruf erreicht wird, ein Read-Through, das eine Zeile anlegte,
ließe einen Fremden also ein `INSERT` provozieren.

Jeder Schreibvorgang wird in `app_admin_audit_logs` auditiert, wobei die **Felder**
benannt werden und nie deren Werte: eine Ankündigung und eine Domain-Liste sind
beide Text eines Betreibers, und eine Audit-Zeile überlebt den Request-Body, aus
dem sie stammt.

## Eine Ablehnung dieses Deployments sieht immer gleich aus { #a-refusal-from-this-deployment-always-looks-the-same }

Hier erwähnenswert, weil das Schließen eines Deployments das Feature ist, das am
ehesten eine erzeugt, die eine Person noch nie gesehen hat.
`app/api/exception_handlers.py` legt **jede** Ablehnung in
`{"error": {"code", "message", "details"}}`:

```json
{
  "error": {
    "code": "NOT_FOUND",
    "message": "Agent not found",
    "details": { "agent_id": "…" }
  }
}
```

Das deckt Domain-Exceptions ab, Schema-Validierung und seit #917 auch
`HTTPException`, was einen 405, einen nicht getroffenen Pfad und die
zweiundzwanzig Routen abdeckt, die direkt eine auslösen. Zwei Formen auf der
Leitung bedeuten, dass jeder Aufrufer entweder beide behandelt oder eine
stillschweigend falsch behandelt.

Ein Request mit falscher Methode antwortete früher mit **500** statt 405, auf
jeder Route. Die FastAPI-Instrumentierung von OpenTelemetry leitet einen
Span-Namen ab, indem sie `app.routes` durchläuft, und ihr `Match.PARTIAL`-Zweig —
der genau „der Pfad passt und die Methode nicht" ist — liest `.path` ungesichert;
FastAPI 0.141 legt `_IncludedRouter`-Objekte in diese Liste, und die haben keinen.
`app/core/otel_compat.py` liefert für diesen Zweig denselben Fallback, den Upstream
in dem Zweig bereits verwendet, den es abgesichert hat. Upstream ist das ab 0.65b0
weiterhin nicht behoben, und `tests/test_otel_route_details.py` schlägt fehl, wenn
es behoben ist, was der Zeitpunkt ist, an dem das Modul verschwindet.

## Zusammenfassung { #recap }

- Die Identität des Deployments ist **eine Zeile**, bearbeitet unter
  `/admin/settings`, und eine Null-Spalte bedeutet *den eingebauten Wert* statt
  *leer*.
- `signup_mode` wird an **einer Stelle** angewendet und kontrolliert beide Pfade,
  die ein Konto prägen. Eine Einladung setzt eine Domain-Liste außer Kraft;
  nichts setzt `closed` außer Kraft.
- Ein App-Admin **kann sich nicht selbst aussperren** über die Konsole.
- **Impersonation ist eine Session**: aus der Konsole gestartet, ohne Token in der
  Zwischenablage, in einem Banner benannt, beendet vom Administrator, davon, dass
  die Person sich überall abmeldet, oder von der Stunde. Ob die Person informiert
  wird, ist `notify_impersonated_users`, standardmäßig aus.
- Jede Ablehnung dieses Deployments sieht gleich aus, welche Schicht sie auch
  erzeugt hat.
