---
source_sha: "7cb876b5ef26"
---

<!-- source_sha: 7cb876b5ef26 -->

# Zu AgenticOS beitragen

[English](CONTRIBUTING.md) · [Polski](CONTRIBUTING.pl.md) · **Deutsch** · [Español](CONTRIBUTING.es.md)

Danke fürs Vorbeischauen. Dieses Dokument hält sich nicht mit Zeremonie auf und
wird konkret bei den Dingen, an denen Pull Requests tatsächlich scheitern.

## Der Maßstab

Code landet, wenn ein Maintainer ihn ohne Änderungen mergen würde. Konkret:

- **Vollständig typisiert.** Kein `Any`, kein `# type: ignore`, kein `except:`,
  das einen Fehler verschwinden lässt. Modellieren Sie mit präzisen Typen statt
  mit losen Dicts.
- **Fehler sind laut.** Scheitern Sie mit einer klaren Meldung; verschlucken Sie
  nie eine Exception und übertünchen Sie nie einen Bug mit einem Fallback. Eine
  stille falsche Antwort ist schlimmer als ein Absturz.
- **Kein totes Gewicht.** Keine spekulativen Abstraktionen, keine ungenutzten
  Parameter, kein auskommentierter Code, keine „nur für alle Fälle“-Zweige.
- **Kommentare erklären das *Warum*.** Was der Code tut, ist sichtbar; warum er
  es so tut, ist es nicht — und genau das braucht ein Leser in sechs Monaten.
- **Passen Sie sich dem umgebenden Code an.** Seine Idiome schlagen die
  persönliche Vorliebe.

## Einrichtung

```bash
make dev            # postgres, redis, api, worker, frontend
make seed           # an organization, an owner, a default model profile
```

Das Backend braucht einen `VAULT_MASTER_KEY`. Ohne einen fällt es auf
`SECRET_KEY` zurück, was lokal in Ordnung ist und in der Produktion abgelehnt
wird.

## Die Tests ausführen

Das vollständige Bild steht in [`CLAUDE.md`](CLAUDE.md#testing). Die kurze
Fassung:

```bash
make test               # backend, with the coverage gate
make test-frontend      # vitest unit + integration, no coverage
make test-frontend-cov  # the same, plus the gate CI applies
make test-e2e           # playwright
make check              # every CI job except e2e — run this before a pull request
```

**`make test-frontend` misst keine Coverage, und das einzige Gate des Frontends
ist eine Coverage-Schwelle.** Es ist die Schleife; `make check` ist die Antwort.

**Die Plattformschicht wird auf 100 % Coverage gehalten**, und die CI setzt das
durch. Das heißt `app/agents/`, den Permission-Katalog, den Vault und die darauf
aufbauenden Services. Aus dem Template übernommene Subsysteme (die
RAG-Pipeline, die Connectors, die Channel-Adapter) werden berichtet, sind aber
kein Gate für den Build — Code, den wir nicht entworfen haben, am selben Maßstab
zu messen, hieße mock-lastige Tests, die eine Zahl kaufen statt Vertrauen.

Wenn Sie eine Datei zur Plattformschicht hinzufügen, braucht sie Tests, die
fehlschlagen würden, wenn sich das Verhalten änderte. Ein Test, der nur den
glücklichen Pfad durchläuft, zählt nicht.

## Die Architektur, in einem Absatz

Ein Agent ist **Daten**, kein Code. Der `AgentSpec` ist der Vertrag: der Builder
bearbeitet ihn, die Datenbank versioniert ihn, `app/agents/factory.py`
instanziiert ihn, und ein Kunde kann ihn als YAML in sein eigenes
Git-Repository committen. Alles, woraus ein Agent zusammengesetzt wird, ist eine
**Capability** — Wissenssuche, Webrecherche, ein Budget-Guard, eine Menge von
Skills —, im Code mit Metadaten deklariert und per Konfiguration komponiert. Die
Konfiguration kann immer nur das erreichen, was der Code registriert hat.

Daraus folgen zwei Regeln, und die meisten Review-Kommentare kommen auf sie
zurück:

**Ids sind dauerhaft.** Eine Capability-Id steht in gespeicherten Specs und in
den Repositories der Kunden. Benennen Sie die Python-Klasse beliebig um; die Id
zu ändern ist ein Breaking Change.

**Validieren Sie beim Publish, nicht zur Laufzeit.** Ein kaputter Agent soll
abgelehnt werden, während jemand auf ein Formular schaut, und nicht um 3 Uhr
nachts in einem Kundengespräch.

## Eine Capability hinzufügen

Ein Ordner unter `app/agents/capabilities/`, in derselben Form wie die anderen:

```
app/agents/capabilities/your_thing/
    __init__.py        # registration + public exports
    _capability.py     # the AbstractCapability subclass
    _toolset.py        # its tools, if it has any
    README.md          # the decisions behind it, not a description of the code
```

Registrieren Sie sie in `load_builtins()` in `_registry.py`, sonst existiert sie
für den Builder nicht — diese Kopplung ist Absicht.

Wenn die Capability auf die Außenwelt wirken kann, markieren Sie sie mit
`side_effecting=True`. Damit wird die menschliche Freigabe zum Standard, und das
Flag zu vergessen ist der Weg, auf dem ein Agent am Ende unbeaufsichtigt E-Mails
verschickt.

## Pull Requests

- Ein Anliegen pro PR. Ein Refactoring und ein Feature in einem Diff werden als
  keines von beidem reviewt.
- Bugs kommen mit einem Regressionstest, der ohne den Fix fehlschlägt.
- Schreiben Sie in die Beschreibung, was Sie entschieden haben und warum. Das
  Was zeigt der Code.

## Sicherheit

Öffnen Sie für eine Schwachstelle kein öffentliches Issue. Siehe
[`SECURITY.md`](SECURITY.md).

## Lizenz

Mit Ihrem Beitrag erklären Sie sich damit einverstanden, dass Ihre Arbeit unter
der Apache License 2.0 lizenziert ist, denselben Bedingungen wie der Rest dieses
Repositories. Es gibt kein CLA.
