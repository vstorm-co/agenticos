---
source_sha: cff22ae9f823
---

# Eine Seite übersetzen { #translate-a-page }

Diese Site erscheint auf Englisch, Polnisch, Deutsch und Spanisch aus einem
einzigen `docs/`-Baum. Englisch ist die Ausgangssprache: eine Seite wird zuerst
auf Englisch geschrieben, und die anderen drei sind Übersetzungen davon, die
zurückfallen können und das dann auch sagen sollen.

## Wo eine Übersetzung liegt { #where-a-translation-lives }

Eine Übersetzung liegt neben der Seite, die sie übersetzt, mit der Locale im
Dateinamen.

```text
docs/install.md      the English source
docs/install.pl.md   Polish
docs/install.de.md   German
docs/install.es.md   Spanish
```

[mkdocs-static-i18n](https://github.com/ultrabug/mkdocs-static-i18n) baut aus
diesem Baum eine Site pro Locale. Englisch behält die URLs, die es schon immer
veröffentlicht hat - `/install/` ist weiterhin `/install/` - und jede Übersetzung
kommt daneben unter `/pl/install/`, `/de/install/` und `/es/install/` hinzu. Der
Sprachumschalter in der Kopfzeile wechselt zwischen ihnen, ohne dass der Leser
die Stelle verliert.

Sonst ändert sich nichts. Es gibt keine eigene Navigationsdatei, kein zweites
`docs_dir` und keine Kopie von `mkdocs.yml` pro Locale: die Navigation in
`mkdocs.yml` wird geteilt, und ihre Abschnittsüberschriften werden von der
Tabelle `nav_translations` unter der jeweiligen Locale dort übersetzt. Der eigene
Titel einer Seite in der Seitenleiste kommt aus der ersten Überschrift der
übersetzten Datei, also übersetzt das Übersetzen der Überschrift auch den
Navigationseintrag.

## Jede Übersetzung verzeichnet, woraus sie gemacht wurde { #every-translation-records-what-it-was-made-from }

Das Erste in einer übersetzten Datei ist ihr Front Matter, und der Fingerabdruck
darin ist der Sinn der ganzen Anordnung:

```markdown
---
source_sha: 4f2b9c1ad07e
---

# Instalacja
```

Das sind die ersten zwölf Hexzeichen des SHA-256 von `install.md`, so wie es zum
Zeitpunkt der Übersetzung der Seite stand. `scripts/docs_i18n.py` berechnet ihn,
und zwei Dinge lesen ihn zurück.

`python3 scripts/check_docs_i18n.py` läuft in `make lint` und lässt den Build
scheitern an einer Seite ohne Übersetzung, an einer Übersetzung, deren
Fingerabdruck nicht mehr zu ihrer englischen Quelle passt, und an einer
Übersetzung, deren englische Seite umbenannt oder gelöscht wurde.

Der Site-Build liest denselben Fingerabdruck und setzt oben auf jede Seite, die
entweder unübersetzt oder zurückgefallen ist, eine Warnung in der Sprache des
Lesers. Ohne sie sieht eine Locale fertig aus, wenn sie es nicht ist: eine Seite,
die niemand übersetzt hat, antwortet trotzdem unter `/de/...`, auf Englisch,
innerhalb einer deutschen Navigation, und nichts unterscheidet sie von einer
Seite, die tatsächlich jemand übersetzt hat.

!!! warning "`--update` ist der letzte Schritt des Übersetzens, kein Weg, still zu werden"

    `python3 scripts/check_docs_i18n.py --update` stempelt den aktuellen
    englischen Fingerabdruck auf jede vorhandene Übersetzung. Führen Sie es aus,
    nachdem Sie eine Seite neu übersetzt haben. Führen Sie es über eine Seite aus,
    die niemand neu übersetzt hat, und Sie haben eine veraltete Übersetzung
    sowohl vor dem Tor als auch vor dem Leser versteckt, und genau das ist das
    eine Versagen, das dieses Design verhindern soll.

## Jede Überschrift pinnt ihren englischen Anker { #every-heading-pins-its-english-anchor }

Eine übersetzte Überschrift trägt den Anker der englischen Seite ausdrücklich, in
der `attr_list`-Form:

```markdown
## Berechtigungen { #permissions }
### Wer welche Rolle vergeben darf { #who-may-hand-out-which-role }
```

Ohne das bekommt eine ins Deutsche übersetzte Überschrift einen deutschen Anker,
und jeder Link, der als `../permissions.md#who-may-hand-out-which-role`
geschrieben ist, landet am Anfang der deutschen Seite statt beim Abschnitt. Es
gibt über hundert seitenübergreifende Links auf dieser Site, und viele tragen ein
Fragment, das ist also kein Randfall - und `mkdocs build --strict` validiert den
Pfad eines Links, aber **nicht** sein Fragment, sodass es sonst niemandem
auffällt.

Das Pinnen bedeutet außerdem, dass ein Link in allen vier Sprachen funktioniert,
ohne pro Locale umgeschrieben zu werden, und dass ein Permalink, den jemand
geteilt hat, beim Sprachwechsel weiter funktioniert.

`scripts/check_docs_i18n.py` vergleicht die beiden Ankerlisten in
Dokumentreihenfolge, sodass eine Überschrift, die fehlt, hinzugekommen ist,
umgestellt wurde oder ungepinnt blieb, `make lint` scheitern lässt und sagt,
welche es ist. Um die Liste zu lesen, müssen Sie vor dem Anfangen pinnen:

```bash
python3 scripts/check_docs_i18n.py --anchors docs/permissions.md
```

Leiten Sie den Anker nicht mit dem Auge her. Die Überschrift
`Layer 1: users.is_app_admin - the deployment superadmin` antwortet auf
`layer-1-usersis_app_admin-the-deployment-superadmin`: der Punkt fällt weg,
statt zu einem Trennzeichen zu werden, und die Unterstriche bleiben erhalten.

!!! note "Zwei Überschriftenanker sind nicht Ihre zu pinnen"

    Einer wiederholten Überschrift hängt die `toc`-Erweiterung `_1` an -
    `screens.md` hat zwei mit dem Titel "MCP servers", von denen die zweite auf
    `mcp-servers_1` antwortet. Pinnen Sie auf beiden denselben Text, und das
    Suffix wird auf die Übersetzung genauso angewendet. Die generierten
    Symbolüberschriften auf den Seiten unter `docs/reference/` kommen aus den
    Docstrings und haben im Markdown keine Überschrift, die sich pinnen ließe.

## Was übersetzt wird, und was unangetastet bleibt { #what-to-translate-and-what-to-leave-alone }

Übersetzen Sie die Prosa, die Überschriften, die Tabellenköpfe und Zellentexte,
die Prosa sind, die Titel von Admonitions, den Alternativtext von Bildern und den
Linktext.

Lassen Sie das Folgende genau so, wie es auf Englisch steht:

| Nie übersetzt | Warum |
|---|---|
| Codeblöcke und alles darin | Ein Leser tippt sie wortwörtlich ab |
| Befehlsnamen, Flags, Umgebungsvariablen | `make check`, `--strict`, `DATABASE_URL` |
| API-Pfade, HTTP-Methoden, Statuscodes | `POST /api/v1/agents` |
| Feld- und Konfigurationsschlüssel | `spec_version`, `budget.monthly_cap` |
| Berechtigungsnamen | `agents:edit` ist eine Zeichenkette, die das Produkt vergleicht |
| Datei- und Verzeichnispfade | `backend/app/core/vault.py` |
| Namen von Fehler- und Ausnahmeklassen | `AuthorizationError` |
| Produktnamen | Docker Compose, PostgreSQL, Slack, Prefect |
| Mermaid-Blöcke | Ein Label mit einer Klammer oder einem Anführungszeichen bricht den Graphen, und der Build kann es Ihnen nicht sagen - Mermaid rendert im Browser |
| Eine Beschriftung der Konsole, die der Leser auf dem Bildschirm finden muss | Die Oberfläche ist englisch, `Admin → Response Ratings` ist also ein Orientierungspunkt und keine Formulierung |
| Bildpfade | Ein Screenshot bedient alle vier Locales |

Ein Kommentar innerhalb eines Codeblocks ist Prosa, die ein Leser liest statt
tippt, er darf also übersetzt werden - aber nur dort, wo der Block eine
Veranschaulichung ist. Übersetzen Sie nie einen Kommentar in einem Block, den
jemand einfügen soll, denn das Einfügen nimmt ihn mit.

## Die eigenen Substantive des Produkts bleiben englisch { #the-products-own-nouns-stay-english }

Die Konsole macht das bereits, und aus demselben Grund: diese Wörter benennen
Dinge, denen ein Leser auch in der API begegnet, in dem YAML, das ein Spec in
sein eigenes Repository exportiert, und auf jeder englischen Seite dieser Site.
Sie hier und sonst nirgends zu übersetzen gibt einem Produkt zwei Vokabulare, und
ein polnischer Leser, der das übersetzte Wort nachschlägt, findet nichts.

**agent · spec · capability · skill · embed · budget · run · prompt · provider ·
token · vault · workspace · sandbox · MCP**

Flektieren Sie sie, statt sie zu ersetzen, und übersetzen Sie alles darum herum.

| Englisch | Polnisch | Deutsch | Spanisch |
|---|---|---|---|
| the agent's spec | spec agenta | der Spec des Agents | el spec del agent |
| publish a version | opublikuj wersję | eine Version veröffentlichen | publica una versión |
| grant a capability | przyznaj capability | eine Capability gewähren | concede una capability |
| the run failed | run zakończył się błędem | der Run ist fehlgeschlagen | el run ha fallado |
| a vault secret | sekret w vault | ein Secret im Vault | un secreto del vault |

Alles andere ist gewöhnlicher Wortschatz und soll natürlich klingen: knowledge
base, organization, member, role, permission, approval, budget cap, notification,
channel, deployment.

### Ein beibehaltenes Substantiv braucht ein Genus, und es bekommt es hier { #a-kept-noun-needs-a-gender-and-it-gets-one-here }

Ein englisches Substantiv, das in einem deutschen, polnischen oder spanischen
Satz steht, muss einen Artikel und eine Endung annehmen, und jede Seite für sich
wählt eine andere. Der erste deutsche Durchgang lieferte auf einer Seite "der
Sandbox" und auf einer anderen "ein Sandbox"; die Leserin begegnet beidem. Die
Entscheidung fällt deshalb einmal, und zwar hier:

| Noun | German | Polish | Spanish |
|---|---|---|---|
| agent | der Agent | ten agent, agenta | el agent |
| spec | der Spec | ten spec, speca | el spec |
| capability | die Capability | ta capability (nieodmienne) | la capability |
| skill | der Skill | ten skill, skilla | el skill |
| embed | das Embed | ten embed, embeda | el embed |
| budget | das Budget | ten budżet | el budget |
| run | der Run | ten run, runa | el run |
| prompt | der Prompt | ten prompt, promptu | el prompt |
| provider | der Provider | ten provider, providera | el provider |
| token | das Token | ten token, tokena | el token |
| vault | der Vault | ten vault, vaulcie | el vault |
| workspace | der Workspace | ten workspace, workspace'u | el workspace |
| sandbox | die Sandbox | ten sandbox, sandboksie | la sandbox |
| MCP server | der MCP-Server | ten serwer MCP | el servidor MCP |

Im Deutschen wird mit Bindestrich zusammengesetzt, sobald die zweite Hälfte
deutsch ist - Run-Kosten, Vault-Eintrag, Sandbox-Session - und das englische Wort
behält seine eigene Großschreibung.

## Terminologie, die exakt sein muss { #terminology-that-has-to-be-exact }

Seiten zu Berechtigungen, Governance und Sicherheit beschreiben Ablehnungen, und
eine lose beschriebene Ablehnung ist schlimmer als eine gar nicht beschriebene.
Halten Sie diese Unterscheidungen in jeder Sprache ein:

| Englisch | Die Unterscheidung, die erhalten bleiben muss |
|---|---|
| permission / grant | Eine Permission kommt aus einer Rolle; ein Grant hängt an einer Ressource und erweitert sie |
| role / membership | Autorität liegt auf einer Mitgliedschaftszeile, nicht auf einem Nutzer |
| owner / admin / editor / viewer | Rollennamen, gegen den Katalog abgeglichen - behalten Sie den englischen Namen bei der ersten Nennung in Klammern |
| budget cap / spend | Die Grenze, und was dagegen ausgegeben wurde |
| approval / refusal | Eine Entscheidung, die aussteht, und eine, die endgültig ist |
| organization / deployment | Ein Mandant, und die gesamte installierte Instanz |
| published / draft | Eine Spec-Version, die Agents ausführen, und eine, die noch nichts ausführt |

Wenn ein Satz aussagt, was die Plattform ablehnt, übersetzen Sie die Ablehnung
wörtlich. Weichen Sie "is refused" nicht zu "funktioniert möglicherweise nicht"
auf, und machen Sie aus einer Aussage darüber, was nicht passieren kann, keinen
Rat darüber, was Sie nicht tun sollten.

## Zwei Dinge, die eine Locale nicht bekommt { #two-things-a-locale-does-not-get }

Die Referenzseiten unter `docs/reference/` werden von mkdocstrings aus
Python-Docstrings erzeugt. Eine dieser Dateien zu übersetzen übersetzt ihre Prosa
und ihre Überschriften; die erzeugte Symboldokumentation bleibt englisch, weil sie
beim Build aus dem Quelltext gelesen wird. Das ist so gewollt - sagen Sie es auf
der Seite, statt die Docstrings in eine zweite Kopie zu paraphrasieren, die
abdriftet.

`release-notes.md` zeigt `CHANGELOG.md`, beim Build eingesetzt. Eine übersetzte
Release-Notes-Seite übersetzt den eigenen Rahmen der Seite um die Markierung
herum; die Changelog-Einträge selbst bleiben englisch, weil sie die
Commit-Historie sind.

## Suche auf Polnisch { #searching-in-polish }

lunr.js, das die Suche der Site antreibt, hat keinen polnischen Stemmer, also
trifft die Suche unter `/pl/` ganze Wörter statt Wortstämme. Deutsch und Spanisch
werden normal gestemmt. Es gibt nichts zu konfigurieren - der Build sagt es in
seinem Log -, aber es ist gut zu wissen, bevor es jemand als Fehler meldet.

## Der Arbeitsablauf { #the-workflow }

1. Kopieren Sie die englische Seite nach `<page>.<locale>.md`.
2. Übersetzen Sie sie, halten Sie die Überschriftenstruktur identisch und pinnen
   Sie den englischen Anker jeder Überschrift.
3. Prüfen Sie, ob jeder relative Link noch auflöst. Ein Link auf `../mcp.md` von
   einer übersetzten Seite löst automatisch auf das übersetzte `mcp.md` auf; ein
   Link, der als `../mcp.pl.md` geschrieben ist, ist falsch und lässt den Build
   scheitern.
4. `python3 scripts/check_docs_i18n.py --update`.
5. `make docs-build` - es läuft mit `--strict`, ein toter Link lässt es also
   scheitern.
6. `python3 scripts/check_docs_paragraphs.py` - die Grenze von 115 Wörtern pro
   Absatz gilt in jeder Sprache, und eine Übersetzung, die zwei englische Absätze
   zu einem verschmilzt, stolpert meist darüber.

Eine englische Seite zu ändern ist dieselbe Schleife vom anderen Ende her: ändern
Sie sie und übersetzen Sie dann entweder die drei Übersetzungen in derselben
Änderung neu, oder lassen Sie sie und lassen Sie das Tor sie melden - was Sie
nicht tun dürfen, ist `--update` darüber zu stempeln.

## Zusammenfassung { #recap }

- Eine Übersetzung ist `<page>.<locale>.md` neben der englischen Seite; die
  englischen URLs bewegen sich nicht.
- Ihr Front Matter verzeichnet den Fingerabdruck des englischen Textes, aus dem
  sie gemacht wurde, und jede Überschrift pinnt ihren englischen Anker.
- `scripts/check_docs_i18n.py` lässt `make lint` an einer fehlenden, veralteten
  oder verwaisten Übersetzung und an nicht zusammenpassenden Überschriften
  scheitern, und die Site markiert eine unübersetzte oder veraltete Seite für den
  Leser.
- Code, Befehle, Schlüssel, Pfade und die eigenen Substantive des Produkts
  bleiben englisch; alles darum herum wird übersetzt.
- Formulierungen zu Berechtigungen und Governance sind exakt, nicht ungefähr.
