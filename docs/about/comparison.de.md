---
source_sha: 0683b5318348
---

# Wann man etwas anderes nimmt { #when-to-use-something-else }

Diese Seite ist so geschrieben, dass sie nützlich ist, wenn die Antwort nicht
AgenticOS lautet. Ein Vergleich, der immer gleich ausgeht, ist kein Vergleich, und
die Kategorien unten überschneiden sich so stark, dass eine falsche Wahl Monate
kostet.

Die Kurzfassung: Eine **Bibliothek** ist richtig für einen Agent innerhalb eines
Produkts, eine **gehostete Plattform** ist richtig, wenn Sie die Maschine nicht
wollen, ein **Agent-Workspace** ist richtig, wenn der Nutzer Ihr eigener
Mitarbeiter ist, und AgenticOS ist richtig, wenn Agents von einem
Nicht-Entwickler bearbeitbar sein müssen, von jemandem mit Verantwortung
gesteuert werden und auf Hardware laufen, die Sie kontrollieren — alle drei
zugleich.

## Die Kategorien { #the-categories }

| | Was es ist | Wann man es stattdessen nimmt |
|---|---|---|
| [Pydantic AI](https://ai.pydantic.dev) | Die Agent-Bibliothek, auf der AgenticOS läuft | Sie bauen einen Agent, in Python, als Teil eines Produkts |
| LangGraph, LangChain, LlamaIndex, elizaOS | Bibliotheken und Frameworks, um Modellaufrufe zusammenzusetzen | Dasselbe — Sie wollen Code, keine Plattform, und übernehmen das Deployment gern selbst |
| [Cloudflare OS](https://github.com/cloudflare/cloudflare-os) | Ein quelloffener Agent-Workspace auf Cloudflare Workers | Ihre Nutzer sind Ihre eigenen Angestellten, Sie sind ohnehin auf Cloudflare, und Sie wollen eher Apps pro Person als einen gesteuerten Agent-Katalog |
| [Glean](https://www.glean.com) | Gehostete Unternehmenssuche mit Agents darauf | Sie wollen 275+ ACL-bewusste Connectors, für Sie indexiert, und die Daten dürfen in der Cloud eines Anbieters liegen |
| Dify, Flowise | Visuelle Agent-Builder, selbst hostbar | Sie wollen den Builder und eine Workflow-Leinwand, und das Governance-Modell zählt für Sie weniger als das Tempo, in dem jemand einen Flow zusammensetzen kann |
| Gehostete Unternehmensplattformen für Agents | Proprietäre Plattformen, verkauft mit einem Einführungsteam | Sie wollen jemand anderen in der Verantwortung für das Ergebnis, und die Lizenzkosten sind nicht die Einschränkung |
| OpenAI Assistants, Bedrock Agents | Gehostete Agent-Laufzeiten | Sie sind mit einem Anbieter zufrieden und brauchen die Daten nicht auf eigener Hardware |

## Open Source ist nicht dasselbe wie selbst hostbar { #open-source-is-not-the-same-as-self-hostable }

Das sind zwei verschiedene Versprechen, und der Unterschied entscheidet über
Deployments.

**Open Source** heißt, dass Sie den Code lesen und forken können. **Selbst
hostbar** heißt, dass Sie es vollständig auf Infrastruktur betreiben können, die
Ihnen bereits gehört, ohne Abhängigkeit von der Plattform des Anbieters.

AgenticOS braucht PostgreSQL mit pgvector, Redis und Docker. Sonst nichts, kein
Konto irgendwo, und die einzigen ausgehenden Anfragen sind die, die Ihre Agents
stellen. Das ist die gesamte Deployment-Oberfläche, und deshalb kann es in einem
Krankenhausnetz oder in einer air-gapped Umgebung laufen.

Cloudflare OS steht unter Apache-2.0 und ist wirklich offen, und es ist auf
Durable Objects, Dynamic Workers und Cap'n Web gebaut. Es außerhalb von
Cloudflare zu betreiben heißt, `workerd` selbst zu betreiben, und die README des
Projekts führt die Dokumentation dazu als noch nicht geschrieben. Wenn die
Deployment-Bedingung lautet "das darf von keiner bestimmten Cloud abhängen", ist
das die Sache, die man zuerst prüft.

!!! info "Keine der beiden Positionen ist falsch"

    Auf den Primitiven einer Plattform zu bauen ist der Weg, auf dem Cloudflare
    OS zu Sandboxing pro Dokument und capability-basiertem Zugriff kommt, die auf
    gewöhnlicher Infrastruktur wirklich schwer nachzubauen sind. Es ist ein
    Tauschgeschäft, und welche Seite davon Sie wollen, hängt davon ab, wo die
    Software laufen muss.

## Cloudflare OS { #cloudflare-os }

Dem Namen nach das Nächstliegende zu diesem Projekt, und der Form nach ein
anderes Produkt.

**Cloudflare OS ist ein Workspace.** Jede Person bekommt einen Agent, eine
Laufzeit, in der sie Code schreiben und ausführen kann, und persönliche Apps, die
sie bauen und teilen kann. Das Sicherheitsmodell ist ausgezeichnet: Agents starten
ohne Zugriff auf irgendetwas, Zugangsdaten erreichen den Agent nie, und jede
Ressource, die ein Agent liest, wird verzeichnet und gegen die Person geprüft, die
das Ergebnis später öffnet.

**AgenticOS ist ein Katalog.** Sie veröffentlichen Agents, und die antworten
Menschen, die oft keine Angestellten sind — ein Kunde in einem Widget, ein
Nutzer in Slack, ein System hinter einem API-Schlüssel. Die Einheit ist ein
veröffentlichter, versionierter Agent mit einem Budget und einem Publikum, nicht
der Workspace einer Person.

Nehmen Sie Cloudflare OS, wenn die Nutzer des Agents Ihr eigenes Personal sind
und Sie auf Cloudflare arbeiten. Nehmen Sie AgenticOS, wenn der Agent nach außen
gerichtet sein, pro Agent gesteuert werden und dort laufen muss, wo Sie es sagen.

## Glean { #glean }

Glean ist zuerst Unternehmenssuche, mit Agents auf dem Index. Seine Stärke ist
genau der Teil, den AgenticOS gar nicht erst versucht: Connectors zu 275+
Systemen, die die eigenen Zugriffsregeln jedes Dokuments in den Index tragen,
sodass eine Antwort nie etwas zitieren kann, das die fragende Person nicht öffnen
könnte.

Daraus folgt zweierlei. Wenn Ihr Problem *"unser Wissen liegt in vierzig Systemen
und die Suche funktioniert nicht"* lautet, ist Glean dafür gemacht und AgenticOS
wird da nicht mithalten — unser Retrieval arbeitet pro Collection und erbt die
ACLs der Quelle noch nicht.

Wenn Ihr Problem *"wir brauchen gesteuerte Agents, und die Daten dürfen nicht
weg"* lautet, geht der Vergleich andersherum aus: Glean ist gehostet, pro
Arbeitsplatz bepreist mit einem Unternehmensminimum, und nichts, was Sie selbst
betreiben.

## Eine Bibliothek, und den Rest selbst bauen { #a-library-and-building-the-rest-yourself }

LangGraph, LangChain, LlamaIndex, Pydantic AI. Die häufigste richtige Antwort und
die, mit der dieses Projekt am wenigsten im Wettbewerb steht: AgenticOS **läuft
auf** Pydantic AI, eine Bibliothek ist also die Schicht darunter statt die
Alternative dazu.

Eine Bibliothek plus eine Queue plus eine Datenbank bringt Sie schnell zu einem
funktionierenden Agent, und für einen oder zwei Agents ist das weniger Arbeit, als
eine Plattform zu lernen.

Nehmen Sie die Bibliothek direkt, wenn:

- **Der Agent das Produkt ist.** Sein Verhalten ist ein Feature, das Sie
  ausliefern, versioniert mit Ihrem Code, geprüft in Ihren Pull Requests. Eine
  UI, in der jemand anderes es ändern kann, ist hier kein Vorteil — sie ist ein
  Weg, auf dem sich Ihr Produkt ohne Release ändert.
- **Sie die Schleife brauchen.** Eigener Kontrollfluss, ein Graph mit Zyklen,
  eine Retry-Strategie, die niemandes fremde Abstraktion ausdrückt. Eine
  Plattform gibt Ihnen einen klar definierten Runner; genau den wollen Sie hier
  nicht haben.
- **Kein Nicht-Entwickler in der Geschichte vorkommt.** Wenn ohnehin jede
  Änderung immer von einem Entwickler geschrieben worden wäre, bringt Ihnen der
  Umweg nichts.
- **Es einen Agent gibt.** Oder zwei. Die Rechnung unten dreht sich erst bei
  einer Handvoll.

Was Sie stattdessen übernehmen, sind die
[sieben Aufgaben](index.md#what-makes-something-an-operating-system-for-agents),
eine nach der anderen und meist in dieser Reihenfolge, jede erst, nachdem sie
einmal wehgetan hat:

| Sie werden am Ende schreiben | Weil |
|---|---|
| Ein Budget, das einen Run stoppt | Ausgaben im Nachhinein zu zählen ist kein Budget, und die erste überraschende Rechnung lehrt das |
| Eine Approval, die einmal entschieden wird | Die zweite Entscheidung über eine entschiedene Approval ist eine Race Condition, und sie ist nicht theoretisch |
| Mandantentrennung | Wenn zum ersten Mal ein `WHERE organization_id` vergessen wird, ist es ein Datenvorfall und kein Bug |
| Einen Secret-Speicher pro Mandant | Ein deploymentweiter Schlüssel heißt, ein Leck ist das Leck jedes Kunden |
| Einen Ausführungspfad über alle Oberflächen | Sonst sind sich Slack und Ihre API uneins darüber, was ein Agent gekostet hat |
| Eine Audit-Spur, die Fehlschläge verzeichnet | Ein Hauptbuch, das nur Erfolge protokolliert, beantwortet während eines Vorfalls die falsche Frage |

Nichts davon ist schwer. Alles davon ist Arbeit, die Sie nicht an Ihrem Produkt
leisten, und es ist genau das, was diese Plattform ausmacht.

!!! info "Die Grenze liegt ungefähr beim fünften Agent"

    Oder früher, bei der ersten Person, die ändern muss, was ein Agent sagt, und
    keinen Commit-Zugang hat. Davor sind eine Bibliothek und eine Queue weniger
    Arbeit, und Sie sollten sie nehmen.

Und wenn Sie diese sechs Zeilen ohnehin bauen werden, sind die
[sieben Aufgaben](index.md#what-makes-something-an-operating-system-for-agents)
eine vernünftige Spezifikation, gegen die man baut — ob Sie nun dieses hier
nutzen oder nicht.

## Fazit { #recap }

- Nehmen Sie eine **Bibliothek** für einen Agent innerhalb eines Produkts;
  nehmen Sie dies für einen Katalog davon — die Grenze liegt beim fünften Agent
  oder beim ersten Builder, der kein Entwickler ist.
- **Open Source und selbst hostbar sind verschiedene Versprechen** — prüfen Sie,
  welches Sie tatsächlich brauchen.
- **Cloudflare OS** ist ein Workspace für Angestellte; dies ist ein Katalog von
  Agents, die nach außen gerichtet sind.
- **Glean** gewinnt bei Connectors und ACL-bewusster Suche; dies gewinnt, wenn
  die Daten Ihre Infrastruktur nicht verlassen dürfen.
- **Es selbst zu bauen** ist richtig bis ungefähr zum fünften Agent, und die
  sieben Aufgaben sind so oder so die Spezifikation.
