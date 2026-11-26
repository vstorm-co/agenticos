---
source_sha: "b4f01f7af48e"
---

# Modelle und Provider { #models-and-providers }

!!! tip "Geht es ums Entscheiden statt ums Konfigurieren?"

    Diese Seite beschreibt die Mechanik. [Ein Modell wählen](choosing-models.md)
    beantwortet, *welches* Modell ein Agent verwenden sollte — offene oder
    geschlossene Gewichte, was die Rechnung tatsächlich treibt, und warum die Wahl
    umkehrbar ist.

Das Template, aus dem diese Plattform gewachsen ist, hat ein Modell aus
Umgebungsvariablen gebaut.

Das hört in dem Moment auf zu funktionieren, in dem mehrere Organisationen sich
ein Deployment teilen: jede braucht ihren eigenen Key, ihren eigenen Standard und
die Möglichkeit, beides ohne ein erneutes Deployment zu rotieren.

Ein Modell wird deshalb **pro Run** aus der Datenbank konstruiert:

```
model profile → credential → unsealed secret → provider client → Model
```

Nichts davon, welches Modell ein Agent verwendet, steht in `.env`.

## Persönliche Modellschlüssel { #personal-model-keys }

Behalte im Builder unter **Modellzugriff** die Voreinstellung **Organisationsschlüssel verwenden** oder wähle **Jeder Nutzer verbindet seinen eigenen Schlüssel**. Im persönlichen Modus bleiben Modell und Endpunkt des Administrators fest. Unterstützt werden Chat-Anbieter mit API-Schlüssel, ohne Ersatzmodelle oder Modellwechsel pro Gespräch.

Ein angemeldetes Mitglied verbindet seinen Schlüssel über das private Formular über dem Nachrichteneingabefeld oder in den Chat-Einstellungen. Schlüssel gelangen nie in Nachrichten, Prompts oder Agentenanweisungen. Dieselbe Verbindung gilt für Agenten dieser Organisation mit gleichem Anbieter und Endpunkt. Ohne Schlüssel wird der Lauf vor der Modellanfrage blockiert; Authentifizierungsfehler wechseln nie zum Organisationsschlüssel. Ersetze den Schlüssel in den Chat-Einstellungen oder entferne die Verbindung unter **Vault → Deine Modellverbindung**. Das Speichern prüft den Schlüssel nicht beim Anbieter.

Das private Schlüsselformular übermittelt das erwartete Profil, den Anbieter, Endpunkt und das angezeigte Modell. Ändert sich das Ziel vor dem Speichern, lehnt der Server den Schlüssel mit einem Konflikt ab; das Formular lädt das Ziel neu und löscht den eingegebenen Schlüssel vor einem erneuten Versuch.

Der persönliche Modus unterstützt derzeit keine privaten oder Gruppenkanäle, Widgets, öffentlichen Seiten, HTTP-API-Läufe, Zeitpläne, Trigger, Hintergrundthemen, Sprache, Reviewer oder separate Modelle für Fähigkeiten. Pausiere oder entferne aktive Kanäle, öffentliche Freigaben und Routinen vor der Veröffentlichung. Das Erstellen oder erneute Aktivieren einer unvereinbaren Freigabe wird abgelehnt; dieselbe Regel gilt zur Laufzeit. Öffentliche Seiten und Widget-JWTs identifizieren kein angemeldetes Mitglied der Instanz.

Delegation funktioniert im angemeldeten Webchat. Ein persönlicher Subagent muss dasselbe Modellprofil wie der persönliche Hauptagent verwenden. Ein Hauptagent mit Organisationsschlüssel darf keine persönlichen Schlüssel über Delegation nutzen; persönliche Subagenten dürfen kein anderes Modell oder Ziel wählen. Veröffentlichung, Freigabe für Oberflächen, Promotion und Laufzeit prüfen diese Regeln auch für verschachtelte Delegationen und nach einer Fortsetzung.

Subagenten im Organisationsmodus behalten ihre eigenen Zugangsdaten. Inline-Spezialisten übernehmen den Modus ihres Elternagenten; dynamische Spezialisten im persönlichen Modus bleiben bei dessen Modell. Die Regeln für persönlichen MCP-Zugriff bleiben unverändert.

Bei einer fehlenden Subagent-Verbindung nennt die Meldung den Agenten und die Modellverbindung. Öffne dessen Chat-Einstellungen, um deinen Schlüssel zu verbinden; bitte den Eigentümer um Zugriff, falls der Agent nicht sichtbar ist. Der Runner prüft den Delegationsbaum vor Modellanfragen und erneut beim Fortsetzen. Schlüssel für andere Endpunkte, andere Mitglieder oder die freigebende Person ersetzen keine fehlende Verbindung des Aufrufers.

Schlüssel werden im Tresor für ihren Eigentümer verschlüsselt und beim Entfernen der Mitgliedschaft oder des Kontos gelöscht. Ein geänderter Endpunkt benötigt eine neue Verbindung. Die Rotation eines persönlichen Schlüssels ändert weder andere Schlüssel noch das gemeinsame Modellprofil.

Die Identitätsübernahme eines anderen Mitglieds gewährt keinen Zugriff auf dessen persönliche Modellverbindungen: Anfragen zum Lesen, Ändern oder Verwenden des Schlüssels werden vor dem Vault-Zugriff abgelehnt.

