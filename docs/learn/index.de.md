---
source_sha: 80ee04abded5
---

# Lernen { #learn }

Die Abschnitte unten sind der empfohlene Weg, AgenticOS zu lernen, in dieser
Reihenfolge. Lesen Sie sie als Kurs: jeder setzt die vorherigen voraus, und
keiner setzt voraus, dass Sie den Quellcode gelesen haben.

## Erste Schritte { #get-started }

Sie brauchen einen laufenden Stack und einen Agent, der Ihnen antwortet. Etwa
zwanzig Minuten.

<div class="grid cards" markdown>

- :material-download:{ .lg .middle } **[Installation](../install.md)**

    Docker Compose, oder die Dienste von Hand. Fünf Minuten bis zu einem Stack,
    den Sie im Browser öffnen können.

- :material-rocket-launch:{ .lg .middle } **[Ihr erster Agent](../first-agent.md)**

    Ein Provider-Key, ein Agent, eine veröffentlichte Version, ein Run, der
    etwas gekostet hat.

- :material-lightbulb:{ .lg .middle } **[Konzepte](../concepts.md)**

    Spec, Version, Exposure, Trigger, Run. Fünf Substantive. Alles andere ist
    daraus gebaut, das ist also die Seite, die Sie erneut lesen, wenn Sie etwas
    überrascht.

</div>

!!! tip

    Lesen Sie **Konzepte** auch dann, wenn Sie es eilig haben. Die meiste
    Verwirrung über diese Plattform ist eines dieser fünf Substantive, das für
    ein anderes gehalten wird — ein *Spec* für eine *Version*, eine *Exposure*
    für einen *Trigger*.

!!! tip "In der Konsole verlaufen?"

    [Die Konsole](../console.md) ist die Landkarte jedes Bereichs — wofür jeder
    da ist, und welche Seite ihn erklärt.

## Den Agent bauen { #build-the-agent }

Jetzt machen Sie ihn gut. Jede Seite hier ist eine Sache, die Sie dem Agent
geben, und sie sind voneinander unabhängig — nehmen Sie die, die Ihr Agent
braucht.

<div class="grid cards" markdown>

- :material-compass-outline:{ .lg .middle } **[Ein Modell wählen](../choosing-models.md)**

    Welches Modell dieser Agent nutzen sollte — offene Gewichte oder
    geschlossene, was die Rechnung treibt, und wie Sie es sich später anders
    überlegen.

- :material-brain:{ .lg .middle } **[Modelle und Provider](../models.md)**

    27 Provider, Modellprofile, Fallbacks, und was ein Token wirklich kostet.

- :material-school:{ .lg .middle } **[Skills](../skills.md)**

    Geschriebenes Know-how, das der Agent nur lädt, wenn er es für einschlägig
    hält.

- :material-text-box-outline:{ .lg .middle } **[Context-Dateien](../context.md)**

    Dauerhaftes Wissen, einmal geschrieben und an viele Agents gebunden — ein
    Glossar, ein Leitfaden für den Ton, eine Eskalationsmatrix.

- :material-file-document-multiple:{ .lg .middle } **[Knowledge](../file-processing.md)**

    Hochladen, parsen, chunken, einbetten. Collections, und wie Sie einen
    Drive-Ordner oder einen Bucket in eine davon synchronisieren.

- :material-connection:{ .lg .middle } **[MCP-Verbindungen](../mcp.md)**

    Jeder MCP-Server per URL, und 59 in der Auswahl, bei denen OAuth schon
    verdrahtet ist.

- :material-console:{ .lg .middle } **[Die Sandbox](../sandbox.md)**

    Dateien und eine Shell, isoliert, mit einer Lebensdauer.

- :material-clock-outline:{ .lg .middle } **[Trigger](../triggers.md)**

    Ein Run, der nach Zeitplan oder auf ein Ereignis hin passiert, ohne dass
    jemand tippt.

</div>

## Für Nutzer bereitstellen { #put-it-in-front-of-people }

Ein Agent, den niemand erreichen kann, ist ein Draft. So verlässt er die
Konsole.

<div class="grid cards" markdown>

- :material-source-branch:{ .lg .middle } **[Umgebungen](../environments.md)**

    `staging` und `production` als Namen, die an Versionen geheftet sind, sodass
    Veröffentlichen und Ausliefern zwei Entscheidungen sind.

- :material-forum:{ .lg .middle } **[Oberflächen](../channels.md)**

    Web-Chat, eine gehostete Seite, ein einbettbares Widget, die HTTP-API,
    Slack, Telegram und Mattermost — ein Runner hinter ihnen allen.

- :material-server:{ .lg .middle } **[Das Deployment selbst](../deployment.md)**

    Seine Identität, seine Anmelderichtlinie, seine Hinweise. Die Dinge, bei
    denen es um die Installation geht und nicht um einen Agent.

- :material-cloud-upload:{ .lg .middle } **[Deployen](../deploy.md)**

    Die Plattform auf einen Host bringen.

- :material-account-group:{ .lg .middle } **[Sie einführen](../rollout.md)**

    Wer was tut, realistische erste neunzig Tage, was es kostet, und die Fragen,
    die Ihre Sicherheitsprüfung stellen wird.

</div>

## Unter Kontrolle halten { #keep-it-under-control }

Der Teil, den die meisten Agent-Frameworks Ihnen überlassen. Lesen Sie ihn,
bevor Sie einem Agent ein Tool geben, das Geld ausgibt oder irgendwohin
schreibt.

<div class="grid cards" markdown>

- :material-account-key:{ .lg .middle } **[Berechtigungen](../permissions.md)**

    Drei Schichten: was eine Rolle erlaubt, was ein Grant weitet, was ein Scope
    ein Tool erreichen lässt.

- :material-shield-check:{ .lg .middle } **[Governance](../governance.md)**

    Budgets, die vor der Anfrage geprüft werden, Freigaben, die einmal
    entschieden werden, Alarme, und eine Audit-Spur, die den Wert behält statt
    der Zeile.

- :material-lock:{ .lg .middle } **[Secrets und der Vault](../secrets.md)**

    Ein Mechanismus für alle gespeicherten Zugangsdaten, und bewusst kein
    zweiter.

</div>

## Anleitungen — Rezepte { #how-to-recipes }

Kurze Antworten auf konkrete Fragen, sobald Sie sich auskennen.

- [Die Anweisungen eines Agents schreiben](../howto/customize-agent-prompt.md)
- [Sync-Quellen konfigurieren](../howto/configure-sync-sources.md)
- [Nachrichtenbewertungen nutzen](../howto/use-ratings.md)

Sie suchen, wie Sie die Plattform in Python *erweitern* — eine neue Capability,
einen neuen Connector, einen neuen Endpunkt? Das steht unter
[Ressourcen](../resources/index.md#extending-the-platform).

## Wohin als Nächstes { #where-to-go-next }

Wenn Sie wissen, wie sich die Plattform verhält, und genau wissen wollen, was
eine Einstellung, ein Befehl oder ein Spec-Feld tut, ist das
[Referenz](../configuration.md).
