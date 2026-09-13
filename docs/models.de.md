---
source_sha: d4f249f20433
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

### Fallbacks { #fallbacks }

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

Der Reasoning-Aufwand steht **nicht** hier. Er ist die
[`thinking`-Capability](reference/capabilities.md#thinking), denn "denk
gründlicher" ist eine Entscheidung darüber, wofür der Agent *da ist*, und kein
Regler an einer Verbindung — und weil ein Spec, der das als Model Setting setzt,
über einen Modellwechsel hinweg aufhört, portabel zu sein.

## Provider { #providers }

Siebenundzwanzig, also alles, was Pydantic AI ausliefert und worauf ein
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
    ein LiteLLM-Proxy) sprechen dessen Chat-Completions-API, und deshalb wird ein
    `openai`-Profile als `openai-chat` gebaut.

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

Diese drei sind der Grund, warum ein Secret überhaupt eine *Art* hat. Ein
Formular, das für Azure ein einzelnes undurchsichtiges Token einsammelte, würde
etwas einsammeln, das sich korrekt ausfüllen lässt und beim ersten Run trotzdem
scheitert. Siehe [Secret-Arten](secrets.md#kinds).

!!! note "Zwei Ids werden auf dem Weg zum SDK umgeschrieben"

    Ein `openai`-Profile wird als `openai-chat` gebaut, weil schlichtes `openai` auf
    die Responses-API schließen lässt und OpenAI-kompatible Server — vLLM, LM Studio,
    ein LiteLLM-Proxy — diese nicht implementieren.

    `google_cloud` wird als `google-cloud` gebaut. Keines von beidem ändert, was Sie
    speichern.

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
Provider muss auf dieser Seite auftauchen. Den achtundzwanzigsten hinzuzufügen
ist eine Änderung plus alles, worum dieser Test dann bittet.

Zwei Überkreuzungen sind wissenswert, weil es Nachschläge sind, die ins Leere
gehen können:

- Der Preis-Snapshot schreibt drei Provider anders — `xai` ist `x-ai`, `bedrock`
  ist `aws`, `google_cloud` ist `google` — und `_PRICE_PROVIDER_ALIASES`
  überbrückt das.
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

## Zusammenfassung { #recap }

- Ein **Profile** ist ein benanntes Modell plus ein benannter Key, und Agents
  zeigen auf Profiles, damit das Rotieren des einen oder anderen eine Zeile
  berührt.
- **27 Provider**, und das Einzige, was diese Plattform über jeden weiß, ist die
  Form der Zugangsdaten — die Konstruktion ist Sache von Pydantic AI.
- Die Model-Id ist **Freitext**, weil keine Liste maßgeblich ist.
- Die **Kontextlänge** wird einmal gelesen und gespeichert, weil der
  Preis-Snapshot in genau der Richtung darüber falsch liegt, die einen Run
  kaputtmacht.
- Die **Kosten** kommen aus einem mitgelieferten Snapshot, ein unbekanntes Modell
  wird als unbepreist statt als kostenlos erfasst, und ein Provider ohne Key
  erfasst überhaupt keine Ausgaben.

## Eines einrichten { #setting-one-up }

Die [Anleitung zum ersten Agent](first-agent.md) macht das von Anfang bis Ende.
Kurz gesagt: hinterlegen Sie einen Provider-Key unter **Settings → Secrets**,
legen Sie ein Model Profile an, das ihn benennt, und lassen Sie dann den Spec
eines Agents auf das Profile zeigen.

```bash
make platform-bootstrap BOOTSTRAP_API_KEY=sk-...
```

erledigt alle drei Schritte für ein neues Deployment.
