---
source_sha: 35041987d0af
---

# Der Berechtigungskatalog { #the-permission-catalog }

Alles, was einem Mitglied erlaubt werden kann, wie weit jede Berechtigung
reicht, und wie sich die eingebauten Rollen daraus zusammensetzen.

Siehe [Berechtigungen](../permissions.md) für die Erklärung und dafür, wie die
vier Schichten zusammenwirken; diese Seite ist die generierte Referenz und
bleibt deshalb englisch — sie wird zur Build-Zeit aus den Docstrings der Quelle
gelesen.

::: app.core.permissions

## Zugriff auf eine einzelne Zeile auflösen { #resolving-access-to-one-row }

Nicht generiert. `app/services/` ist ein implizites Namespace-Package - es hat
kein `__init__.py` - deshalb kann der statische Collector nicht hineinlaufen,
und eine Referenzseite, die stillschweigend die Hälfte ihrer Symbole weglässt,
wäre schlechter als eine, die sagt, wo man nachschauen muss.

Die Formel und jede Ablehnung, die sie ausspricht, sind in
[Berechtigungen](../permissions.md#how-the-layers-combine) dokumentiert. Die
Quelle ist
[`app/services/access.py`](https://github.com/vstorm-co/agenticos/blob/main/backend/app/services/access.py),
die die Begründung in ihren Docstrings trägt.
