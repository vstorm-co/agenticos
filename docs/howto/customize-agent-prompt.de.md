---
source_sha: d61a7f894dfb
---

# Die Anweisungen eines Agents schreiben { #write-an-agents-instructions }

!!! danger "Anweisungen sind Daten, kein Code"

    Es gibt keine `prompts.py` zum Bearbeiten und keine Konstante
    `DEFAULT_SYSTEM_PROMPT` zum Überschreiben. Das Verhalten eines Agents ist das
    Feld `instructions` seines [Specs](../reference/spec.md) — im Builder
    bearbeitet, beim Veröffentlichen versioniert und als YAML in das eigene
    Repository eines Kunden exportiert. Python zu bearbeiten, um zu ändern, was
    ein Agent sagt, ist die mit Abstand häufigste falsche Annahme über diese
    Codebasis.

## Wo der Text lebt { #where-the-text-lives }

| | Wo | Wer ihn bearbeitet |
|---|---|---|
| Die Anweisungen eines Agents | `AgentSpec.instructions`, im Builder bearbeitet | Wer den Agent bearbeiten darf |
| Die Anweisungen eines Inline-Spezialisten | `InlineSpecialistSpec.instructions`, im selben Spec | Dieselben |
| Der Starttext, den ein neuer Agent bekommt | `backend/app/agents/default_instructions.py` | Ein Deploy — es ist die Vorstellung dieses Deployments von einem Assistenten |
| Ein Ablauf, den viele Agents teilen | Ein [Skill](../skills.md), eine Zeile in der Datenbank | Eine Support-Leitung, an einem Dienstagnachmittag, ohne Deploy |

Die letzte Zeile ist die, nach der zu greifen sich lohnt. Zwanzig Abläufe in
einem `instructions`-Feld bedeuten, dass jeder Run für alle zwanzig bezahlt;
zwanzig Skills kosten fast nichts, weil das Modell die Namen sieht und nur lädt,
was es braucht.

## Was in die Anweisungen gehört { #what-belongs-in-instructions }

Lesen Sie `default_instructions.py`, bevor Sie eigene schreiben — es ist das
durchgearbeitete Beispiel, und es erklärt seine eigenen Entscheidungen. Zwei
davon entscheiden über den größten Teil der Qualität:

- **Schreiben Sie für die Ablehnungen.** Die Absätze, die ihren Platz verdienen,
  sind die darüber, keine Tatsachen zu erfinden, zu sagen, aus welcher Quelle
  eine Antwort stammt, und lieber innezuhalten und zu fragen, als bei etwas
  Zerstörerischem zu raten. "Sei hilfreich" ist Dekoration: das Modell versucht
  ohnehin schon, hilfreich zu sein, und was es braucht, ist zu wissen, wo die
  Kanten liegen.
- **Setzen Sie das, was für *diesen* Agent spezifisch ist, nach oben.** Wer ihn
  als Nächstes öffnet, schreibt den ersten Absatz neu und behält den Rest.

```text
You are a customer support agent for Acme.

Answer questions about our products, help people troubleshoot, and escalate
anything involving a refund over £500 — the refund-policy skill has the rule.

Never quote a price you have not read from the knowledge base. If a question
needs an account change, say what you would do and ask them to confirm.
```

!!! warning "Zählen Sie die Tools des Agents nicht in seinen Anweisungen auf"

    Ein Agent bekommt seine Capabilities aus seinem Spec, und die Tools bringen
    ihre eigenen Beschreibungen aus der Bibliothek mit. Ein Prompt, der sie
    aufzählt, ist in dem Moment falsch, in dem jemand eines umschaltet — und der
    Fehlschlag ist ein Agent, der selbstbewusst ablehnt, etwas zu tun, was er
    inzwischen kann.

!!! tip "Wiederholen Sie auch nicht die Regeln einer Capability"

    Eine Capability, die vom Modell ein bestimmtes Verhalten braucht, steuert das
    selbst bei. Das Zitierformat für Retrieval, wie die Sandbox zu benutzen ist,
    wann eine Person zu fragen ist — das kommt mit der Capability, in jedem
    Agent, der sie aktiviert.

## Knowledge, Skills und Context-Dateien { #knowledge-skills-and-context-files }

Drei Wege, einem Agent Text zu geben, den er nicht hatte, und sie sind nicht
austauschbar:

| | Für | Geholt durch |
|---|---|---|
| `collection_ids` — [Knowledge](../file-processing.md) | Tausende Dokumente: was wir wissen | Semantische Suche, mit Zitat |
| `skill_ids` — [Skills](../skills.md) | Dutzende Abläufe: wie wir das machen | Das Modell wählt einen Namen und lädt dann den Inhalt |
| `context_ids` — Context-Dateien | Eine Handvoll Dateien, klein genug, um immer dabei zu sein | In die Anweisungen eingefügt, ohne jede Suche |

Alle drei werden gegen den Zugriff des **Veröffentlichenden** geprüft, beim
Veröffentlichen und nicht zur Laufzeit. Siehe
[Berechtigungen](../permissions.md).

## Daran feilen { #iterating-on-it }

- **Ein Draft kann nicht laufen.** Ein Agent führt seine veröffentlichte Version
  aus, einen neuen Prompt auszuprobieren heißt also, eine zu veröffentlichen —
  was von Haus aus billig ist, und weshalb ein Rollback ein Promote und keine
  Wiederherstellung ist. Feilen Sie auf einer
  [Umgebung](../concepts.md#version) `dev`, die jeder Veröffentlichung folgt,
  und lassen Sie `production` darauf warten, dass etwas auf sie promotet wird.
- **Testen Sie mit echten Anfragen, nicht mit idealen.**
- **Halten Sie ihn so kurz, wie das Verhalten es verlangt.** Ein längerer Prompt
  wird bei jedem Zug jedes Runs bezahlt und drängt die Unterhaltung früher aus
  dem Fenster.
- **Veröffentlichen Sie, wenn es stimmt.** Das Veröffentlichen friert die Version
  ein, sodass "was hat dieser Agent letzten Dienstag getan" auch nach einem
  Dutzend Bearbeitungen beantwortbar bleibt — und ein Rollback veröffentlicht
  eine *neue* Version, die von der alten kopiert ist, statt Historie zu löschen.
- **Temperature und der Rest sind `model_settings`**, pro Agent und pro
  Spezialist, oben auf dem Modellprofil. Keine Umgebungsvariable.
