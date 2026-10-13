---
source_sha: "50cf8da35126"
title: "Neue GitHub-Issues automatisch triagieren"
description: "Lösen Sie einen Agent aus, sobald ein Issue geöffnet wird, lassen Sie ihn allein aus der Zustellung Priorität und Labels vorschlagen, und testen Sie den Trigger, indem Sie eine Zustellung selbst signieren."
---

# Neue GitHub-Issues automatisch triagieren { #triage-new-github-issues-automatically }

Verbinden Sie einen [Ereignis-Trigger](../triggers.md) mit dem `issues`-Webhook eines Repositorys, damit ein neues Issue einen Agent erreicht, sobald es geöffnet wird, und lassen Sie den Agent aus dem Text der Zustellung Priorität, Labels und eine Duplikatprüfung vorschlagen. Diese Seite testet die Trigger-Hälfte für sich, indem sie eine synthetische Zustellung signiert und direkt an den Webhook sendet, ohne GitHub-Konto. Dies ist eine Anleitung zum Ausführen, mit einem festgehaltenen Run als Referenz für diese Hälfte. Labels setzen oder im Issue kommentieren braucht eine GitHub-Verbindung, die diese Umgebung nicht hat, und wird hier nicht ausgeführt.

## Was Sie brauchen { #what-you-need }