Der private Gesprächsverlauf ist an die genehmigten Modellziele einschließlich Fallbacks gebunden; der [Chatverlauf](console.md#chat) beschreibt Verbindungswechsel und die Fortsetzung wartender Läufe.

## Ein Model Profile { #a-model-profile }

Eine Zeile in einer Organisation: ein Label, ein Provider, eine Model-Id,
Standardeinstellungen und die Angabe, mit welchem
[Vault-Secret](secrets.md) authentifiziert wird.

Der Spec eines Agents benennt eines über `model_profile_id`, und der Run löst es
auf.

!!! tip "Die Model-Id ist absichtlich Freitext"

    Es gibt eine Auswahlhilfe, aber das Feld nimmt alles an, was Sie eintippen.

    Ein Provider liefert am Morgen nach jeder hier aufgewärmten Liste etwas Neues
    aus, und ein Feld, das "genau das" nicht ausdrücken kann, ist ein Feld, das
    Menschen umgehen, indem sie den Spec von Hand editieren.

### Ein Profil, auf dem kein Agent laufen kann { #a-profile-an-agent-cannot-run-on }

Ein Profil kann ein Modell benennen, das kein Gespräch führen kann: ein
Sprachausgabe-Modell wie `gpt-4o-mini-tts`, ein Realtime-Sprachmodell, ein
Transkriptionsmodell, ein
Bildmodell, ein Videomodell oder ein Embedding-Modell. Ein Agent darauf scheitert
schon an seinem ersten Zug. Sprachausgabe, Bildgenerierung und Transkription
nutzen keine Profile: Jede dieser Funktionen benennt ihren eigenen Provider und ihr
eigenes Modell.

Die Plattform kennt diese Modelle aus ihren eigenen Katalogen (den Listen für
Realtime-Sprache, Sprachausgabe, Transkription, Bilder, Video und Embeddings).
`GET /providers/model-profiles` markiert jedes Profil mit `chat_capable` und
`output_modalities`, und `GET /providers/{provider}/models` markiert jeden
Vorschlag mit `chat_capable`. Diese beiden Felder lesen auch das Listing eines
Providers, das angibt, was jedes Modell ausgibt (OpenRouter und der Hugging Face
Router tun das), sofern der API-Prozess es bereits abgerufen hat. Dieses Listing
ändert nur, was eine Auswahl anbietet. Es lehnt nie eine Veröffentlichung ab, weil
ein anderer API-Prozess es vielleicht nicht abgerufen hat. Die Konsole aktualisiert
auch gespeicherte Profile, wenn das Listing später eintrifft. Provider-Aliase wie
`openai_codex` und `google_cloud` verwenden die Kataloge des jeweiligen Anbieters.
Dann gilt:

- Das Modell-Panel im Builder, die Auswahl für Reviewer und Spezialisten, die
  Felder für das Modell der Folgeschritte und das Schrittmodell des Browsers und
  die Modellauswahl für Bildbeschreibungen in der Wissensdatenbank bieten ein
  solches Modell nicht an. Benennt ein Agent bereits eines, zeigt der Builder es
  weiterhin an, markiert als kein Chat-Modell. Einem Mitglied, das Verbindungen
  verwaltet, listet der Builder auch die übrigen solchen Modelle, markiert und
  nicht wählbar, damit sie entfernt werden können.
- Die Modellauswahl im Chat und das Formular zum Hinzufügen eines Modells im
  Builder schlagen ein solches Modell nicht vor und lehnen ein eingetipptes ab.
- Die Veröffentlichung lehnt ein solches Modell als Modell des Agents, eines
  Reviewers oder eines Spezialisten, als Schrittmodell des Browsers oder als Modell
  für Folgeschritte ab und nennt es. Sie lehnt auch ein Profil ab, dessen Fallbacks
  ein solches Modell enthalten. Dieselbe Prüfung läuft beim Rollback, bei der
  Entwurfsprüfung, beim Testlauf im Builder und beim Aktivieren einer Capability
  aus dem Chat. Eine gespeicherte Version auf einem solchen Modell lädt weiterhin,
  lässt sich aber nicht wiederherstellen, solange ihr Profil kein Chat-Modell
  benennt oder eines als Fallback auflistet. Stellen Sie dieses Profil auf ein
  Chat-Modell um oder veröffentlichen Sie eine neue Version.
- Ein Run lässt einen solchen Fallback aus seiner Kette weg, genau wie einen
  gelöschten, wenn er dem Profil nach der Veröffentlichung hinzugefügt wurde.
- Ein Gespräch, das statt des Modells des Agents ein solches Modell nennt, aus dem
  Chat oder über die API, wird abgelehnt, bevor der Run beginnt.
- Ein Modell, das die Kataloge nicht einordnen, etwa ein Ollama-Modell oder ein
  heute Morgen veröffentlichtes Modell, ist erlaubt. Ein unbekanntes Modell ist
  keine Ablehnung. Ein Profil mit eigenem Endpoint (`base_url`) wird nie
  eingeordnet, unabhängig von seiner Modell-ID: Die Kataloge beschreiben die
  eigene API des Providers, und ein OpenAI-kompatibler Server kann ein Chat-Modell
  unter jedem Namen anbieten.

Die Modellauswahl für proaktive Arbeit folgt derselben Regel. Die Prüfung der
festen Kataloge läuft auch bei der Konfiguration proaktiver Arbeit und beim
Auflösen eines Profils für eine gewöhnliche Textanfrage, einschließlich der
Bildbeschreibung bei der Konfiguration und im Worker. Alte Konfigurationen laden
weiterhin; ein inkompatibles Modell muss vor der Nutzung ersetzt werden. Das
Ausschalten bleibt möglich. Azure-Deployment-Namen werden nicht anhand der
Basismodell-IDs des Katalogs klassifiziert.

### Das Modell, mit dem ein neuer Agent startet { #the-model-a-new-agent-starts-on }

Es gibt kein organisationsweites Standardmodell. Der Spec eines Agents nennt sein
Modell, und die Veröffentlichung lehnt einen Spec ab, der keines nennt.

Ein neuer Agent, der kein Modell nennt, startet mit dem Modell der Organisation,
wenn die Organisation genau ein Modell hat, auf dem ein Agent laufen kann. Das ist
ein Chat-Modell mit Schlüssel oder ein selbst gehostetes Modell, das ohne Schlüssel
gespeichert wurde, und die Veröffentlichung akzeptiert es so, wie es ist, Fallbacks
eingeschlossen. Das gilt für jeden Weg, einen Agent anzulegen: **Neuer Agent** in
der Konsole, `POST /agents` ohne `model_profile_id`, eine Vorlage, eine Kopie eines
Entwurfs ohne Modell und ein beförderter Spezialist.

Der Architekt, der Assistent der Organisation, wählt sein Modell beim
Veröffentlichen selbst: das erste Chat-Modell, das die Veröffentlichung akzeptiert,
und nie ein Modell auf einer
[ChatGPT-Anmeldung](#running-on-a-chatgpt-subscription). Der Architekt dient der
ganzen Organisation, und eine Anmeldung ist das Abonnement einer Person: Läufe von
Mitgliedern, die sie im Vault nicht sehen dürfen, werden abgelehnt, und Läufe derer,
die es dürfen, etwa der Eigentümer und Administratoren der Organisation, verbrauchen
es. Gibt es nur eine Anmeldung, wartet der Architekt auf ein anderes Modell.

Eine Anmeldung, die jemand im Entwurf des Architekten wählt, oder ein Modell mit
einer Anmeldung als Fallback bleibt dort, wird aber erst veröffentlicht, wenn jemand, der die Einstellungen der Organisation ändern
darf, es im Builder veröffentlicht. Ein Architekt, der bereits auf einer Anmeldung
veröffentlicht ist, behält dieses Modell, bis jemand, der die Einstellungen der
Organisation ändern darf, unter **Bauen > Modell** (Build > Model) ein anderes wählt
und es veröffentlicht.

Das Modell wird in den Entwurf geschrieben. So lässt sich der Agent veröffentlichen,
ohne dass jemand **Modell** öffnet, und seine Historie zeigt, mit welchem Modell er
veröffentlicht wurde. Ein Spec, der ein Modell nennt, behält es. Der Entwurf gilt
dann als Nutzer des Modells: Das Modell lässt sich erst löschen, wenn der Agent auf
ein anderes Modell wechselt oder gelöscht wird; Archivieren genügt nicht. Um nur den
Schlüssel oder den Endpunkt des Modells zu ändern, bearbeiten Sie es an Ort und
Stelle ([Schlüssel oder Endpunkt eines Profils
ändern](#changing-a-profiles-key-or-endpoint)).

Der Entwurf bleibt ohne Modell, wenn die Organisation keines oder mehr als eines
hat. Profile, auf denen kein Agent laufen kann, zählen nicht: ein Profil ohne
Schlüssel, ein Text-to-Speech-Modell und die anderen Modelle aus [Ein Profil, auf
dem kein Agent laufen kann](#a-profile-an-agent-cannot-run-on), und ebenso wenig ein
Profil, das die Veröffentlichung ablehnen würde, etwa eines mit einem solchen Modell
als Fallback. Ein Modell auf einer
[ChatGPT-Anmeldung](#running-on-a-chatgpt-subscription) wird nie für jemanden
gewählt, weil es das Abonnement einer einzelnen Person ist, aber es zählt als
Modell.

Ebenso wenig ein Modell, unter dessen ersten drei Fallbacks, die ein Run
versucht, eine Anmeldung ist: Fällt das Modell aus, wiche der Run jedes
Menschen, der die Anmeldung sehen darf, auf dieses Abonnement aus. Auch der
Architekt wählt kein solches Modell. Ein Autor kann ein
solches Modell weiterhin bewusst wählen und veröffentlichen.

Die Veröffentlichung lehnt den Entwurf dann mit *No model selected - pick one under
Build > Model before publishing* ab. Die Ablehnung markiert auch das Feld
(`model_profile_id` in `details.fields`), und die Konsole zeigt daneben **Zum
Abschnitt Modell**, das den Tab **Bauen** an der Karte **Modell** öffnet.

### Schlüssel oder Endpunkt eines Profils ändern { #changing-a-profiles-key-or-endpoint }

Agents verweisen über die id auf ein Profil. Um ein Modell auf einen anderen
Schlüssel, einen anderen Endpunkt oder die andere OpenAI-API umzustellen,
bearbeiten Sie das Profil an Ort und Stelle: `PATCH /providers/model-profiles/{id}`
ändert `secret_id`, `base_url`, `api`, `params` oder `label` und behält die id.
Jeder Agent auf dem Profil nutzt die Änderung ab seinem nächsten Run. Niemand
muss etwas neu veröffentlichen.

Ändern Sie im Modellbereich des Builders den Schlüssel, den Endpunkt oder die API
des verwendeten Modells. Die Schaltfläche heißt dann **Modell aktualisieren**,
und der Bereich sagt, dass jeder Agent auf diesem Modell mitwechselt. **Modell
hinzufügen** bleibt die Schaltfläche für einen anderen Provider oder ein anderes
Modell und für ein Modell, dem Sie einen eigenen Namen geben. Mit **Nennen Sie
ihn anders** erhält nur dieser Agent ein eigenes Modell.

Eine Bearbeitung folgt denselben Regeln wie das Anlegen und braucht dieselbe
Berechtigung `connections:manage`. Ein neuer Schlüssel muss im Vault dieser
Organisation liegen, für Sie sichtbar sein und für den Provider des Profils
gespeichert sein. Ein neuer Endpunkt prüft den gespeicherten Schlüssel genauso,
denn an den Endpunkt wird der Schlüssel gesendet. Ein Provider, der einen
Schlüssel braucht, kann ihn nicht verlieren. Ein Provider ohne Schlüsselpflicht
(keyless) ohne Schlüssel behält einen Endpunkt. Ein Label muss eindeutig bleiben.

Ändern Sie den Endpunkt ohne `api`, wechselt eine API, die nur der Standard des
alten Endpunkts war, auf den Standard des neuen; eine bewusst gewählte API
bleibt. Das Audit-Log speichert
`model_profile.updated` mit den Namen der geänderten Felder, nicht mit ihren
Werten. Provider und Modell-id können Sie nicht ändern. Ein anderes Modell ist
ein anderes Profil.

`connections:manage` ist damit die Befugnis, jeden Agent auf einem Modell
umzustellen, auch Agents, die Sie nicht bearbeiten dürfen: ein neuer Endpunkt
erhält ihre Anfragen ab dem nächsten Run. Vergeben Sie sie an die Personen, die
die Modelle der Organisation verwalten.

### Ein Profil ohne Schlüssel { #a-profile-without-a-key }

Wenn Sie einen Schlüssel aus dem Vault löschen, bleiben seine Profile mit
`secret_id` auf null bestehen, und `GET /providers/model-profiles` markiert sie
mit `missing_key: true`. Ein Profil, das absichtlich ohne Schlüssel gespeichert
wurde, ist etwas anderes: ein selbst gehostetes Modell oder ein Gateway, das
nichts authentifiziert, auf einem keyless Provider mit Endpunkt, etwa ein Ollama
in Ihrem Netz oder ein OpenAI-kompatibler Server. Es speichert das als
`runs_without_key` und läuft weiter. Ein Gateway-Profil, das einen Schlüssel hatte
und ihn verloren hat, wird wie jedes andere mit `missing_key` markiert. Dann:

- Die Modellauswahl für Agents und Chat bietet es nicht an. Verweist ein Agent
  bereits darauf, zeigt der Builder es mit dem Hinweis **kein Schlüssel** und
  fordert Sie auf, ihm einen Schlüssel zu geben.
- Das Veröffentlichen lehnt es ab und nennt das Modell. Es lehnt auch ein Profil
  ab, unter dessen ersten drei Fallbacks eines ohne Schlüssel ist, weil ein Run es
  überspringen würde. Ein Run darauf scheitert
  mit „no key configured“.
- Zum Reparieren öffnen Sie einen Agent auf diesem Modell, wählen unter **Modell**
  einen Schlüssel und klicken auf **Modell aktualisieren**. Jeder Agent auf dem
  Modell funktioniert wieder.

### Ein Profil löschen { #deleting-a-profile }

`DELETE /providers/model-profiles/{id}` lehnt ein Profil ab, das Agents nutzen.
Die Antwort ist `409 IN_USE`, und `details.agents` listet jeden Agent, den Sie
sehen können, mit id und Namen. `details.hidden_agents` zählt die Agents, die Sie
nicht sehen. Ein Profil ist in Gebrauch, wenn der Entwurf eines Agents, seine
ausgelieferte Version oder eine von einer Umgebung gepinnte Version das Profil
irgendwo nennt: als Modell des Agents, eines Reviewers oder eines Spezialisten
oder in einer Capability, etwa als Follow-up-Modell oder als Modell für
Browser-Schritte.

Archivierte Agents zählen, denn das Wiederherstellen aus dem
Archiv stellt die Version wieder her, die sie ausgeliefert haben. Die Ablehnung
markiert sie mit `archived`: Ein archivierter Agent kann nicht veröffentlichen,
also löschen Sie ihn, oder stellen Sie ihn wieder her und verschieben Sie ihn.
Alte Versionen, die nichts ausliefert, zählen nicht. Verschieben Sie die übrigen
Agents zuerst auf ein anderes Modell. Um nur
den Schlüssel zu ändern, bearbeiten Sie stattdessen das Profil.

### Fallbacks { #fallbacks }

Der Runner verwendet nur die ersten drei Fallbacks; nur diese werden bei der Veröffentlichung geprüft.

Ein Profile kann Fallback-Profiles auflisten, die der Reihe nach versucht werden.
Der Ausfall eines Providers sollte die Agents einer Organisation nicht lahmlegen,
wenn sie einen zweiten Key oder einen zweiten Provider konfiguriert hat.

!!! warning "Ein Fallback ist im Run-Datensatz unsichtbar"

    Die Run-Zeile wird vor der ersten Anfrage geschrieben und trägt Label, Provider
    und Secret-Id des **primären** Profiles. Hat ein Fallback den Zug bedient, nennt
    der Run trotzdem das primäre.

    "Was haben wir bei OpenAI ausgegeben" und "welcher Key kostet am meisten"
    antworten also mit dem Profile, das zuerst *gefragt* wurde, nicht mit dem, das
    geantwortet hat. Wissenswert, bevor Sie sich während eines Ausfalls auf diese
    Zahlen verlassen.

### Model Settings { #model-settings }

Pro Profile, und pro Agent über die `model_settings` des Specs überschreibbar:
`temperature`, `top_p`, `max_tokens`, `parallel_tool_calls`, `timeout`. Siehe
[die Spec-Referenz](reference/spec.md#model-settings).

**Prompt-Caching ist standardmäßig an**, über die anbieterneutrale
`cache`-Einstellung von Pydantic AI. Jeder Request eines Runs schickt die
Anweisungen, die Tool-Schemas und den ganzen Verlauf erneut, also werden der
stabile Präfix und das Gespräch als Cache-Breakpoints markiert, und jeder Request
liest den vorigen aus dem Cache. Das greift überall, wo ein Anbieter explizites
Caching annimmt - Anthropic, die Anthropic- und Nova-Modelle bei Bedrock, die
Anthropic- und Gemini-Modelle bei OpenRouter, OpenAI ab GPT-5.6 - und ändert
nichts bei einem, der selbst cacht, wie Google. Ein Profile schaltet es mit
`cache: false` ab oder cacht mit `cache: {"messages": false}` nur Anweisungen und
Tools. Ein anbieterspezifisches Flag, das ein Profile schon setzt, etwa
`anthropic_cache_messages`, hat für dieses Profile weiter Vorrang.

Tägliches Briefing, Vorschläge und Speicherpflege bieten diese Vorgaben zusammen
mit dem Reasoning-Aufwand in der Modellauswahl der Organisation an. Änderungen
werden ausdrücklich im gemeinsamen Modellprofil gespeichert und gelten für alle
Verwendungen dieses Profils. Nicht gesetzte Felder senden keine Überschreibung;
belassen Sie nicht unterstützte Parameter bei den Anbietervorgaben. Agents können
den Aufwand über die [`thinking`-Capability](reference/capabilities.md#thinking)
mit der anbieterneutralen Einstellung von Pydantic AI überschreiben. Hintergrundrollen
haben keinen Agent-Spec und verwenden den `thinking`-Standard des Profils direkt.

### Responses oder Chat Completions { #responses-or-chat-completions }

OpenAI veröffentlicht zwei APIs für dieselben Modelle, und ein Profile auf `openai`,
`azure` oder `stav` speichert, an welche davon seine Requests gehen: `responses` oder
`chat`. Jeder andere Provider bedient eine API und speichert hier nichts.

Keine ist überall richtig. Die neuesten Modelle von OpenAI gibt es nur über
Responses, und auf Chat Completions antworten sie mit einem 400, während die
meisten OpenAI-kompatiblen Server - vLLM, LM Studio, ein LiteLLM-Proxy - nur Chat
Completions implementieren. Deshalb ist die Wahl ein Feld des Profiles, unter
**Agents → add a model → API**, und das Formular beginnt beim Standard:

| Profile | Standard |
|---|---|
| `openai`, ohne Endpunkt (die eigene API von OpenAI) | `responses` |
| `openai` mit Endpunkt | `chat` |
| `azure` | `chat`, weil die Responses-API eine aktuelle `api_version` braucht und das Secret eine ältere festlegen kann |
| `stav` | aus dem Modell: `chat`, wo es bedient wird, sonst `responses` |

Der Standard ist nur, wo das Formular beginnt. Ein regionaler OpenAI-Endpunkt wie
`https://eu.api.openai.com/v1` ist ein Endpunkt, der Responses bedient, also
wählen Sie es dort. Eine weggelassene Wahl wird als ihr Standard gespeichert, ein
späterer Wechsel des Standards verschiebt also kein bestehendes Profile.

**Ein Responses-Profile hinterlässt keine Conversations bei OpenAI.** Die
Responses-API speichert jede Antwort auf der Seite von OpenAI, sofern man es ihr
nicht untersagt, während Chat Completions standardmäßig nichts speichert - ein
Responses-Modell sendet daher `store: false`. Reasoning wird zwischen den Zügen als
verschlüsselter Inhalt weitergegeben und nicht über eine gespeicherte Response-Id,
also braucht nichts die gespeicherte Kopie. Ein Profile, das sie will, setzt
`openai_store` in seinen Settings auf `true`.

### Wo die Requests eines Stav-Profiles laufen { #where-a-stav-profiles-requests-run }

Ein Profile auf `stav` speichert eine Region: `eu`, `eea` oder `global`. Stav
antwortet nur von Endpunkten, die in dieser Region rechnen, weicht nur innerhalb
davon aus und lehnt einen Request ab, den es dort nicht bedienen kann. `global`
setzt selbst keine Grenze. Die Region schränkt nur ein, was die eigene Policy des
Stav-Workspaces erlaubt.

Gesetzt wird sie unter **Agents → add a model → Region**. Das Formular beginnt bei
`eu`, und eine weggelassene Region wird als `eu` gespeichert - ein Profile verlässt
die EU also nur, wenn es mit `eea` oder `global` gespeichert wurde.

Die Region geht bei jedem Request als Header `X-Stav-Runs-In` mit, nicht im Body,
damit ein `extra_body` in den Settings des Profiles sie nicht ersetzen kann.

Ein eigener Stav-Katalog verwendet den im Formular ausgewählten Vault-Schlüssel. Der Benutzer muss auf diesen Schlüssel zugreifen dürfen; für eine eigene URL wird niemals ein verborgener Organisationsschlüssel gewählt. Authentifizierte Kataloge werden pro Zugangsdaten getrennt gecacht. `extra_headers` eines Requests können die EU- oder EEA-Beschränkung des Profils nicht überschreiben.

### Otari-Gateway { #otari-gateway }

Beim Hinzufügen eines Modells **Otari** wählen, einen Otari-API-Key im Vault speichern und im Profil auswählen. **Endpoint** ist erforderlich: für gehostetes Otari `https://api.otari.ai/api/v1` eintragen. Für ein Otari-Konto in der EU `https://eu.api.otari.ai/api/v1` eintragen; beim Selbsthosting den API-Stamm des Gateways mit `/api/v1` verwenden, erreichbar von API und Workern.

Nach der Auswahl von Endpunkt und Schlüssel **Modelle laden** anklicken. Jede Änderung erfordert eine erneute Bestätigung; beim Tippen einer Adresse wird der Schlüssel nicht gesendet.

Modellvorschläge stammen vom authentifizierten `/models`-Endpunkt dieses Gateways und verwenden den ausgewählten Schlüssel. Ein eigener Endpunkt erfordert `connections:manage` und Zugriff auf diesen Schlüssel. Der Katalog-Cache ist nach Endpunkt und Zugangsdaten getrennt; bei einem Fehler wird ein eigener Katalog nicht durch den gehosteten ersetzt. Das Modellfeld akzeptiert auch einen Selektor wie `anthropic:claude-sonnet-4-6` oder einen in Otari konfigurierten Alias beziehungsweise eine Routing-Policy.

Die Integration verwendet [`pydantic-ai-otari`](https://github.com/mozilla-ai/otari/tree/main/integrations/pydantic-ai-otari): `OtariProvider` liefert das Modellfamilienprofil an das Chat-Completions-Modell von Pydantic AI, wie `OtariModel`. Anfragen nutzen immer Chat Completions; das Formular bietet weder Responses noch Stavs Regionsauswahl. Schlüssel und Endpunkt werden ausdrücklich aus dem Profil übergeben, ohne Rückgriff auf `OTARI_*` oder `OPENAI_API_KEY`. Otaris Gateway-Budgets und Routing ergänzen die weiterhin geltenden Budgets und Freigaben von AgenticOS.

Direkte `provider:model`-Selektoren nutzen für AgenticOS-Budgets den gebündelten Katalogpreis des upstream Modells; bloße Routing-Aliase und unbekannte Modelle bleiben ausdrücklich teilweise bepreist. Das sind upstream Preisschätzungen: Gateway-Gebühren stehen in Otaris Nutzungsansicht.

## Provider { #providers }

Chat-Provider von Pydantic AI sowie Otari über sein Integrationspaket, Stav mit regionalem Routing und MiniMax über seine kompatible API.

Standard-Provider verwenden die Modell- und Provider-Ableitung von Pydantic AI. Die Plattform beschreibt die Form der Zugangsdaten und bindet bei Bedarf Provider-Pakete ein.

!!! info "Was Custom URL bedeutet"

    Das SDK des Providers benennt einen Endpunkt-Parameter, Sie können ein Profile
    also auf ein Gateway, einen LiteLLM-Proxy oder einen Model Server in Ihrem eigenen
    Netz zeigen lassen statt auf die öffentliche API des Anbieters.

    Es ist ein Feld am **Profile**, nicht am Key. Ein Key sagt, was authentifiziert,
    ein Endpunkt sagt, wohin die Anfrage geht — derselbe Key kann also als zwei
    Profiles einen Staging-Proxy und einen Produktions-Proxy bedienen.

    Setzen Sie es unter **Agents → add a model → Endpoint**, was nur für die unten
    markierten Provider erscheint. Eines für einen Provider zu speichern, der keinen
    hat, wird abgelehnt, statt angenommen und verworfen zu werden.

### Gehostet { #hosted }

| Provider | id | Zugangsdaten | Custom URL |
|---|---|---|---|
| OpenAI | `openai` | API-Key, oder keine | ✓ |
| Anthropic | `anthropic` | API-Key | ✓ |
| Google Gemini | `google` | API-Key | ✓ |
| TypeSafe (Jev) | `typesafe` | API key | ✓ |
| OpenRouter | `openrouter` | API-Key |  ✓ |
| Otari | `otari` | API-Key | ✓ |
| Alibaba Cloud | `alibaba` | API-Key | ✓ |
| Cerebras | `cerebras` | API-Key | |
| DeepSeek | `deepseek` | API-Key | |
| Fireworks AI | `fireworks` | API-Key | |
| GitHub Models | `github` | API-Key | |
| GitHub Copilot | `github_copilot` | Kontotoken / persönliche Anmeldung | |
| Groq | `groq` | API-Key | |
| Heroku AI | `heroku` | API-Key | ✓ |
| LLMTR | `llmtr` | API-Key | |
| Mistral | `mistral` | API-Key | |
| MiniMax | `minimax` | API-Key | ✓ |
| Kimi Code (plan) | `kimi_code` | API-Key | ✓ |
| Alibaba Coding Plan | `alibaba_coding_plan` | API-Key | ✓ |
| OpenCode Go | `opencode_go` | API-Key | ✓ |
| Ollama Cloud | `ollama_cloud` | API-Key | ✓ |
| Nous Portal | `nous_portal` | API-Key | ✓ |
| Inception | `inception` | API-Key | ✓ |
| Cline | `cline` | API-Key | ✓ |
| Chutes | `chutes` | API-Key | ✓ |
| Synthetic | `synthetic` | API-Key | ✓ |
| CLIProxyAPI (subscription gateway) | `cliproxyapi` | API-Key | ✓ |
| Moonshot AI | `moonshotai` | API-Key | |
| Nebius AI Studio | `nebius` | API-Key | |
| OVHcloud AI Endpoints | `ovhcloud` | API-Key | |
| SambaNova | `sambanova` | API-Key | ✓ |
| Stav.ai | `stav` | API-Key | ✓ |
| Together AI | `together` | API-Key | |
| Vercel AI Gateway | `vercel` | API-Key | |
| Z.AI | `zai` | API-Key | ✓ |
| xAI (Grok) | `xai` | API-Key | ✓ (`api_host`) |
| Cohere | `cohere` | API-Key | |
| Hugging Face | `huggingface` | API-Key | ✓ |

LLMTR zeigt nur Modelle mit `CHAT_COMPLETIONS`. Ein Modell ohne geprüften Preis im mitgelieferten Snapshot kann nur ohne aktive Dollargrenze ausgeführt werden; seine Kosten bleiben als unvollständig markiert. Bei aktiver Grenze werden weitere LLMTR-Aufrufe auch verweigert, wenn frühere Nutzung unbekannte Kosten hat.

Wähle **MiniMax** für seine OpenAI-kompatible Chat-Completions-API. Speichere deinen M-Plan-API-Schlüssel als MiniMax-Schlüssel im Vault; ein normaler API-Schlüssel nutzt seine eigene Abrechnung. Ein leerer Endpoint verwendet `https://api.minimax.io/v1`. Einen eigenen Endpoint setzt du nur für die Region oder das Gateway deines Schlüssels. Gib die genaue Modell-ID deines Kontos ein, etwa `MiniMax-M3.1-Flash`; die Integration lädt keinen planspezifischen Katalog. MiniMax-Verläufe haben eine eigene Provider-Identität, sodass verschlüsselte OpenAI-Denkinhalte nicht dorthin gesendet werden. Bekannte Tokenpreise dienen als Budgetschätzungen, nicht als Abonnementrechnung.

Für einen **Z.AI GLM Coding Plan** wähle **Z.AI** und setze **Endpoint** ausdrücklich auf `https://api.z.ai/api/coding/paas/v4` (global) oder `https://open.bigmodel.cn/api/coding/paas/v4` (China), mit einem Schlüssel für diesen Plan und diese Region. Ein leerer Endpoint behält die normale nutzungsabhängige API bei; bestehende Profile ändern sich nicht.

**Schlüssel für Abo-Pläne.** Vier weitere Provider rechnen einen Abo-Plan über einen Planschlüssel für einen OpenAI-kompatiblen Endpunkt ab. Speichere den Planschlüssel unter dem passenden Tresorzweck; die Modellliste stammt aus dem Katalog dieses Schlüssels, und ein leerer Endpoint verwendet die Standardadresse des Plans.

| Provider | Standard-Endpunkt | Andere Region oder Hinweis |
|---|---|---|
| Kimi Code (plan) | `https://api.kimi.ai/coding/v1` | China: `https://api.kimi.com/coding/v1` |
| Alibaba Coding Plan | `https://coding-intl.dashscope.aliyuncs.com/v1` | China: `https://coding.dashscope.aliyuncs.com/v1` |
| OpenCode Go | `https://opencode.ai/inference/go/openai/v1` | Modelle, die dieses Protokoll nicht bedienen, lehnt der Endpunkt ab |
| Ollama Cloud | `https://ollama.com/v1` | Cloud-Modelle deines Ollama-Kontos |

Ein Planschlüssel ist nicht mit dem nutzungsabhängigen API-Schlüssel des Anbieters austauschbar. Manche Anbieter beschränken Planschlüssel auf Coding-Tools; die Nutzung über eine Agentenplattform ist deine Entscheidung und kann den Plan einschränken oder sperren. AgenticOS-Budgets behandeln diese Nutzung als unbepreiste Abo-Nutzung.

**Weitere OpenAI-kompatible Konten.** Nous Portal, Inception, Cline, Chutes und Synthetic nehmen den Schlüssel aus der Konsole des jeweiligen Dienstes. Ein leerer Endpoint verwendet die Standardadresse unten, und die Modellliste stammt aus dem Katalog des Schlüssels. Abos von Nous Portal, Chutes und Synthetic gelten als unbepreist; Cline-Guthaben und Inception-Nutzung werden nur bepreist, wo AgenticOS den Modellpreis kennt.

| Provider | Standard-Endpunkt |
|---|---|
| Nous Portal | `https://inference-api.nousresearch.com/v1` |
| Inception | `https://api.inceptionlabs.ai/v1` |
| Cline | `https://api.cline.bot/api/v1` |
| Chutes | `https://llm.chutes.ai/v1` |
| Synthetic | `https://api.synthetic.new/openai/v1` |

**Eigenes CLIProxyAPI-Gateway.** Konten, für die der Anbieter keinen Planschlüssel ausgibt (Antigravity, Grok Build, Devin, Muse Code, Kimi-Code-Anmeldung und weitere), lassen sich über ein [CLIProxyAPI](https://github.com/router-for-me/CLIProxyAPI)-Gateway nutzen, das du oder dein Betreiber außerhalb des Stacks betreibt. [Abonnement-Konten](#subscription-accounts) sind dieselbe Idee eingebaut, mit den Konten jeder Person getrennt voneinander. Melde die Konten mit den eigenen Login-Befehlen des Gateways an, lege unter `access.api-keys` einen Client-Schlüssel an und erstelle dann ein Profil **CLIProxyAPI (subscription gateway)** mit dessen Endpoint (zum Beispiel `http://cliproxyapi:8317/v1` für einen Gateway-Container im Netz des Deployments) und diesem Client-Schlüssel. Jedes Konto im Gateway steht allen offen, die das Profil nutzen dürfen; betreibe für ein persönliches Konto daher ein persönliches Gateway. Trage den Host des Gateways in `OUTBOUND_PRIVATE_ALLOWLIST` ein; Loopback-Adressen sind vom Server aus nie erreichbar. Anbieter können so genutzte Konten einschränken oder sperren; dieses Risiko trägt der Kontoinhaber.

Der Scope enthält auch die Mitgliedschafts-ID: Ein erneuter Beitritt erzeugt einen neuen Scope, sodass ein alter Bereinigungsauftrag keine neu verbundenen Konten löschen kann. Das Löschen der Anmeldedaten wird auch bei deaktiviertem Gateway eingereiht. Ein deaktiviertes oder fehlerhaftes Gateway hinterlässt einen sichtbar fehlgeschlagenen Auftrag statt einer Löschbestätigung; wiederholen Sie ihn nach Wiederherstellung des Gateways. Ein fehlgeschlagener Abruf des Anmeldestatus zeigt einen Fehler und eine Schaltfläche zum Wiederholen.

Wähle den Vault-Schlüssel und bestätige das Ziel, bevor du Modelle lädst. Ein eigener Katalog verwendet nur diesen Schlüssel und Endpoint. Eine nicht verfügbare Liste lässt die manuelle Modelleingabe zu, statt den allgemeinen API-Katalog einzusetzen. Die Budgetschätzungen von AgenticOS messen nicht dein verbleibendes Abonnementkontingent.

### Abonnement-Konten { #subscription-accounts }

Beginne im Agenteneditor und in der Modellauswahl des Chats mit **Deine Abonnements**, wähle einen bekannten Anbieter wie **Claude Code (Pro, Max)** oder **ChatGPT (Codex)** und klicke auf **Verbinden**. Die Anmeldung öffnet sich direkt dort und führt zur Modellauswahl zurück. Die Liste stammt aus den verbundenen Konten dieses Anbieters, nicht aus Vermutungen anhand von Modellnamen. Nicht verfügbare Konten bieten eine erneute Anmeldung. Konten lassen sich unter **Einstellungen → Abonnements** verwalten und trennen. API-Schlüssel der Organisation bilden eine eigene Gruppe; manuell konfigurierte Gateways und Endpoints stehen unter **Erweitert / eigener Endpoint**. Bestehende Profile mit `subscription_accounts` und `cliproxyapi` behalten ihre API-IDs.

Chatkataloge zeigen alle chatfähigen Einträge, statt die Liste unbemerkt auf 100 Modelle zu begrenzen. Die Auswahl zeigt die Anzahl, den aktuellen Katalog oder eine begrenzte Ersatzliste und eine Aktualisierung an. OpenRouter zeigt die aktuelle Katalogregion; Änderungen erfolgen ausdrücklich und das neu gespeicherte Modell behält die Region. Gespeicherte Modelle behalten ihre eigenen Verbindungseinstellungen.

Im Onboarding können Mitglieder unter **Welche Abonnements hast du bereits?** vorhandene Abonnements auswählen und sich vor dem ersten Chat anmelden. Dies ist optional; die Konten bleiben persönlich und konfigurieren nicht das gemeinsame Startmodell der Organisation.

Bei mehreren verbundenen persönlichen Konten öffnen Sie den Reiter **Konto** und wählen Sie das Konto wie einen gespeicherten API-Schlüssel. Abonnementmodelle verwenden dieselbe durchsuchbare Liste wie API-Anbieter; die Auswahl eines Modells wendet es sofort an. Die Modellauswahl bindet es über eine undurchsichtige Route an dieses Konto; sie wechselt nicht still zu einem anderen Konto. Kontogebundene Profile benötigen das verbundene Konto der ausführenden Person. Beim erneuten Öffnen werden Konto und Modell wiederhergestellt, ohne die Kontoroute im Modellnamen anzuzeigen.

**Einstellungen → Abonnements** zeigt jedes verbundene Konto einzeln mit Kontingentfenstern, verbleibenden Prozenten, Fortschrittsbalken und Rücksetzzeiten. Der Reiter **Konto** verwendet dieselbe Ansicht für alle Konten des gewählten Anbieters.

Claude, Codex, Antigravity und beide Kimi-Code-Regionen lesen Kontingentmetadaten ohne Modellaufruf. Claude zeigt Fünfstunden-, Wochen- und Modellfamilienfenster. Antigravity behält Modellgruppen bei; Kimi zeigt Wochen- und rollierende Fenster. Devin zeigt gemeldete Tages- und Wochenschnappschüsse. Grok- und Meta-Kontingente lassen sich über diese Gateway-Verbindung derzeit nicht auslesen.

Die Daten werden bei geöffneter Ansicht jede Minute aktualisiert, bei Claude alle fünf Minuten; manuelles Aktualisieren bleibt möglich. Ältere Daten werden als veraltet markiert. Fehler bleiben sichtbar; fehlende Daten bedeuten niemals ein volles Kontingent. Kimi Code (kimi.com) und Kimi Code (kimi.ai) sind getrennte regionale Anmeldungen, keine Verbraucher-Chatpläne.

Alle Verbindungsgruppen sind sofort sichtbar. Verbundene Abonnements zeigen ein Statusabzeichen und die Kontoidentität; ein weiteres Konto hinzuzufügen ist eine sekundäre Aktion. Beim erneuten Öffnen stellt die Auswahl die Abonnementquelle und das Modell aus dem gespeicherten Abonnementprofil wieder her.

Abonnementmodelle nutzen die Anweisungen und Werkzeuge von AgenticOS in der Laufzeit von Pydantic AI. Sie starten weder Claude Code noch einen anderen Coding-Harness. Unter Capabilities vereint **An Agenten delegieren** die Subagenten, **Claude Code und Codex** und **Weitere installierte Agenten**. Coding Agent bleibt in der Standardvorlage von AgenticOS aktiviert. Die Gruppen folgen täglicher Arbeit, Wissen, Recherche, Ergebnissen, Delegation, Automatisierung und Kanälen; erweiterte Einstellungen stehen eingeklappt am Ende. Innerhalb jeder Gruppe stehen aktivierte Capabilities zuerst, danach empfohlene.

Personen melden sich in der Konsole bei ihren eigenen Abonnements an, und
Modelle des Anbieters **Subscription accounts** laufen darauf. Unter
**Einstellungen → Abonnements** verbindet jede Person Konten von
Claude (Pro, Max), ChatGPT (Codex), Google Antigravity, Grok, Kimi, Devin oder
Meta AI. Eine Anmeldung zeigt einen Code, den du auf der Seite des Anbieters
eingibst, oder fragt nach der Adresse, auf der der Browser nach der Bestätigung
gelandet ist.

Ein Profil dieses Anbieters nimmt nur eine Modell-ID, ohne Schlüssel und ohne
Endpoint. **Add model** listet die Modelle, die deine eigenen Konten anbieten.
Chattet eine Person mit einem Agenten auf einem solchen Profil, nutzt der Lauf
die Konten dieser Person und keine anderen. Ein Lauf, den ein API-Schlüssel, ein
Besucher eines veröffentlichten Agenten oder Hintergrundarbeit startet, hat
keine Person dahinter und wird abgelehnt. Aus demselben Grund wählt die
Plattform ein solches Modell nie für einen neuen Agenten.

Der Dienst `subscription-gateway` gehört zum Stack und betreibt
[CLIProxyAPI](https://github.com/router-for-me/CLIProxyAPI) (MIT) einmal pro
Person und Organisation. Der Prozess einer Person startet bei der ersten
Nutzung und stoppt nach zehn Minuten Leerlauf. Jeder Prozess lauscht auf
Loopback mit eigenen Schlüsseln und eigenem Anmeldeverzeichnis, und die API
leitet aus Organisation und Person ab, welchen eine Anfrage erreicht; ein
Browser benennt ihn nie. Verlässt ein Mitglied die Organisation, löscht ein
Hintergrundjob seine Anmeldungen; das Löschen einer Organisation löscht die
aller Mitglieder. Dasselbe Konto in zwei Organisationen heißt zwei Anmeldungen.

Anbieter können die Nutzung eines Abonnements außerhalb ihrer eigenen Apps
einschränken und ein Konto dafür sperren. Die Konsole nennt dieses Risiko, und
die Kontoinhaberin oder der Kontoinhaber trägt es. Cursor und Qwen Code haben
keine Anmeldung, die das Gateway unterstützt, und werden daher nicht angeboten.
AgenticOS-Budgets erfassen diese Läufe ohne Preis, weil das verbleibende
Kontingent eines Abonnements nicht pro Token gemessen wird. Den Betrieb des
Gateways beschreibt die [Konfiguration](configuration.md#subscription-accounts).

### Selbst gehostet { #self-hosted }

| Provider | id | Zugangsdaten | Custom URL |
|---|---|---|---|
| System One API | `system-one` | API key, or none | ✓ |
| Ollama | `ollama` | keine | ✓ |
| LiteLLM proxy | `litellm` | keine | ✓ (`api_base`) |

Diese beiden sind der Grund, warum "keine Zugangsdaten" eine gespeicherte **Art**
ist und keine leere Zeichenkette. Ein Model Server im eigenen Netz hat meist
nichts, wogegen er authentifizieren könnte, und der Vault lehnt ein leeres Secret
ab — der Resolver schaltet also über eine vollständige Menge, statt einen
fehlenden Wert als Sonderfall zu behandeln.

**Ein Profile ohne Key braucht seinen Endpunkt, und das ist das Einzige, was es
braucht.** Das Key-Feld wird optional, sobald ein Endpunkt eingetragen ist. Ohne
Endpunkt wird das Profile abgelehnt: es gibt keine öffentliche API, auf die man
zurückfallen könnte, und nichts, womit man authentifizieren könnte.

!!! note "Der Endpunkt ist es, was ein Profile als selbst gehostet kennzeichnet, nicht `keyless`"

    `keyless` trifft auch auf `openai` zu. OpenAI-kompatible Server (vLLM, LM Studio,
    ein LiteLLM-Proxy) sprechen dessen Chat-Completions-API, und deshalb nutzt ein
    `openai`-Profile mit Endpunkt sie standardmäßig - siehe
    [Responses oder Chat Completions](#responses-or-chat-completions).

    "Kein Key" allein unterscheidet also ein bewusst lokales Modell nicht von einem
    Profile, dessen Key gelöscht wurde — und der Fremdschlüssel auf das Secret ist
    `ON DELETE SET NULL`, was den zweiten Fall gewöhnlich macht. Ein Run löst ein
    Profile ohne Key nur dann auf, wenn es einen Endpunkt trägt; sonst wird er mit
    derselben Meldung "no key configured" abgelehnt, die es immer schon gab.

### Eigener Endpunkt { #your-own-endpoint }

| Provider | id | Zugangsdaten | Custom URL |
|---|---|---|---|
| Custom (OpenAI-compatible) | `openai_compatible` | API-Key | ✓ |
| Custom (Anthropic-compatible) | `anthropic_compatible` | API-Key | ✓ |

Diese beiden sind eine API-*Form* und kein Anbieter. Sie tragen die Adresse
eines Servers ein, den Sie selbst betreiben, oder eines Gateways, dem Sie
vertrauen, sowie den Schlüssel, der ihn authentifiziert. Wählen Sie das, was zu
Ihrem Endpunkt passt:

| Ihr Endpunkt beantwortet | Wählen | Die Adresse zum Eintragen |
|---|---|---|
| `POST /chat/completions` — vLLM, LM Studio, ein LiteLLM-Proxy, die meisten Gateways | `openai_compatible` | die `/v1`-Wurzel, etwa `https://llm.example/v1` |
| `POST /v1/messages` — die eigene API-Form von Anthropic | `anthropic_compatible` | die API-Wurzel, etwa `https://llm.example` |

Beide brauchen einen Endpunkt und einen Schlüssel. Es gibt keine öffentliche
API, auf die man ausweichen könnte, also wird ein Profil ohne beides abgelehnt
und nicht irgendwohin geschickt.

Der Schlüssel liegt im Tresor unter dem Namen des Providers. Das sagt dort,
dass er *diesen* Endpunkt authentifiziert und nicht die öffentliche API eines
Anbieters. Deshalb sind es eigene Einträge und kein `openai`- oder
`anthropic`-Profil mit einem Endpunkt: Ein Schlüssel unter dem Namen eines
Anbieters spricht über diesen Anbieter.

!!! info "Die Anthropic-Adresse trägt kein `/v1`"

    Das SDK von Anthropic sendet an `<endpoint>/v1/messages`, der Endpunkt ist
    also die API-Wurzel. Eine Adresse, die bereits auf `/v1` endet, wird für Sie
    gekürzt, beide Schreibweisen funktionieren — die Plattform fragt aber nach
    der Wurzel.

**Load models** liest die Liste vom selben Endpunkt mit demselben Schlüssel, so
dass die Auswahl genau das anbietet, was Ihr Server ausliefert. Die Modell-ID
bleibt Freitext: Ein Server ohne veröffentlichte Liste ist trotzdem benutzbar,
wenn Sie die ID eintippen.

### Wenn die Zugangsdaten kein API-Key sind { #when-the-credential-is-not-an-api-key }

| Provider | id | Zugangsdaten |
|---|---|---|
| Azure OpenAI | `azure` | Key **+** Endpunkt **+** gepinnte API-Version |
| AWS Bedrock | `bedrock` | Access Key Id, Secret Key, Region, optionales Session-Token |
| Google Vertex AI | `google_cloud` | Service-Account-JSON |
| ChatGPT (Codex-Abonnement) | `openai_codex` | eine ChatGPT-Anmeldung, gespeichert durch Anmelden statt durch Eintippen |
| ChatGPT (offizielle Plannutzung) | `openai_chatgpt` | eine durch Anmeldung erstellte Anwendungsfreigabe mit gesonderter Planzustimmung |
| Abonnement-Konten | `subscription_accounts` | die eigenen Abonnement-Anmeldungen jeder Person, über das mitgelieferte Gateway; kein Schlüssel |

Die ersten drei sind der Grund, warum ein Secret überhaupt eine *Art* hat. Ein
Formular, das für Azure ein einzelnes undurchsichtiges Token einsammelte, würde
etwas einsammeln, das sich korrekt ausfüllen lässt und beim ersten Run trotzdem
scheitert. Siehe [Secret-Arten](secrets.md#kinds).

!!! note "Zwei Ids werden auf dem Weg zum SDK umgeschrieben"

    Ein `openai`-Profile wird je nach gespeicherter API als `openai-chat` oder
    `openai-responses` gebaut, ein `azure`-Profile als `azure` oder
    `azure-responses`, statt die Responses-API zu übernehmen, auf die schlichtes
    `openai` schließen lässt. Siehe
    [Responses oder Chat Completions](#responses-or-chat-completions).

    `google_cloud` wird als `google-cloud` gebaut. Keines von beidem ändert, was Sie
    speichern.

### Mit einem ChatGPT-Abonnement betreiben { #running-on-a-chatgpt-subscription }

`openai_codex` betreibt OpenAI-Modelle über das Codex-Backend mit einem
ChatGPT-Abonnement statt mit einem nach Verbrauch abgerechneten API-Key. Es ist
für den **persönlichen Gebrauch** gedacht: Die Anmeldung ist das Abonnement einer
Person, und jeder Run auf einem Profile, das sie verwendet, zählt gegen die
ChatGPT-Limits dieser Person.

Niemand kann die Zugangsdaten eintippen. Stattdessen melden Sie sich mit ChatGPT
an, standardmäßig mit einem kurzen Code:

1. Wählen Sie unter **Vault → add a secret** (oder unter **Agents → add a model**,
   mit ausgewähltem **ChatGPT (Codex subscription)**, oder unter **Settings →
   Coding accounts**) **Sign in with a code**. Die Geräteseite von ChatGPT öffnet
   sich in einem neuen Tab, und das Formular zeigt einen Code.
2. Geben Sie den Code auf dieser Seite ein und bestätigen Sie die Anmeldung. Das
   Formular bemerkt die Bestätigung selbst und schließt ab; nichts muss
   zurückkopiert werden.

Der Code gilt 15 Minuten, nur für die Person, die die Anmeldung gestartet hat.
Unterstützt Ihr Konto keine Gerätecodes, öffnen Sie **Paste an address instead**:
wählen Sie **Sign in with ChatGPT**, bestätigen Sie und fügen Sie die Adresse,
an die ChatGPT den Browser schickt (`http://localhost:1455/...`, die nicht lädt),
in das Formular ein. Auch diese Adresse funktioniert einmal, nur für die Person,
die die Anmeldung gestartet hat, und nur innerhalb von 15 Minuten.

Das Access-Token läuft ab und wird erneuert, während Modelle laufen. Jede
Erneuerung verbraucht das Refresh-Token, deshalb wird das neue Paar sofort wieder
im selben Vault-Secret versiegelt. Zwei Runs, die im selben Moment erneuern,
können trotzdem in eine Race Condition geraten. Der unterlegene wird abgelehnt,
und die Abhilfe ist **Reconnect** am Secret: Damit melden Sie sich erneut an,
ohne seine Id zu ändern.

!!! warning "Was eine ChatGPT-Anmeldung nicht ist"

    - **Sie ist nicht die `auth.json` der Codex CLI.** Diese Datei hält die eigene
      Berechtigung der CLI. Refresh-Tokens sind nur einmal verwendbar, also würde
      die Seite, die zuerst erneuert, die andere abmelden.
    - **Sie ist kein Zugang für die ganze Organisation.** Ein Secret wird
      standardmäßig privat angelegt, und ein Modell darauf läuft nur für jemanden,
      der die Anmeldung im Vault sehen darf und selbst fragt. Für alle anderen -
      Besucher einer öffentlichen Seite oder eines Embeds, Aufrufer mit API-Key -
      und für Arbeit im Hintergrund, etwa das Beschreiben der Bilder eines
      Dokuments, wird das Modell abgelehnt, und ein Fallback darauf wird
      übersprungen.
    - **Nicht jeder darf darauf veröffentlichen.** Das Veröffentlichen, das
      Zurückrollen auf oder das Promoten einer Version eines Agenten wird für
      jemanden abgelehnt, der die Anmeldung im Vault nicht sehen kann, wenn ein
      Modell, das seine Runs erreichen, darauf läuft: das Modell des Agenten,
      eines Reviewers, eines Inline-Spezialisten oder einer eingeschalteten
      Capability, das Modell eines
      [angehefteten Delegaten](reference/capabilities.md#delegation) und dessen,
      was dieser wiederum erreicht, oder einer der ersten drei Fallbacks eines
      dieser Modelle. Der Inhaber der Anmeldung, Owner und Admins sowie alle,
      mit denen sie geteilt wurde, dürfen es. Ein API-Schlüssel darf es nicht,
      was auch immer sein Aussteller sehen kann, denn ein Run unter einem
      Schlüssel verbraucht nie eine Anmeldung. Eine früher darauf
      veröffentlichte Version läuft weiter.
    - **Sie wird keinem Spezialisten angeboten, den das Modell erfindet.** Unter
      [`allow_dynamic`](reference/capabilities.md#delegation) darf das Modell
      eines Runs das Modell eines Spezialisten aus den Profilen der Organisation
      wählen. Ein Profil auf einer Anmeldung, oder eines, dessen erste drei
      Fallbacks eine erreichen, steht nur dann auf dieser Liste, wenn der Spec
      des Agents genau dieses Profil als eines der oben genannten Modelle nennt.
    - **Die angezeigten Ausgaben sind nicht Ihre Rechnung.** Ein Run wird zu den
      OpenAI-API-Preisen für dasselbe Modell bepreist, und damit kann ein
      [Budget](governance.md#budgets) rechnen. Das Abonnement selbst rechnet
      OpenAI zu einem Pauschalpreis ab.
    - **Manche Einstellungen werden ignoriert.** Das Codex-Backend verwirft
      `max_tokens`, `temperature` und `top_p`.

### Bewusst nicht vorhanden { #deliberately-absent }

Vier Namen, die Pydantic AI kennt, fehlen hier. `sentence-transformers` und
`voyageai` sind Embedding-Modelle, `bedrock-mantle` ist kein Chat-Provider, auf
den ein Profile zeigen kann, und `gateway` löst auf keine Provider-Klasse auf —
es ist ein Routing-Präfix über die anderen.

`tests/test_model_profiles.py` konstruiert jeden Eintrag des Katalogs, ein
Provider kann im Builder also nicht auswählbar sein, ohne zur Laufzeit
konstruierbar zu sein.

## Welche Liste welche Frage beantwortet { #which-list-answers-which-question }

Sechs Dinge in diesem Repository wissen etwas über Modelle und Provider, und sie
sind **nicht** sechs Kopien einer Liste. Jedes beantwortet eine andere Frage, und
das, von dem alle abgeleitet sind, ist das erste:

| Frage | Beantwortet von |
|---|---|
| Auf welche Provider darf ein Profile zeigen, und welche Zugangsdaten verlangt jeder? | `PROVIDERS` in `backend/app/agents/model_resolver.py` — **die Quelle der Wahrheit**, und nur für den Teil, den die Modell-Ableitung nicht wissen kann |
| Wie konstruiere ich den Client? | `pydantic_ai`s eigenes `infer_provider_class` / `infer_model`. Nicht die Sache dieser Plattform, und bewusst hier nicht wiederholt |
| Wie lese ich die Live-Modellliste dieses Providers? | `backend/app/core/catalog/model_listings.json` |
| Was schlage ich vor, wenn der Provider nicht gefragt werden kann? | `backend/app/core/catalog/curated_models.json` |
| Was kostet dieses Modell, und wie viel Kontext nimmt es? | der `genai-prices`-Snapshot, über `model_catalog.priced_model` |
| Welche Modelle zeichnen Bilder? | `backend/app/core/catalog/image_models.json`, dazu die eigene Antwort des SDK darauf, welche Provider überhaupt zeichnen können |

!!! info "Alles unterhalb der ersten Zeile ist von ihr abgeleitet"

    Eine abgeleitete Kopie, die abdriftet, lässt zur Laufzeit nichts scheitern. Sie
    zeigt eine Auswahl für einen Provider, den es nicht gibt, oder lässt einen weg,
    den es gibt.

    `tests/test_model_catalog.py::TestOneAnswerPerQuestion` ist das, was daraus
    stattdessen einen fehlschlagenden Build macht — und es verlangt, dass jeder
    Provider auf **dieser Seite** auftaucht.

Jeder Schlüssel in einer der beiden Katalogdateien muss einen Provider benennen,
den `PROVIDERS` hat. Das gilt auch für jeden Eintrag im Bildkatalog. Und jeder
Provider muss auf dieser Seite auftauchen. Den neunundzwanzigsten hinzuzufügen
ist eine Änderung plus alles, worum dieser Test dann bittet.

Zwei Überkreuzungen sind wissenswert, weil es Nachschläge sind, die ins Leere
gehen können:

- Der Preis-Snapshot schreibt vier Provider anders — `xai` ist `x-ai`, `bedrock`
  ist `aws`, `google_cloud` ist `google`, und `openai_codex` wird als `openai`
  bepreist — und `_PRICE_PROVIDER_ALIASES` überbrückt das.
- Der Bildkatalog trägt sein eigenes Paar aus `provider` und `prefix`, was
  wiederum ein drittes Vokabular ist.

## Welche Modelle ein Provider anbietet { #which-models-a-provider-offers }

Das Feld für die Model-Id wird aus zwei Quellen befüllt, in dieser Reihenfolge —
und bei sieben Providern aus keiner von beiden, was die Antwort laut ausspricht.

### Live { #live }

Dreißig Provider veröffentlichen einen Listen-Endpunkt, und das ist die einzige
Quelle, die von einem heute Morgen veröffentlichten Modell weiß:

`anthropic`, `openai`, `google`, `openrouter`, `groq`, `mistral`, `together`,
`cohere`, `deepseek`, `xai`, `sambanova`, `vercel`, `ovhcloud`, `huggingface`,
`cerebras`, `fireworks`, `nebius`, `moonshotai`, `zai`, `alibaba`,
`kimi_code`, `alibaba_coding_plan`, `opencode_go`, `ollama_cloud`, `cliproxyapi`, `nous_portal`,
`inception`, `cline`, `chutes`, `synthetic`.

Die Antwortformen sind uneinheitlich — das Array liegt bei `data`, bei `models`
oder in der Dokumentwurzel; die Id ist `id`, `name` oder `model`; Gemini stellt
ihr `models/` voran — jede wird deshalb durch Daten beschrieben statt durch einen
Zweig. Im Prozess eine Stunde lang zwischengespeichert; diese Listen bewegen sich
im Wochenrhythmus.

**Fünf davon brauchen überhaupt keine Zugangsdaten** — `openrouter`,
`sambanova`, `vercel`, `ovhcloud` und `huggingface` — und genau das macht sie
wertvoll: die Auswahl füllt sich, bevor irgendjemand einen Key für diesen
Provider hinterlegt hat. Die anderen fünfzehn werden mit dem eigenen Key der
Organisation gefragt, sofern es einen gibt.

Sechs Provider veröffentlichen weiterhin nichts, was sich hier lesen ließe:
`github` (der Pfad seines Katalogs ist verschwunden), `heroku`, `azure`,
`bedrock`, `google_cloud`, und ein `litellm`-Proxy, dessen Liste das ist, was das
Deployment dahintergesetzt hat. `ollama` antwortet im eigenen Netz des
Deployments statt unter einem festen Host und ist deshalb ebenfalls nicht
aufgeführt.

!!! warning "Eine leere Modalitätsliste bedeutet *nicht angegeben*, niemals 'nur Text'"

    `openrouter` und der Hugging-Face-Router tragen beide
    `architecture.output_modalities`, und ein Listing-Eintrag kann diesen Pfad
    benennen. Sonst gibt ihn niemand an.

    Ein Client, der danach filtert, muss Abwesenheit als unbekannt behandeln, sonst
    verbirgt er Modelle, die funktionieren. Es sind Metadaten, auf die ein Client
    einschränken darf; es ist *nicht* die Art, wie die Bild-Capability ihre Modelle
    auswählt — das ist eine Katalogdatei plus die eigene Antwort des SDK darauf,
    welche Provider überhaupt zeichnen können, siehe
    [Bilderzeugung](reference/capabilities.md#image-generation).

### Kuratiert { #curated }

Eine kurze Liste pro Provider, verwendet, wenn der Provider nichts
veröffentlicht, wenn der Aufruf fehlschlägt oder wenn es keinen Key gibt, mit dem
man ihn machen könnte.

Sie liegt in `backend/app/core/catalog/curated_models.json` neben den anderen
Deployment-Katalogen, ein Modell hinzuzufügen ist also ein Eintrag statt einer
Python-Änderung — und die Listings selbst sind `model_listings.json` im selben
Verzeichnis, was auch aus dem Endpunkt eines neuen Providers Daten macht.

Sie ist bewusst kurz und bewusst **nicht** aus `genai-prices` übernommen, das
ohnehin schon eine Abhängigkeit ist und Modelle auflistet.

Das ist ein *Preis*-Datensatz. Er führt `ada` und `babbage` unter OpenAI,
`claude-2` unter Anthropic, 690 Zeilen unter OpenRouter, und er markiert so gut
wie nichts als veraltet — alphabetisch sortiert wäre das Erste, was eine Auswahl
für OpenAI anbietet, `ada`. Eine kurze aktuelle Liste schlägt eine lange
irreführende.

Wofür die Bibliothek *doch* verwendet wird, ist die Hälfte, die verrottet. **Jede
Kontextlänge kommt zum Lesezeitpunkt aus dem Snapshot**, hier ist also kein
Fenster niedergeschrieben; zwei, die es waren, waren bereits veraltet, eines
davon zweimal mit zwei verschiedenen Zahlen erfasst.

Und eine kuratierte Id, von der der Snapshot nie gehört hat, lässt die Testsuite
scheitern, so wird ein Tippfehler oder ein ausgemustertes Modell abgefangen statt
als Dropdown ausgeliefert, auf das der Provider mit 404 antwortet. Ein Modell,
das der Snapshot kennt, aber nicht bepreist, hat schlicht kein Fenster — das ist
das unten beschriebene Null.

Die Modellauswahl verwendet beim Öffnen die Liste des Deployments. Ein kontospezifischer Live-Katalog wird nicht abgerufen. Die GPT-6.2-Einträge wurden über den Codex App Server geprüft. Das Kontextfenster bleibt leer, bis es im Preiskatalog steht.

| Provider | Kuratierte Ids |
|---|---|
| `anthropic` | `claude-opus-5`, `claude-sonnet-5`, `claude-fable-5`, `claude-haiku-4-5` |
| `openai` | `gpt-5.6-sol`, `gpt-5.6-terra`, `gpt-5.6-luna`, `gpt-5.3-codex` |
| `openai_codex` | GPT-6.2 Sol und Astra, GPT-6.1 Sol und Terra, GPT-6 Sol, Astra und Luna sowie frühere Codex-IDs |
| `google` | `gemini-3.6-flash`, `gemini-3.5-flash`, `gemini-3.5-flash-lite`, `gemini-3.1-pro-preview` |
| `deepseek` | `deepseek-v4-pro`, `deepseek-v4-flash` |
| `xai` | `grok-4.5`, `grok-4.3` |
| `groq` | `openai/gpt-oss-120b`, `llama-3.3-70b-versatile` |
| `openrouter` | fünf verbreitete Ids über mehrere Provider hinweg |

### Keins von beiden, und es sagt das auch { #neither-and-it-says-so }

Sieben Provider veröffentlichen kein Listing, das diese Plattform lesen kann, und
haben keinen kuratierten Eintrag — `github`, `heroku`, `ollama`, `litellm`,
`azure`, `bedrock` und `google_cloud`.

Das `source` der Antwort lautet für diese `unlisted`, **nicht** `curated`. Eine
leere Auswahlliste ist keine Auswahlliste, und eine zu behaupten ist das, was aus
"diese Plattform kann diesen Provider nicht aufzählen" ein "dieser Provider hat
keine Modelle" macht (#923). Die Auswahl fragt stattdessen nach der Id.

`ollama` und `litellm` sind die, bei denen sich die Verdrahtung lohnt — beide
veröffentlichen ein OpenAI-förmiges `/v1/models` unter dem Endpunkt, den das
Profile ohnehin speichert — und dafür muss dem Listing eine Basis-URL mitgeteilt
werden, was eine feste `ListingSpec.url` nicht sein kann.

Keine der beiden Quellen ist maßgeblich, und deshalb bleibt das Feld Freitext.

## Das Fenster, das ein Modell annimmt, wird einmal gelesen und behalten { #the-window-a-model-accepts-is-read-once-and-kept }

Ein Listing trägt meist mit, wie viele Token das Modell annimmt, und das Profile
hält das bei seiner Anlage als `context_length` fest.

Diese Zahl ist es, worauf das
[Kontextmanagement](reference/capabilities.md#context-management) auslöst: bei
einem Bruchteil des Fensters zu verdichten ist die einzige Einstellung, die
richtig bleibt, wenn ein Agent auf ein anderes Modell umzieht.

!!! danger "Warum sie gespeichert und nicht pro Run aufgelöst wird"

    Der Anfragepfad darf keinen Provider aufrufen, und das Einzige, was er sonst
    heranziehen könnte, ist der mitgelieferte Preis-Snapshot — der hier in genau der
    Richtung falsch liegt, die einen Run kaputtmacht.

    Dieser Snapshot verzeichnet 1.000.000 für `anthropic:claude-sonnet-4-5` gegen
    reale 200.000, ein Auslöser bei 90 % landet also oberhalb der echten Obergrenze,
    und die Verdichtung greift nie, bevor der Provider die Anfrage ablehnt. Ein
    Profile mit Fallbacks ist schlimmer: es baut ein `FallbackModel`, dessen
    zusammengesetzte Id auf gar nichts auflöst.

Null bedeutet **nicht erfasst**, nicht null als Zahl: ein Profile, das älter ist
als die Spalte, ein Provider, der keine Länge veröffentlicht, eine kuratierte
Liste, oder ein Listing, das nicht erreicht werden konnte. Die Capability löst
das Fenster dann selbst auf, genau wie zuvor.

Wenn Sie es besser wissen als beide, setzen Sie `context_window` am Binding. Ein
Provider veröffentlicht das Maximum, das sich ein Modell annehmen *lässt*, und
ein Beta- oder stufenbeschränktes Deployment bekommt weniger.

Eine Kette von Fallbacks trägt die Zahl des **primären**. Ein `FallbackModel` hat
kein eigenes Fenster, und welches Modell ein Run erreicht, ist erst bekannt,
wenn eines abgelehnt hat.

## Was ein Run kostet { #what-a-run-costs }

Die Preise stammen aus einem mitgelieferten
[`genai-prices`](https://github.com/pydantic/genai-prices)-Snapshot. Nichts ruft
dafür zu Hause an, was zwei wissenswerte Dinge bedeutet:

- Ein Modell, das für den Snapshot zu neu ist, ist **unbepreist**, und ein Run,
  der eines enthält, wird als *teilweise bepreist* erfasst und nicht als
  kostenlos. Ein Budget, das ein unbekanntes Modell stillschweigend als gratis
  behandelte, wäre ein Budget mit einem Loch darin.
- Ein `vendor/model` eines Aggregators, das der Snapshot nicht kennt, wird wie das
  eigene Modell des Anbieters bepreist, eine Version mit Punkt wird auch mit
  Bindestrichen versucht: OpenRouters `anthropic/claude-sonnet-5.5` kostet, was
  Anthropics `claude-sonnet-5-5` kostet.
- Preise zu aktualisieren ist ein Abhängigkeits-Update.

!!! warning "Ein Provider ohne Key erfasst keine Ausgaben"

    Ausgaben werden dem [Vault-Secret](secrets.md) zugerechnet, auf das der Run
    aufgelöst hat, und ein Provider ohne Key hat keines, dem sie zuzurechnen wären.

Die Kosten werden *vor* jeder Modellanfrage geprüft und auch dann erfasst, wenn
der Run fehlschlägt. Siehe [Budgets](governance.md#budgets).

### Eine Delegation löst ihr eigenes Profile auf { #a-delegation-resolves-its-own-profile }

Ein Run kann mehrere Modelle einbeziehen.

Ein [Delegate](concepts.md#delegate-vs-inline-specialist) läuft auf dem Profile,
das *sein eigener* Spec benennt, aufgelöst, wenn der Runner den Delegationsbaum
abläuft. Ein Inline-Spezialist, der keines benennt, läuft auf dem Profile des
Agents, der ihn aufgerufen hat — die am wenigsten überraschende Antwort und
zugleich die einzige, die funktioniert, wenn das des Elternteils das einzige
Profile ist, das der Autor gewählt hat.

Diese Anfragen werden gegen das eine Hauptbuch des Eltern-Runs gemessen, aber sie
werden **pro Provider bepreist**: die Schranke des Delegate teilt sich Hauptbuch,
Obergrenzen und die Ausgangswerte des Monats und nimmt ihren eigenen Provider.

Den des Elternteils rundheraus zu teilen würde einen Anthropic-Delegate gegen den
Katalog von OpenAI bepreisen — stillschweigend, und meist als unbepreist, was den
Run zu niedrig ausweist und einen vollkommen bepreisbaren als Untergrenze
kennzeichnet.

Die Zeile des Kind-Runs, die eine Delegation schreibt, benennt das Modell, das
geantwortet hat, das Kosten-Dashboard gruppiert einen delegierten Zug also unter
dem Modell, das tatsächlich lief, statt unter dem des Elternteils.

## Realtime-Modelle { #realtime-models }

Ein [Sprachanruf](voice.md) verwendet kein Model Profile. Sein Modell ist eine
Auswahl aus einem Katalog, den dieses Deployment mitliefert,
`backend/app/core/catalog/realtime_models.json`, gelesen von
`backend/app/services/realtime_models.py` und dem Builder unter
`GET /api/v1/providers/realtime-models` ausgeliefert. Der Key wird im Abschnitt
Sprachgespräche (Voice conversations) des Agents als Vault-Secret benannt, nicht
auf einem Profile. Das ist dieselbe Form, die Speech-to-Text verwendet: eine
Auswahl aus dem Katalog plus ein ausdrücklicher Key.

Jeder Eintrag benennt einen Provider, seine Modelle und für jedes Modell:

| Feld | Was es entscheidet |
|---|---|
| `transport` | `webrtc` (der Browser spricht mit dem Provider; dieses Deployment hält eine Sideband-Verbindung) oder `relay` (das Audio geht durch den Socket dieses Deployments) |
| `input_sample_rate`, `output_sample_rate` | Die PCM-Raten, mit denen der Browser über das Relay aufnimmt und abspielt |
| `voices`, `default_voice` | Was der Abschnitt Sprachgespräche anbietet und was eine leere Auswahl bedeutet |
| `supports_thinking` | Ob die Thinking-Capability des Agents auf die eigene Reasoning-Einstellung des Modells abgebildet wird |
| `context_window` | Ab wann eine Wiederverbindung nicht mehr die Züge nachspielt, sondern eine Zusammenfassung der älteren |
| `pricing` | `kind` (`tokens` oder `per_minute`), `worst_case_usd_per_minute` für die Prüfung vor einem Anruf und `usd_per_minute` für ein Modell mit Minutenpreis |

Die `gpt-realtime`-Familie von OpenAI läuft über WebRTC und ist der einzige
live getestete Provider. Azure OpenAI, Gemini Live und xAI laufen über das Relay
und sind **nicht live verifiziert**. GPT-Live steht nicht im Katalog: Es kann
nach dem Start einer Sitzung keinen Verlauf mehr aufnehmen, also könnte eine
Wiederverbindung einen Anruf nicht fortsetzen.

**Azure ist ein Deployment plus ein Basismodell.** Den Namen eines Deployments
wählt sein Besitzer, und er sagt nichts darüber, was darauf läuft, also nimmt
der Abschnitt Sprachgespräche den Deployment-Namen als Freitext und das
Katalogmodell, das darauf läuft, als `base_model`. Das Basismodell bestimmt die
Stimmen und den Preis: Die Tokens eines Azure-Anrufs werden wie dieses Modell
bei OpenAI bepreist. Endpunkt und API-Version kommen aus dem
`azure_openai`-Secret.

**Preise.** Modelle mit Tokenpreis werden pro Antwort aus demselben
mitgelieferten Snapshot bepreist wie Text-Runs. Ein Modell mit Minutenpreis
(xAI) wird für die verbundene Zeit zum `usd_per_minute` des Katalogs
abgerechnet. Ein Modell mit Tokenpreis, das der Snapshot nicht bepreisen kann,
wird beim Start eines Anrufs abgelehnt, statt mit einem Budget zu laufen, das
es nicht durchsetzen kann.

## Zusammenfassung { #recap }

- Ein **Profile** ist ein benanntes Modell plus ein benannter Key, und Agents
  zeigen auf Profiles, damit das Rotieren des einen oder anderen eine Zeile
  berührt.
- **28 Provider**, und das Einzige, was diese Plattform über jeden weiß, ist die
  Form der Zugangsdaten — die Konstruktion ist Sache von Pydantic AI.
- Die Model-Id ist **Freitext**, weil keine Liste maßgeblich ist.
- Die **Kontextlänge** wird einmal gelesen und gespeichert, weil der
  Preis-Snapshot in genau der Richtung darüber falsch liegt, die einen Run
  kaputtmacht.
- Die **Kosten** kommen aus einem mitgelieferten Snapshot, ein unbekanntes Modell
  wird als unbepreist statt als kostenlos erfasst, und ein Provider ohne Key
  erfasst überhaupt keine Ausgaben.
- **Realtime-Modelle** für Sprachanrufe sind eine Auswahl aus dem Katalog plus
  ein benannter Key, ohne Profile; nur die von OpenAI sind live verifiziert.

## Eines einrichten { #setting-one-up }

Die [Anleitung zum ersten Agent](first-agent.md) macht das von Anfang bis Ende.
Kurz gesagt: hinterlegen Sie einen Provider-Key unter **Settings → Secrets**,
legen Sie ein Model Profile an, das ihn benennt, und lassen Sie dann den Spec
eines Agents auf das Profile zeigen.

```bash
make platform-bootstrap BOOTSTRAP_API_KEY=sk-...
```

erledigt alle drei Schritte für ein neues Deployment.

Für eine regionale OpenRouter-API bleibt **OpenRouter** der Anbieter. Trage im Modellformular unter **Endpoint** `https://eu.openrouter.ai/api/v1` ein. Das Profil behält seinen OpenRouter-Schlüssel aus dem Vault, die native Modellverarbeitung und die Cache-Steuerung. Modellvorschläge stammen von diesem Endpunkt und werden separat zwischengespeichert; eine fehlgeschlagene regionale Abfrage wechselt nicht zum globalen Katalog. Lege für Wissensbasen den Embedding-Endpunkt beim Erstellen oder Bearbeiten des Embedding-Anbieters separat fest. Bestehende Konfigurationen behalten den globalen Endpunkt. EU-Routing erfordert einen passenden OpenRouter-Business- oder Enterprise-Tarif; [regionales Routing](https://openrouter.ai/docs/guides/get-started/sovereign-ai) und ZDR sind getrennte OpenRouter-Richtlinien.

Ein regionaler Endpunkt stellt weniger Embedding-Modelle bereit als der globale: `eu.openrouter.ai` bietet `mistralai/mistral-embed-2312`, `mistralai/codestral-embed-2505` und `google/gemini-embedding-2`, aber keines von OpenAI. Das Anlageformular bietet nur die Modelle an, die der Endpunkt aufführt, und eine Collection, deren Modell der Endpunkt nicht bereitstellt, wird abgelehnt, sowohl beim Erstellen als auch beim Verschieben dorthin. Die beiden Mistral-Modelle fehlen im mitgelieferten Preis-Snapshot, daher werden ihre Kosten als teilweise bepreist erfasst.

Aktualisiere alle API- und Worker-Prozesse, bevor du regionale Endpunkte konfigurierst. Ältere Versionen ignorieren den überschriebenen OpenRouter-Endpunkt.

Für einen weiteren Endpunkt mit demselben Anbieter und Modell wählen Sie im Builder **Separates Modell hinzufügen**. Der automatische Name enthält den Endpunkt; das vorhandene Profil bleibt unverändert. **Modell aktualisieren** bearbeitet stattdessen das gemeinsame Profil. Benutzerdefinierte Kataloge sind auf 2 MiB, 2.048 Modelle und begrenzte Feldlängen beschränkt; jeder Prozess speichert höchstens 16 Kataloge. Bei komprimierten oder übergroßen Antworten bleibt die Modell-ID frei eingebbar, ohne auf eine globale Liste auszuweichen.

## Entscheidungsmodelle { #decision-models }

Entscheidungsprofile verwenden die native API `decisions` statt Textgenerierung. Anbieter, Modell und Tresorschlüssel werden im Modellformular gewählt. OpenAI, Google und OpenRouter bieten Chat- und Entscheidungs-APIs; TypeSafe und ein eigener System-One-Endpunkt dienen Entscheidungen. Ein Entscheidungsprofil kann weder das Gesprächsmodell eines Agents sein noch auf ein Chatmodell zurückfallen.

Die Adapter stammen aus Pydantic AI. Aktuelle Vorschläge umfassen OpenAI `gpt-6-luna`, Google `gemini-decision-1` und TypeSafe `jev-1.14.0` / `jev-latest`. OpenRouter lädt Entscheidungsmodelle getrennt von Textmodellen. Ein eigener System-One-Endpunkt benötigt URL und Modell-ID. Verfügbarkeit und Kontozugang bestimmt der Anbieter; Vorschläge garantieren keinen Zugang.

Die Workflow-Schritte **Decision models** wählen ein natives Profil. Bestehende `decide.*`-IDs und TypeSafe-Schlüsselkonfigurationen bleiben gültig. Unterhalb der Konfidenzschwelle folgt der Schritt dem Port `unsure`. Jede Ausführung prüft Schlüssel und Berechtigungen erneut; Kosten zählen zum Workflow- und Organisationsbudget.

Automatisches Mitreden in Kanälen kann ein natives Modell oder ein gewöhnliches LLM mit strukturierter Ausgabe verwenden. Native Ja/Nein-Entscheidungen liefern die Wahrscheinlichkeit des Mitredens; ein begrenztes Zahlenfeld erhält diesen Wert. Ein LLM liefert eine Nützlichkeitsbewertung von 0 bis 100, keine kalibrierte Wahrscheinlichkeit. Beide werden einschließlich Gleichheit mit dem Schwellenregler verglichen. Der Klassifikator hat keine Tools. Die Funktion ist optional und beachtet die Intervalle; der Hauptagent darf organisatorische MCP-Konten nutzen, niemals private Zugangsdaten eines Teilnehmers.

Anbieterquellen: [Pydantic AI](https://pydantic.dev/docs/ai/models/decision/), [OpenAI](https://developers.openai.com/api/docs/guides/decisions), [Google](https://ai.google.dev/gemini-api/docs/decisions-api), [TypeSafe](https://docs.typesafe.ai/models), [OpenRouter](https://github.com/OpenRouterTeam/skills/tree/main/skills/openrouter-decisions).

ElevenLabs Realtime bietet `eleven_realtime_v1_mini` und `eleven_realtime_v1_max` über das PCM-Relay mit 24 kHz, der Standardstimme `brian` und semantischer Sprecherkennung.

Das SDK meldet keine Tokenkosten. Anrufe mit einem Ausgabenbudget werden vor dem Verbindungsaufbau abgelehnt. Ohne Ausgabenbudget gilt weiterhin das Zeitlimit; Audiokosten werden als Untergrenze statt als vollständige Rechnung erfasst. Der Audiotarif beträgt 0,08 USD/Minute beziehungsweise 0,16 USD bei Burst; Tokenkosten kommen hinzu. Der Kontextwert von 16k ist ein konservatives Plattformlimit für den Verlauf, kein veröffentlichtes Kontextfenster des Anbieters. Die Integration wurde offline mit SDK-Modellkonstruktion und kontrollierten Transporten geprüft, nicht mit einem echten Konto. [SDK](https://pydantic.dev/docs/ai/api/realtime/elevenlabs/), [ElevenLabs API pricing](https://elevenlabs.io/pricing/api).

## GitHub Copilot-Konten { #github-copilot-accounts }

**GitHub Copilot** (`github_copilot`) verwendet Pydantic AIs Copilot-Modelldialekt, getrennt von GitHub Models (`github`). Explizite Vault-Zugangsdaten gehen an das feste Gateway `https://api.githubcopilot.com`, mit AgenticOS-Integrationsidentität und ohne VS Code-Editorheader. Anfrageeinstellungen können weder Konto noch Integrationsidentität ersetzen. Eigene und Enterprise-Gateways werden nicht unterstützt.

Ein Modelladministrator kann ein genehmigtes Profil mit einem Copilot-Bearer-Token im Vault konfigurieren. Ein allgemeines GitHub-API-Token belegt keinen Copilot-Zugriff. Wählen Sie persönliche Modellzugangsdaten für einen geteilten Agenten, damit jedes Mitglied sein Konto in den Chat-Einstellungen verbindet. Der Betreiber muss `GITHUB_COPILOT_OAUTH_CLIENT_ID` auf die eigene AgenticOS OAuth App mit aktiviertem Device Flow setzen. Mitglieder öffnen GitHub, bestätigen den in AgenticOS angezeigten Code und prüfen die Autorisierung. Gerätecode und Token stehen nie in einer URL. Wiederverbinden wiederholt den Ablauf; Trennen entfernt das private gespeicherte Token, die OAuth-Freigabe widerruft man separat in GitHub.

GitHub-Anmeldung genügt nicht: Vor dem Speichern prüft AgenticOS, ob Konto und Anwendung das gewählte Modell über `/chat/completions` anbieten. Kataloge sind kontobezogen, nach unterstützten Endpunkten gefiltert und ohne globalen Ersatzkatalog. Copilot Responses, Messages, Embeddings und Realtime werden nicht angeboten. Persönliche Verbindungen bleiben auf angemeldete Web-Chats begrenzt, ohne Ersatz durch Organisationsschlüssel oder andere Anbieter.

Der Device Flow akzeptiert nicht ablaufende OAuth-App-Freigaben. Ablaufende oder erneuerbare GitHub-App-Freigaben werden ausdrücklich abgelehnt; Erneuerung ist nicht implementiert, Refresh-Token werden nicht verworfen. Berechtigungen, Richtlinien, Widerruf und Kontingente erfordern Wiederverbinden oder Kontoaktionen. Ein Modellname bestimmt keine Abonnementkosten: Copilot-Plannutzung bleibt bis zur Prüfung einer USD-Abrechnung unbepreist; Kontingentwerte sind keine Dollarbeträge. Abnahme mit echtem Konto, eigener OAuth App und AgenticOS-Identität bleibt offen. Siehe [Pydantic AI Copilot](https://pydantic.dev/docs/ai/models/github-copilot/) und [GitHub OAuth](https://docs.github.com/en/copilot/how-tos/copilot-sdk/setup/github-oauth).

## Offizielle ChatGPT-Plannutzung { #official-chatgpt-plan-usage }

**ChatGPT plan usage (official)** verwendet eine anwendungsspezifische Freigabe und die öffentliche Responses API. **ChatGPT (Codex subscription)** bleibt die getrennte Codex-Backend-Integration. Anmeldungen, Tresortypen und Tokens sind nicht austauschbar.

Die Funktion ist standardmäßig deaktiviert. Der Betreiber muss die Berechtigung prüfen, `OPENAI_CHATGPT_PLAN_USAGE_ENABLED=true` setzen und eine UUID in `OPENAI_CHATGPT_HOST_ID` über Neustarts und Replikate beibehalten. Kostenpflichtige oder entfernt gehostete Anwendungen benötigen OpenAIs Zustimmung. Die Einstellungen bestätigen die Betreiberentscheidung; sie holen keine Zustimmung ein. Stelle vor erneutem Verbinden die ursprüngliche Host-UUID wieder her.

Wähle den offiziellen Anbieter im Tresor oder bei der Modellauswahl, melde dich an und füge die abschließende Adresse `http://127.0.0.1:1455/auth/callback?...` ein. Die Freigabe wird privat gespeichert. Nur der Eigentümer darf sie nutzen; geteilte Profile, API-Schlüssel und Hintergrundarbeit verleihen sie keinem anderen Mitglied. Eine abgelehnte Planfreigabe speichert Registrierung und Grant, zeigt eine Warnung und erlaubt keine Inferenz. Verbinde erneut, um Zustimmung anzufordern. Ausgestellte Client-Registrierungen überleben fehlgeschlagene Token-Austausche. Callbacks sind einmalig und an Mitglied sowie Organisation gebunden; eine neue Anmeldung ersetzt frühere.

Wähle ein Modell aus dem aktuellen Katalog des gewählten Kontos. Es gibt keinen Ersatz durch einen globalen API-Schlüsselkatalog. Token-Rotation schreibt bedingt in den Tresor. Jede Modellanfrage prüft Widerruf und aktuelle Mitgliedschaft des Eigentümers. Lösche den Tresor-Grant zum lokalen Trennen; widerrufe den Zugriff in ChatGPT-Einstellungen bei OpenAI. Registrierungsmetadaten bleiben für erneutes Verbinden erhalten.

Pydantic AI erzwingt Streaming, `store=false`, lokalen Verlauf und den unterstützten Vorschau-Dialekt. Abruf suspendierter Antworten, Batch API und nicht unterstützte gehostete Werkzeuge stehen nicht zur Verfügung. Offizielle Plannutzung nimmt an keinem automatischen Modell-Fallback teil. Kosten bleiben in AgenticOS unbepreist; ein API-Preis beweist keine Planabrechnung. Kontoberechtigung, Kontingent und Abrechnung erfordern Tests mit einem berechtigten Konto. Siehe [OpenAIs Ablauf](https://developers.openai.com/siwc/token-sharing-open-source) und [Pydantic AIs Adapter](https://pydantic.dev/docs/ai/models/openai-chatgpt/).
