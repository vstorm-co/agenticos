---
source_sha: 34c34d991836
---

# Einen Server zum MCP-Katalog hinzufügen { #add-a-server-to-the-mcp-catalog }

Der [Katalog](../mcp.md#the-catalog) ist das, was die Auswahl für Verbindungen
nützlich macht statt zu einem leeren URL-Feld. Einen Eintrag hinzuzufügen ist
Daten, kein Code: ein Objekt in
`backend/app/core/catalog/mcp_servers.json`.

!!! tip "Sie brauchen das nicht, um einen Server zu nutzen"

    Jeder MCP-Server, der per URL erreichbar ist, verbindet sich über den Eintrag
    *Custom server*, und seine Tools werden beim Verbinden introspiziert. Der
    Katalog erspart jemandem das Nachschlagen einer URL und einen Absatz voller
    Vermutungen über die Einrichtung; er ist kein Tor.

## Der Eintrag { #the-entry }

```json
{
  "key": "acme",
  "name": "Acme",
  "description": "Read and update work orders.",
  "category": "operations",
  "auth": "token",
  "url": "https://mcp.acme.com/mcp",
  "docs_url": "https://docs.acme.com/mcp",
  "token_hint": "A read-only service token from Settings → API, scoped to work orders.",
  "icon": "acme"
}
```

| Feld | |
|---|---|
| `key` | Stabile Id. Verbindungen halten sie fest, behandeln Sie sie also wie die Ids von Capabilities: umbenennen jederzeit, den Key nie ändern |
| `name` | Was die Auswahl zeigt |
| `description` | Ein Satz im Imperativ darüber, was die *Tools* tun |
| `category` | Gruppiert die Auswahl. Nutzen Sie eine bestehende wieder, es sei denn, der Server hat wirklich keine Heimat |
| `auth` | `none`, `token` oder `oauth` |
| `url` | Leer, wenn der Kunde den Server selbst hostet oder der Anbieter einen Endpunkt pro Konto ausgibt — das Formular fragt dann danach |
| `docs_url` | Wo der Anbieter seinen Server dokumentiert |
| `token_hint` | Nur für `token`. Siehe unten |
| `icon` | Ein `BrandIcon`-Name, oder leer |

!!! note "Beim Import geprüft"

    Die Datei wird beim Laden des Moduls gegen `CatalogEntry` geprüft, ein
    fehlerhafter Eintrag verweigert also den Start der Anwendung, statt still aus
    der Auswahl zu verschwinden.

## Den Token-Hinweis schreiben { #write-the-token-hint }

!!! important "Das ist das Feld, das den Eintrag verdient"

    Allgemeine Anweisungen sind der Hauptgrund, warum die Einrichtung eines
    Tokens scheitert, und "ein API-Token" sagt niemandem, wo zu klicken ist.

Sagen Sie, woher das Token kommt und was es können muss:

> A fine-grained personal access token with read access to the repositories the
> agent should see.

Lassen Sie es bei `oauth` und `none` leer — es gibt nichts einzufügen.

## Icons { #icons }

`icon` nennt ein Markenzeichen. Ist es in keinem einkompilierten Icon-Set
enthalten, legen Sie ein SVG unter `backend/app/core/catalog/icons/<name>.svg` ab; es wird von
`GET /catalog/icons` ausgeliefert und für jeden Katalogeintrag und jeden Provider
gezeichnet, dessen Id passt.

Die eigenen Farben der Datei werden **ignoriert** — sie wird als Silhouette in
`currentColor` gerendert, sodass das monochrome Register der Konsole von
Konstruktion wegen hält. Den Vertrag dazu finden Sie in `icons/README.md`.

Ein leeres `icon` fällt auf ein Monogramm zurück. Das ist ein gewolltes Aussehen
und kein fehlendes: jedes Icon-Set ist endlich, und dieser Katalog ist es nicht.

## Bevor Sie ihn committen { #before-you-commit-it }

!!! warning "Ein Eintrag ist ein Versprechen"

    Dass jemand sich den Server angesehen hat, dass der Auth-Ablauf funktioniert,
    dass die Beschreibung ehrlich ist. Das ist der ganze Grund, warum dies eine
    von Hand gepflegte Liste ist und kein Spiegel der öffentlichen Registry —
    machen Sie das Versprechen also wahr:

1. Verbinden Sie ihn in einem laufenden Deployment.
2. Führen Sie `POST /api/v1/mcp-connections/{id}/test` aus (die Schaltfläche
   **Test**) und lesen Sie die Tool-Liste, mit der er zurückkommt. Passen die
   Tools nicht zu Ihrer `description`, korrigieren Sie die Beschreibung.
3. Spielen Sie bei `oauth` den Ablauf von Anfang bis Ende durch. Discovery,
   dynamische Registrierung und der Token-Tausch scheitern jeweils anders, und
   ein Server, der bei Schritt zwei stehen bleibt, sieht in der UI genauso aus
   wie einer, der nur langsam ist.
4. Prüfen Sie, dass der Name nicht mit dem
   [Tool-Präfix](../mcp.md#name-collisions) eines bestehenden Eintrags
   kollidiert.

## Was nicht geändert werden muss { #what-does-not-need-changing }

Sonst nichts. Die Auswahl rendert aus dem Katalog, und der Verbindungsdienst,
der Probe, die Allowlist und das Präfixieren sind alle generisch. Ein Eintrag,
der hier hinzugefügt wird, ist beim nächsten Neustart im Produkt.
