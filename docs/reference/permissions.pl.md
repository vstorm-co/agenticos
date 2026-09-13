---
source_sha: 35041987d0af
---

# Katalog uprawnień { #the-permission-catalog }

Wszystko, na co można pozwolić członkowi organizacji, jak daleko sięga każde
uprawnienie i jak składają się z nich wbudowane role.

Wyjaśnienie oraz to, jak łączą się cztery warstwy, znajdziesz w
[Uprawnieniach](../permissions.md); ta strona jest wygenerowaną referencją i
dlatego pozostaje po angielsku — czyta się ją w czasie budowania z docstringów
w źródle.

::: app.core.permissions

## Rozstrzyganie dostępu do jednego wiersza { #resolving-access-to-one-row }

Nie jest generowane. `app/services/` to niejawny pakiet przestrzeni nazw - nie
ma `__init__.py` - więc statyczny kolektor nie potrafi w niego wejść, a strona
referencyjna, która po cichu pomija połowę swoich symboli, byłaby gorsza niż
taka, która mówi, gdzie szukać.

Wzór i każde odrzucenie, jakie z niego wynika, są udokumentowane w
[Uprawnieniach](../permissions.md#how-the-layers-combine). Źródłem jest
[`app/services/access.py`](https://github.com/vstorm-co/agenticos/blob/main/backend/app/services/access.py),
który niesie uzasadnienie w swoich docstringach.
