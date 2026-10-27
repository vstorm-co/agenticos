---
source_sha: "03612a4d4028"
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

Der Reasoning-Aufwand steht **nicht** hier. Er ist die
[`thinking`-Capability](reference/capabilities.md#thinking), denn "denk
gründlicher" ist eine Entscheidung darüber, wofür der Agent *da ist*, und kein
Regler an einer Verbindung — und weil ein Spec, der das als Model Setting setzt,
über einen Modellwechsel hinweg aufhört, portabel zu sein.

### Responses oder Chat Completions { #responses-or-chat-completions }

OpenAI veröffentlicht zwei APIs für dieselben Modelle, und ein Profile auf `openai`
oder `azure` speichert, an welche davon seine Requests gehen: `responses` oder
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

## Provider { #providers }

Achtundzwanzig, also alles, was Pydantic AI ausliefert und worauf ein
Chat-Profile zeigen kann.

Es gibt hier keinen Builder pro Provider. Pydantic AI leitet die Provider-Klasse
und den Model-Wrapper aus der Id ab, und was diese Plattform weiterhin wissen
muss, ist der Teil, den die Ableitung nicht kennen kann: **welche Form von
Zugangsdaten ein Provider verlangt.**

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
| OpenRouter | `openrouter` | API-Key | |
| Alibaba Cloud | `alibaba` | API-Key | ✓ |
| Cerebras | `cerebras` | API-Key | |
| DeepSeek | `deepseek` | API-Key | |
| Fireworks AI | `fireworks` | API-Key | |
| GitHub Models | `github` | API-Key | |
| Groq | `groq` | API-Key | |
| Heroku AI | `heroku` | API-Key | ✓ |
| Mistral | `mistral` | API-Key | |
| Moonshot AI | `moonshotai` | API-Key | |
| Nebius AI Studio | `nebius` | API-Key | |
| OVHcloud AI Endpoints | `ovhcloud` | API-Key | |
| SambaNova | `sambanova` | API-Key | ✓ |
| Together AI | `together` | API-Key | |
| Vercel AI Gateway | `vercel` | API-Key | |
| Z.AI | `zai` | API-Key | |
| xAI (Grok) | `xai` | API-Key | ✓ (`api_host`) |
| Cohere | `cohere` | API-Key | |
| Hugging Face | `huggingface` | API-Key | ✓ |

### Selbst gehostet { #self-hosted }

| Provider | id | Zugangsdaten | Custom URL |
|---|---|---|---|
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

### Wenn die Zugangsdaten kein API-Key sind { #when-the-credential-is-not-an-api-key }

| Provider | id | Zugangsdaten |
|---|---|---|
| Azure OpenAI | `azure` | Key **+** Endpunkt **+** gepinnte API-Version |
| AWS Bedrock | `bedrock` | Access Key Id, Secret Key, Region, optionales Session-Token |
| Google Vertex AI | `google_cloud` | Service-Account-JSON |
| ChatGPT (Codex-Abonnement) | `openai_codex` | eine ChatGPT-Anmeldung, gespeichert durch Anmelden statt durch Eintippen |

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
an:

1. Wählen Sie unter **Vault → add a secret** (oder unter **Agents → add a model**,
   mit ausgewähltem **ChatGPT (Codex subscription)**) **Sign in with ChatGPT**.
   Eine ChatGPT-Anmeldung öffnet sich in einem neuen Tab.
2. Bestätigen Sie sie. ChatGPT schickt den Browser danach an
   `http://localhost:1455/...`, und diese Adresse lädt nicht. Das ist so
   vorgesehen: OpenAI legt diese Adresse für jeden Client außer dem eigenen fest.
3. Kopieren Sie die vollständige Adresse aus der Adressleiste und fügen Sie sie
   wieder in das Formular ein.

Der Code in dieser Adresse funktioniert einmal, nur für die Person, die die
Anmeldung gestartet hat, und nur innerhalb von 15 Minuten.

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

Zwanzig Provider veröffentlichen einen Listen-Endpunkt, und das ist die einzige
Quelle, die von einem heute Morgen veröffentlichten Modell weiß:

`anthropic`, `openai`, `google`, `openrouter`, `groq`, `mistral`, `together`,
`cohere`, `deepseek`, `xai`, `sambanova`, `vercel`, `ovhcloud`, `huggingface`,
`cerebras`, `fireworks`, `nebius`, `moonshotai`, `zai`, `alibaba`.

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

| Provider | Kuratierte Ids |
|---|---|
| `anthropic` | `claude-opus-5`, `claude-sonnet-5`, `claude-fable-5`, `claude-haiku-4-5` |
| `openai` | `gpt-5.6-sol`, `gpt-5.6-terra`, `gpt-5.6-luna`, `gpt-5.3-codex` |
| `openai_codex` | dieselben vier wie `openai` |
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
