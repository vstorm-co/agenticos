---
source_sha: 86db3a8931da
---

# Ihr erster Agent { #your-first-agent }

Dies geht den ganzen Weg einmal ab: ein Provider-Key, ein Model, ein Agent, der
antwortet, eine veröffentlichte Version und ein Run mit Kosten darauf.

Fünfzehn Minuten und etwa ein Cent an Token.

Sie brauchen zuerst einen laufenden Stack — siehe [Installation](install.md).

!!! tip "Das Produkt führt Sie ebenfalls hindurch"

    Wenn sich jemand zum ersten Mal anmeldet, öffnet sich auf dem Dashboard eine
    Einführung, und wer sie zu Ende geht, bekommt das Angebot, den ersten Agent
    *gemeinsam* zu bauen, in den echten Dialogen.

    Den manuellen Weg einmal zu lesen lohnt sich trotzdem, und das ist diese
    Seite. Der geführte Weg ist [am Ende](#the-guided-walkthrough) beschrieben.

## 1. Einen Provider-Key hinterlegen { #1-store-a-provider-key }

**Settings → Vault → Add credential.**

Wählen Sie einen Provider, fügen Sie den Key ein, geben Sie ihm eine
Beschriftung. Der Wert wird sofort versiegelt, und es gibt keinen Endpunkt, der
ihn zurückgibt — zurück kommen eine Beschriftung und die letzten vier Zeichen.

!!! info "Warum ein Vault und keine Konfigurationsdatei"

    Ein Key in der Umgebung gehört dem Deployment. Ein Key im Vault gehört einer
    **Organisation**, und das ist es, was ein Deployment mehrere Mandanten
    bedienen lässt, ohne dass einer das Budget des anderen ausgeben kann.

    Das Chiffrat ist an die Organisation gebunden, die es hinterlegt hat, und
    lässt sich für keine andere entschlüsseln.

## 2. Ein Model hinzufügen { #2-add-a-model }

**Agents → ein beliebiger Agent → Build → Model.**

Wählen Sie einen Provider, dann ein Model, dann welcher hinterlegte Key dafür
zahlt.

Die Modellliste kommt vom Provider, wo er eine veröffentlicht, und aus einer
mitgelieferten Auswahl, wo er das nicht tut. Sie ist ein Vorschlag und nie eine
Einschränkung — ein Provider bringt ein Model am Morgen nach dem Aufwärmen jedes
Katalogs heraus, also wird alles akzeptiert, was Sie eintippen.

Was Sie gerade angelegt haben, ist ein **Model-Profil**: ein benanntes Model,
gedeckt von einem benannten Key.

Es zu benennen ist der Punkt. So können Sie den Key rotieren oder jeden Agent auf
ein neues Model umstellen, ohne einen einzigen Agent anzufassen.

## 3. Den Agent bauen { #3-build-the-agent }

**Agents → New agent.**

!!! tip "Oder von einem Template ausgehen"

    **Agents → Agent templates** liefert achtundzwanzig fertige Agents, nach
    Branche gruppiert, jeder mit geschriebenen Instructions, eingeschalteten
    Capabilities und den nötigen Skills daneben installiert.

    Einer kommt als **Draft** an statt veröffentlicht, und das mit Absicht: ein
    Template kann Ihr Model nicht wählen, und es hat Ihre Knowledge-Collection nie
    gesehen. Der Rest dieser Seite ist, was Sie ohnehin als Nächstes tun.

Der Name wird zum Handle, unter dem er aus Slack und über die API angesprochen
wird, und er ist bei der Erstellung eingefroren — aus `Support Copilot` wird
`@support-copilot`.

Der Tab **Build** besteht aus Instructions und einem Model, und die Instructions
sind das gesamte Verhalten des Agents:

```markdown
You are Support Copilot.

Answer from the product wiki and cite the document you used.
If the wiki does not cover it, say so rather than guessing.
Never quote a price - route those to sales.
```

Schreiben Sie sie in Markdown. Das Model liest die Struktur, und Überschriften
und Listen sind das, was einen langen Prompt nachvollziehbar macht.

!!! note "Es gibt keine Schaltfläche zum Speichern"

    Der Draft speichert sich selbst, während Sie tippen. Ein Builder mit einer
    Speichern-Schaltfläche ist ein Builder, bei dem der Tab über zwanzig Minuten
    Instructions zugegangen ist.

## 4. Ihm Capabilities geben { #4-give-it-capabilities }

**Toolbox.**

Jede Capability zeigt genau, was sie beiträgt — jedes Tool, seine Beschreibung
und die Argumente, die das Model ausfüllen muss — *bevor* Sie sie einschalten.
Eine Capability zu lesen heißt nicht, sie zu gewähren.

Zwei Dinge lohnen sich hier zu wissen:

- **Name und Beschreibung eines Tools sind Prompt.** Nach
  `search_refund_policy` wird bei Fragen gegriffen, bei denen
  `search_documents` übergangen wird. Beides ist pro Agent editierbar.
- **Alles mit Nebenwirkung fragt standardmäßig nach Freigabe.** Der Run parkt und
  wartet auf einen Menschen. Stellen Sie es pro Capability ein oder pro Tool.

## 5. Ihm etwas zu lesen geben { #5-give-it-something-to-read }

**Knowledge → Collections** für Dokumente. **Skills** für aufgeschriebenes
Fachwissen.

Der Unterschied zählt:

| | |
|---|---|
| Eine **Collection** wird *durchsucht* | Das Model wählt, wonach es sucht, und kann nie ausweiten, wo es sucht |
| Ein **Skill** wird *gelesen* | Der Agent lädt ihn nur, wenn er den Skill für einschlägig hält, sodass zwanzig Skills fast nichts an Kontext kosten |

Jede Collection sagt, wie viele Dokumente sie hält, denn eine leere anzuhängen
ergibt einen Agent, der sucht, nichts findet und das sagt — was sich wie ein
kaputter Agent liest statt wie eine leere Collection.

## 6. Ein Limit setzen und sagen, wer benachrichtigt wird { #6-set-a-limit-and-say-who-is-told }

**Limits.** Ein monatlicher Cap in Dollar, ein Schrittlimit und wer davon erfährt.

Das Schrittlimit ist das, was man vergisst. Es fängt die andere Art von
Ausreißern ab: eine Tool-Schleife, die pro Aufruf billig ist und nie endet. Ein
Budget rechnet dafür nur ab; ein Schrittlimit stoppt sie.

Entscheiden Sie unter **Alerts**, wer erfährt, wenn dieser Agent an seinem Cap
anhält oder auf einer Freigabe parkt. Standardmäßig hören die Admins und der
Owner des Agents vom Budget, und wer den Run gestartet hat plus die Admins hören
von Freigaben — damit ein Run, den ein Zeitplan gestartet hat, nicht unbeobachtet
parkt.

[Governance](governance.md) beschreibt, wie Budgets, Freigaben und Alerts
zusammenpassen.

## 7. Veröffentlichen { #7-publish }

**Publish** validiert zuerst den Draft, also erfahren Sie hier auch, dass das
Spec eine Collection referenziert, die jemand gelöscht hat.

!!! success "Ein Spec, das etwas Fehlendes referenziert, wird hier abgelehnt, nie zur Laufzeit"

    Und genau deshalb findet die Validierung beim Veröffentlichen statt: jemand
    schaut auf ein Formular und kann es beheben, statt es drei Wochen später in
    einem Run zu erfahren, den ein Zeitplan gestartet hat.

Veröffentlichen friert eine **Version** ein. Runs verzeichnen, welche Version
ausgeführt wurde, sodass das, was ein Agent letzten Dienstag getan hat, auch nach
einem Dutzend Änderungen beantwortbar bleibt.

## 8. Ihn ausführen { #8-run-it }

**Test** in der Kopfzeile öffnet einen Chat gegen den veröffentlichten Agent.
Fragen Sie ihn etwas.

Schauen Sie dann in **Activity**: der Run, die ausgeführte Version, das
aufgelöste Model, die Token und was es gekostet hat. Wenn ein Tool eine Freigabe
brauchte, liegt sie dort in der Warteschlange.

## 9. Ihn irgendwo hinstellen { #9-put-it-somewhere }

**Availability** ist der Ort, an dem ein Agent aufhört, ein Ding in einem Builder
zu sein:

| | |
|---|---|
| **Exposures** | Wer ihn ausführen darf und wie — API-Keys, öffentliche Links |
| **Channel bots** | Slack und Telegram. `@support-copilot` in einem Channel läuft als der *Absender*, nie als der Bot |
| **Embeds** | Ein Widget für Ihre eigenen Seiten |
| **Environments** | Benannte Zeiger auf Versionen, sodass Staging und Produktion sich unterscheiden können |

## Ihn exportieren { #export-it }

**Download** gibt Ihnen das Spec als YAML.

Es benennt Referenzen — ein Model-Profil, eine Collection, ein Secret — und nie
Werte, und genau das macht es sicher, es in Ihr eigenes Repository zu committen
und wie Code zu reviewen.

```yaml
name: Support Copilot
instructions: |
  You are Support Copilot.
  Answer from the product wiki and cite the document you used.
model_profile_id: 8f1c...
capabilities:
  - id: knowledge
    config: { default_top_k: 8 }
collection_ids: [b2a9...]
budget:
  monthly_usd: 50
```

## Zusammenfassung { #recap }

Neun Schritte, und ihre Form ist die Form der Plattform:

1. Einen **Key** im Vault versiegelt, pro Organisation.
2. Ein **Model-Profil** benannt, damit Key und Model sich ändern können, ohne
   dass der Agent sich ändert.
3. **Instructions** geschrieben.
4. **Capabilities** eingeschaltet und die mit Nebenwirkung nach Freigabe fragen
   lassen.
5. **Knowledge** zum Durchsuchen und **Skills** zum Lesen angehängt.
6. Ein **Budget** und ein **Schrittlimit** gesetzt und gesagt, wer
   benachrichtigt wird.
7. **Veröffentlicht**, was eine Version eingefroren und das Spec validiert hat.
8. Ihn **ausgeführt** und gesehen, was er gekostet hat.
9. Ihn von woanders als aus dem Builder **erreichbar** gemacht.

Alles danach ist mehr von den Schritten 4, 5 und 9.

## Die geführte Einführung { #the-guided-walkthrough }

Das Produkt bringt sich selbst bei, und es lohnt sich zu wissen wie — denn die
Einführung ist auch der Weg, auf dem jeder, dem Sie das übergeben, es lernen
wird.

**Sie zeigt sich einmal, und das ? spielt sie erneut ab.** Dass sie beendet,
übersprungen oder geschlossen wurde, wird beim Konto gemerkt statt im Browser,
sodass sie auf dem nächsten Gerät nicht wiederkommt. Das **?** in der Kopfzeile
jeder begangenen Seite spielt die Hinweise dieser Seite ab, wann immer sie
gewünscht sind.

Es wird nur dort angeboten, wo es etwas abzuspielen gibt. Ein Bereich ohne Stopps
— die Seiten der Deployment-Administration — hat gar **kein ?**, statt eines, das
einen leeren Rundgang öffnet. Die Einführung sagt beim Verlassen genau das, damit
niemand das **?** zufällig oder gar nicht entdeckt.

**Wer sie zu Ende geht, bekommt das Angebot, den ersten Agent gemeinsam zu
bauen.** Das ist ein interaktiver Ablauf und kein Scheinwerfer: er zeigt auf die
echten Bedienelemente, Sie bedienen die echten Dialoge, und er geht in dem
Moment weiter, in dem die Sache tatsächlich angelegt ist.

Während er läuft, ist die Seite **eingefroren** — alles wird abgedunkelt außer
dem einen Bedienelement, um das es im Schritt geht, sodass Sie nicht mitten im
Ablauf abschweifen und einen geführten Schritt auf der falschen Seite stranden
lassen können. Das Einfrieren tritt von selbst beiseite, sobald ein Dialog oder
eine Auswahl aufgeht, sodass das Bedienelement, auf das der Schritt zeigt, immer
benutzbar ist.

Der Ablauf ist anpassungsfähig. Er geht den Weg von oben ab, prüft, was die
Organisation schon hat, und hält nur dort an, wo etwas fehlt — er bringt einem
Workspace ohne Model bei, wie man eines hinzufügt, oder sagt einem Builder ohne
die Berechtigung dafür genau das, statt ihn schweigend zu einem Publish zu
führen, das einen Agent ohne Model ablehnen wird.

**Bei Knowledge, Skills und MCP tut er am meisten.** Ist schon eines da, zeigt
der Ablauf nur darauf, wo es angehängt wird. Ist keines da, wechselt er zuerst
auf den eigenen Bildschirm dieses Bereichs und *fragt dort* — "noch keine
Knowledge Base, eine anlegen?" — damit die Frage dort landet, wo die Antwort
passiert.

Ein Ja führt die Erstellung an Ort und Stelle, und nicht nur bis zur
Schaltfläche: der Rundgang folgt Ihnen in den Dialog selbst, umrahmt jedes Feld
der Reihe nach mit dem, was hineingehört — der Name eines Skills, unter dem das
Model ihn aufruft, die Beschreibung, die entscheidet, wann er gelesen wird, der
Wechsel zu Source, wo das Fachwissen geschrieben wird — und geht weiter, wenn die
Sache tatsächlich angelegt ist.

Dann führt er Sie zurück, indem er *zeigt*: auf **Agents** in der Seitenleiste,
auf den Bearbeitungsstift genau des Agents, den Sie eben gebaut haben, auf den
Tab Knowledge, wo die neue Base angehängt wird. Der Rückweg wartet auf Ihren
Klick, statt für Sie zu navigieren, und lehrt so den Weg durch die Anwendung,
statt ihn vorzuführen. Ein Überspringen kehrt von selbst in den Builder zurück.

MCP verzweigt genauso, bleibt aber im Builder. Ein Server wird über einen
Inline-Dialog direkt dort in der Toolbox verbunden, also zeigt ein Ja auf diese
Schaltfläche, und der Ablauf setzt in dem Moment fort, in dem die Verbindung
steht — keine Reise auf eine andere Seite und keine zurück.

**Er endet nicht bei Publish.** Nachdem Publish gelandet ist, trägt der Ablauf
Sie in den Chat, lässt Sie den eben gebauten Agent auswählen und schließt erst,
wenn Sie ihm eine erste Nachricht geschickt haben. Ein erster Agent, den niemand
ausgeführt hat, ist ein Rundgang, der einen Schritt vor dem Punkt stehen blieb.

**Jeder andere Bereich hat einen eigenen.** Eine Ablehnung führt niemanden, und
das Angebot kommt am Ende des **?**-Rundgangs von Agents zurück. Der **?** jedes
anderen Bereichs endet genauso und bietet an, die Ressource dieses Bereichs
anzulegen — einen Skill, eine Knowledge Base, eine MCP-Verbindung, eine
Organisation, eine Routine.

Zwei davon sind mit Absicht anders geformt:

- **Routines** endet *hinter* dem eigenen Anlegen. Ein Zeitplan, der auf die Uhr
  wartet, lehrt nichts, also ist der letzte Stopp des Rundgangs das **Run now**
  der frischen Zeile, und die erste Auslösung landet im Run-Log, während Sie
  zusehen.
- **Chat** bietet einen geführten Durchlauf durch die Chat-Oberfläche selbst an:
  eine Unterhaltung beginnen, wechseln, welcher Agent antwortet, Model oder
  Denkaufwand für einen einzelnen Chat ändern. Chat kann nur mit einem
  *veröffentlichten* Agent sprechen, also eröffnet er ohne einen damit, das Bauen
  eines solchen anzubieten, und übergibt direkt an den Agent-Ablauf. Danach legt
  er nichts an, also geht er mit Next weiter.

!!! tip "Spielen Sie das ? des Dashboards einmal ab"

    Sein Stopp zum Anpassen erklärt den ganzen Editor: Karten aus dem Katalog
    hinzufügen (dieselbe Karte auch mehrfach, wenn Sie sie pro Agent wollen), sie
    zwischen Bereichen ziehen, Größe ändern, ausblenden, die Bereiche selbst
    umbenennen und einfärben, benannte Layouts und das Zurücksetzen.

    Jede Anordnung gilt pro Person, also verschiebt Ausprobieren niemandes andere
    Seite.

## Weiter { #next }

<div class="grid cards" markdown>

- :material-lightbulb:{ .lg .middle } **[Konzepte](concepts.md)**

    Spec, Version, Exposure, Trigger, Run — die fünf Substantive, die Sie gerade
    benutzt haben.

- :material-shield-check:{ .lg .middle } **[Governance](governance.md)**

    Budgets, Freigaben, Alerts, Audit.

- :material-account-key:{ .lg .middle } **[Berechtigungen](permissions.md)**

    Wer was darf, und auf welchen Zeilen.

</div>
