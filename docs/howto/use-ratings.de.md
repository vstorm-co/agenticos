---
source_sha: 883886c71472
---

# Nachrichtenbewertungen nutzen { #use-message-ratings }

Menschen können die Antworten eines Agents bewerten, und diese Bewertungen sind
auf zwei Wegen lesbar: an der Antwort selbst, und aggregiert für diejenigen, die
das Deployment verwalten.

## Nachrichten bewerten { #rating-messages }

### Gefällt mir / Gefällt mir nicht { #likedislike }

Jede Assistentennachricht zeigt zwei Schaltflächen:

- **Gefällt mir (👍)** — Klicken Sie darauf, wenn die Antwort hilfreich war
- **Gefällt mir nicht (👎)** — Klicken Sie darauf, wenn die Antwort Probleme hatte

### Umschaltverhalten { #toggle-behavior }

- Ein erneuter Klick auf dieselbe Schaltfläche **entfernt** Ihre Bewertung
- Ein Klick auf die andere Schaltfläche **ändert** Ihre Bewertung (gefällt mir → gefällt mir nicht oder umgekehrt)
- Nur Assistentennachrichten lassen sich bewerten, Ihre eigenen nicht

### Rückmeldung ergänzen { #adding-feedback }

Wenn Sie eine Antwort negativ bewerten, erscheint ein Dialog mit der Frage **"Was ist schiefgelaufen?"**

Sie können optional einen Kommentar von bis zu 2000 Zeichen hinterlassen, der das
Problem beschreibt. Diese Rückmeldung ist wertvoll, um zu verstehen, warum eine
Antwort nicht geholfen hat.

Häufige Gründe für eine negative Bewertung:

- Falsche oder halluzinierte Informationen
- Die Antwort ging nicht auf die Frage ein
- Zu ausführlich oder zu knapp
- Schlechte Formatierung oder Struktur

## Anzahl der Bewertungen { #rating-counts }

Jede Nachricht zeigt die Gesamtzahl der positiven und negativen Bewertungen
aller Nutzer. Ihre eigene Bewertung ist hervorgehoben: grün für gefällt mir, rot
für gefällt mir nicht.

## Für Administratoren { #for-administrators }

### Bewertungs-Dashboard { #ratings-dashboard }

Öffnen Sie **Admin → Response Ratings** (oder `/admin/ratings`), um das Analyse-Dashboard zu erreichen.

#### Zusammenfassende Kennzahlen { #summary-statistics }

- **Total ratings** — Alle Bewertungen im gesamten System
- **Likes** — Anzahl der positiven Bewertungen
- **Dislikes** — Anzahl der negativen Bewertungen
- **Average** — Gesamtzufriedenheit auf einer Skala von -1,0 bis 1,0

#### Bewertungsdiagramm { #ratings-chart }

Ein Balkendiagramm zeigt die Bewertungen der letzten 30 Tage. Grüne Balken stehen
für positive, rote für negative Bewertungen.

!!! note "Das Zeitfenster dieser Seite liegt fest bei 30 Tagen"

    Um dieselben Zahlen über einen selbst gewählten Zeitraum zu lesen, nutzen Sie
    die Dashboard-Karte **Answer quality, deployment-wide**, die dem Zeitraumfilter
    am oberen Seitenrand folgt.

### Bewertungen filtern { #filtering-ratings }

Mit den Filter-Dropdowns grenzen Sie die Ergebnisse ein:

| Filter | Optionen |
|--------|----------|
| Bewertungsart | Alle / nur positive / nur negative |
| Kommentare | Alle / nur mit Kommentar |

### Bewertungstabelle { #ratings-table }

Die Tabelle zeigt einzelne Bewertungen mit:

- **Date** — Wann die Bewertung abgegeben wurde
- **Rating** — 👍 positiv oder 👎 negativ
- **Comment** — Der Kommentartext, falls vorhanden
- **Message** — Vorschau der bewerteten Antwort
- **User** — Wer die Bewertung abgegeben hat
- **Actions** — Link zur vollständigen Unterhaltung

### Daten exportieren { #exporting-data }

Exportieren Sie Bewertungen für eine Auswertung außerhalb des Produkts:

- **JSON** — Vollständige strukturierte Daten, geeignet für Skripte und Analysewerkzeuge
- **CSV** — Tabellenformat für Excel oder Google Sheets

!!! tip "Ein Export folgt den gesetzten Filtern"

    Grenzen Sie auf negative Bewertungen mit Kommentar ein und exportieren Sie
    dann - genau das bekommen Sie. Die Filter gehören zur Abfrage, nicht zur
    Ansicht.

### Unterhaltungen ansehen { #viewing-conversations }

Klicken Sie bei einer Bewertung auf **"View conversation"**, um den Chat mit der
zugehörigen Unterhaltung zu öffnen. Das hilft, den Kontext einer Bewertung zu
verstehen.

## Die Admin-Seite für Unterhaltungen { #admin-conversations-page }

Öffnen Sie **Admin → All Conversations** (oder `/admin/conversations`), um alle Unterhaltungen der Nutzer zu sehen.

Diese Seite bietet:

- Eine durchsuchbare Liste aller Unterhaltungen
- Filter nach E-Mail-Adresse oder Benutzername
- Filter nach Zeitraum, voreingestellt oder selbst gewählt
- Direkte Links zu den Details einer Unterhaltung

## Direkte Links auf eine Unterhaltung { #direct-conversation-links }

Sie können einen direkten Link auf eine bestimmte Unterhaltung teilen, indem Sie
den Parameter `id` an die Chat-URL anhängen:

```
http://localhost:3000/chat?id=550e8400-e29b-41d4-a716-446655440000
```

Das ist nützlich, um:

- den Kontext einer Unterhaltung mit dem Team zu teilen
- wichtige Unterhaltungen als Lesezeichen zu speichern
- aus externen Werkzeugen oder aus einer Dokumentation heraus zu verlinken

Ein Klick auf **"View conversation"** bei einer Bewertung oder in der
Admin-Liste öffnet genau so einen Link.

## Zugriff über die API { #api-access }

Für den programmatischen Zugriff auf Bewertungsdaten gibt es die Admin-Endpunkte:

| Endpunkt | Methode | Beschreibung |
|----------|---------|--------------|
| `/admin/ratings` | GET | Bewertungen auflisten, mit Seitenaufteilung und Filtern |
| `/admin/ratings/summary` | GET | Kennzahlen über `from`/`to` (inklusive UTC-Daten, standardmäßig die letzten 30 Tage) |
| `/admin/ratings/export` | GET | Bewertungen exportieren (JSON/CSV) |
| `/admin/conversations` | GET | Alle Unterhaltungen auflisten |

!!! warning "Jeder `/admin`-Endpunkt gehört dem Deployment-Superadmin, nicht einer Organisationsrolle"

    Das Tor ist `CurrentAppAdmin` — ein angemeldeter Nutzer, dessen
    `users.is_app_admin` wahr ist. Es gibt keine Spalte `users.role`, und keine
    Organisationsrolle erreicht diese Routen. Siehe
    [Berechtigungen](../permissions.md#layer-1-usersis_app_admin-the-deployment-superadmin).