- Eine [laufende Installation](../install.md) mit einem Modellprofil.
- Um das echt auszulösen: ein Repository, dem Sie einen Webhook hinzufügen können (die Quelle **GitHub** als OAuth-App), oder eine für Ihre Organisation registrierte GitHub App (**GitHub (App)**). Siehe [zwei Wege, GitHub zu verbinden](../triggers.md#two-ways-to-connect-github-and-how-to-tell-which-you-are-running). Für die Prüfung unten ist keines davon eingerichtet.
- Damit der Agent tatsächlich Labels setzt oder kommentiert: eine [GitHub-MCP-Verbindung](../mcp.md#development) (Token-Authentifizierung) oder die Schreibrechte der GitHub App selbst, an den Agent gebunden. Auch das ist hier nicht eingerichtet.

## Die Eingabe vorbereiten { #prepare-the-input }

Ein gekürzter, aber realistischer `issues`-Webhook-Payload für ein fiktives Repository, klein genug, um die Triage von Hand zu prüfen:

```json
{
  "action": "opened",
  "issue": {
    "number": 42,
    "title": "Export button does nothing on Safari",
    "html_url": "https://github.com/acme/widgets/issues/42",
    "body": "Steps to reproduce:\n1. Open the reports page in Safari 18\n2. Click Export as CSV\n3. Nothing happens, no download, no error in the console\n\nWorks fine in Chrome. This is blocking our weekly export for finance."
  },
  "repository": {"full_name": "acme/widgets"}
}
```

Nichts davon ist ein echtes Repository oder eine echte Meldung.

## Den Agent bauen { #build-the-agent }

1. Erstellen Sie unter **Agents → New agent** einen Agent und wählen Sie Ihr Modellprofil.
2. Lassen Sie die Toolbox für diesen Versuch leer: Er soll nur eine Zustellung lesen und darüber urteilen. **Date and time** genügt, wenn die Triage sich auf das heutige Datum beziehen soll.
3. Setzen Sie als Instruktionen den Prompt der mitgelieferten Vorlage und klicken Sie dann auf **Publish**:

```text
You triage new GitHub issues from the delivery described in the task message.
Suggest a priority (low, medium, high) and one or two labels.
Say whether it looks like a duplicate of an existing issue, using only what the message gives you.
Flag immediately, in the first line, if it looks like a security report.
End with a short comment-ready summary a maintainer could paste onto the issue.
You have no tool to read the repository or post the comment yourself - say so if asked to do either.
```

Das ist der Prompt hinter **Triage the new issue** in den Trigger-Vorlagen (`GET /trigger-templates`), der genau dies in einen neuen **GitHub**-Ereignis-Trigger einträgt.

## Den Trigger einrichten { #set-up-the-trigger }

Wählen Sie unter **Routines → New event trigger → GitHub** diesen Agent, behalten Sie den Standardfilter (löst nur bei `opened` aus) und fügen Sie die resultierende Webhook-URL und das Signaturgeheimnis in **Settings → Webhooks → Add webhook** des Repositorys ein, mit dem Content-Type `application/json`. Die genauen Felder beschreibt [ein GitHub-Rezept](../triggers.md#a-github-recipe-5-minutes). Dieser Schritt braucht das Repository, das dieser Versuch nicht hat.

## Ausführen { #run-it }

Ohne Repository, aus dem zugestellt werden könnte, signieren Sie eine synthetische Zustellung selbst, genau so, wie [eine Zustellung selbst signieren](../triggers.md#signing-a-delivery-yourself) es für die generische Quelle beschreibt. GitHubs eigene Zustellungen verwenden dasselbe `HMAC-SHA256`-Verfahren, nur der Header-Name ändert sich:

```python
import hashlib, hmac, json, httpx

secret = b"<the trigger's signing secret>"
body = json.dumps(payload).encode()  # the fixture above
signature = "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()

httpx.post(
    f"{BASE}/api/v1/webhooks/triggers/github/{trigger_id}",
    content=body,
    headers={
        "Content-Type": "application/json",
        "X-Hub-Signature-256": signature,
        "X-GitHub-Event": "issues",
    },
)
```

## Das Ergebnis prüfen { #check-the-result }

| Prüfung | Referenz |
| --- | --- |
| Der signierte POST | `202`, sofort |
| Der Run in Activity | Oberfläche `schedule` (ein Ereignis-Trigger löst genauso aus wie ein Zeitplan), Status completed |
| Die Triage | Nennt eine Priorität und ein oder zwei Labels, geht auf die Duplikatfrage ein und ist nicht als Sicherheitsmeldung markiert |
| Die letzte Zeile der Antwort | Eine kurze Zusammenfassung, bereit für einen Kommentar |
| Tool-Aufrufe | Keine. Dieser Agent hat kein GitHub-Tool und urteilt nur über den zugestellten Text |
| Die Bitte, das Label selbst zu setzen, in der Konversation desselben Runs | Sagt, dass er dafür kein Tool hat, statt eines zu erfinden |
| Derselbe Payload mit dem falschen Geheimnis signiert | `403`, bevor ein Run überhaupt in Betracht kommt |
| Eine Zustellung mit `"action": "edited"` | `202` und kein neuer Run, denn der Standardfilter löst nur bei `opened` aus |

!!! example "Festgehalten auf v0.0.504, 25. September 2026"

    Modell: Claude Sonnet 4.6 über OpenRouter. Die signierte Zustellung antwortete `202`. Etwa zehn Sekunden später erschien in Activity ein Run auf der Oberfläche `schedule`, Kosten 0,003861 USD, mit der Nachricht, die der Trigger angehängt hatte: "A GitHub issue was opened in acme/widgets. Issue #42: Export button does nothing on Safari …".

    Die Antwort: "**Not a security report.** Priority: High. Labels: `bug`, `browser-compatibility`. Duplicate check: Nothing in the provided information suggests this is a duplicate …", endend mit einem kommentarfertigen Absatz, der die Reproduktionsschritte nannte und einem Maintainer vorschlug, die Behandlung von `Blob`/`<a download>` in Safari zu prüfen. Es gab keine Tool-Aufrufe. Eine mit dem falschen Geheimnis signierte Zustellung kam als `403` mit `"Webhook signature did not verify"` zurück. Derselbe Payload mit `"action": "edited"` kam als `202` ohne neuen Run zurück.

## Wenn etwas schiefgeht { #when-it-goes-wrong }

- **`403` bei jeder Zustellung, echt oder synthetisch.** Das Geheimnis stimmt nicht, oder der Content-Type ist nicht `application/json`: Eine formularkodierte Zustellung signiert andere Bytes, als GitHub gesendet hat. Der Tab **Recent Deliveries** am Webhook auf GitHub zeigt für ein echtes Repository die genaue Anfrage und Antwort.
- **`202`, aber nichts in Activity.** `202` heißt angenommen, nicht fertig, und heißt auch "nichts passte": Ein inaktiver Trigger oder eine herausgefilterte Aktion antworten identisch. Prüfen Sie den Filter des Triggers, bevor Sie einen Fehler annehmen.
- **Ein `GitHub (App)`-Trigger hat keinen Webhook in den Einstellungen des Repositorys.** Erwartet: Die App liefert an eine gemeinsame URL pro Installation, nicht an eine URL pro Trigger. Siehe [wenn eine Zustellung eintrifft](../triggers.md#when-a-delivery-arrives).
- **Der Agent versucht zu kommentieren und kann es nicht.** Der Agent dieses Versuchs hat absichtlich kein GitHub-Tool. Eines hinzuzufügen ist ein eigener, bewusster Schritt; siehe unten.

## Den Versuch festhalten { #record-the-trial }

Bewahren Sie den signierten Payload, den Filter des Triggers, den Run in Activity und seine Antwort auf. Das beweist nur Trigger und Prompt. Es beweist nicht das Setzen von Labels oder Kommentaren, das eine eigene Capability und eine eigene Prüfung braucht.

## Nächste Schritte { #next-steps }

Damit der Agent handelt statt nur vorschlägt, binden Sie eine [GitHub-MCP-Verbindung](../mcp.md#development) oder die Schreibrechte der GitHub App und entscheiden Sie, wer ein Label oder einen Kommentar vor dem Posten prüft. MCP-Tools haben keine eigene Genehmigung pro Tool, also muss diese Prüfung von einem Menschen kommen, der den Run beobachtet, oder vom Chat-Modus **Ask about everything**, genauso wie beim [Umwandeln von Meeting-Notizen in Tasks](meeting-to-tasks.md). Ein Trigger läuft immer als [das Mitglied, das ihn erstellt hat](../concepts.md#it-runs-as-a-person). Geben Sie diese Rolle also der Person, die für einen fehlauslösenden Trigger verantwortlich sein soll, nicht der, die ihn zufällig eingerichtet hat.
