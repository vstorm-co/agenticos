---
source_sha: "2d253005d633"
title: "Luki w wiedzy"
description: "Luki w wiedzy pokazują pytania, dla których agent nie znalazł w bazie wiedzy nic trafnego, pogrupowane w tematy, żeby było widać, jakiego dokumentu brakuje."
---

# Luki w wiedzy { #knowledge-gaps }

Wiele złych odpowiedzi nie wynika z instrukcji agenta. Baza wiedzy po prostu
nie zawiera odpowiedzi i żadna zmiana promptu tego nie naprawi. **Luki w
wiedzy** pokazują takie pytania: te, dla których agent przeszukał swoją
[bazę wiedzy](file-processing.md) i nie znalazł nic trafnego. Są pogrupowane
w tematy, z liczbą zadań każdego pytania i agentami, którzy je zadali.

Luka mówi, czego brakuje. Sama nigdy niczego nie dodaje do kolekcji. Człowiek
pisze albo znajduje brakujący dokument i go dodaje. Wcześniej może zamienić
pytania z tematu na przypadki [datasetu](datasets.md), żeby eval pokazał, czy
nowy dokument zmienił odpowiedzi.

## Jak pytanie staje się luką { #how-a-question-becomes-a-gap }

Za każdym razem, gdy agent w trakcie runa przeszukuje bazę wiedzy, platforma
zapisuje to wyszukiwanie: zapytanie wysłane przez agenta, przeszukane kolekcje,
liczbę zwróconych fragmentów i to, jak bardzo najbliższy fragment był podobny
do zapytania. Wyszukiwanie jest **chybione**, gdy nic nie zwróciło albo gdy
najbliższy fragment jest mniej podobny do zapytania niż
`KNOWLEDGE_GAP_MIN_SIMILARITY`.

| Ustawienie | Domyślnie | O czym decyduje |
|---|---|---|
| `KNOWLEDGE_GAP_MIN_SIMILARITY` | `0.30` | Podobieństwo kosinusowe, poniżej którego najbliższy fragment liczy się jako „nic trafnego”. To, ile punktów dostaje dobre dopasowanie, zależy od modelu embeddingów, więc przed zmianą sprawdź kilka własnych wyszukiwań |

Podobieństwo to podobieństwo kosinusowe wektora fragmentu do wektora
zapytania. To nie jest wynik rankingu: przy wyszukiwaniu hybrydowym albo
rozszerzaniu zapytania wynik rankingu jest połączoną pozycją i nic nie mówi o
tym, jak blisko był fragment.

Zapisywane jest każde wyszukiwanie, nie tylko chybione. Gdy zmienisz próg,
dotyczy on także wyszukiwań już wykonanych: luki, które czytasz, to zawsze
wyszukiwania poniżej bieżącego ustawienia.

Zapisywane są tylko wyszukiwania, które agent wykonuje w trakcie runa.
Wyszukiwanie przez `/rag/search` w HTTP API ani podgląd na stronie kolekcji
nie są zapisywane.

## Tematy { #topics }

Chybione wyszukiwania są grupowane w **tematy** według znaczenia zapytania. Co
15 minut proces w tle bierze nowe chybione wyszukiwania każdej bazy wiedzy,
tworzy ich embeddingi modelem tej kolekcji i umieszcza każde w najbliższym
temacie tej bazy albo zakłada nowy. Jedno przejście tworzy embeddingi dla
najwyżej 500 chybionych wyszukiwań na bazę wiedzy; reszta czeka na następne.
Baza wiedzy bez nowych chybionych wyszukiwań nie kosztuje żadnego wywołania
embeddingów.

- Wyszukiwanie w dwóch kolekcjach staje się pytaniem w temacie każdej z nich.
- Kolekcja przeniesiona na inny model embeddingów zaczyna nowe tematy, bo
  wektorów z dwóch modeli nie da się porównać.
- Temat zachowuje tożsamość, gdy dochodzą do niego pytania, więc decyzja,
  którą o nim podjąłeś, nadal obowiązuje.

**Grupuj teraz** na karcie luk w wiedzy kolekcji od razu uruchamia przejście
dla tej bazy wiedzy, zamiast czekać na harmonogram. Dopóki pytanie nie trafi do
tematu, karta liczy je jako jeszcze niepogrupowane.

## Czytanie luk { #reading-gaps }

Luki są widoczne w trzech miejscach:

- na karcie **Luki w wiedzy** kolekcji: wszystkie tematy tej bazy wiedzy;
- na karcie **Luki w wiedzy** agenta: tylko pytania tego agenta, w bazach
  wiedzy, które możesz czytać;
- w widżecie **Luki w wiedzy** na pulpicie: najczęściej zadawane tematy w całej
  organizacji.

Temat pokazuje, ile razy go zadano, kiedy ostatnio, którzy agenci go zadali, i
do trzech jego pytań. Otwórz go, żeby zobaczyć najnowsze pytania: o co zapytała
osoba, czego szukał agent, jak blisko był najbliższy fragment i komentarz
każdego, kto ocenił odpowiedź łapką w dół.

## Co zrobić z luką { #acting-on-a-gap }

| Działanie | Co robi |
|---|---|
| Dodaj brakujący dokument | Wgraj go do kolekcji albo do źródła, z którego kolekcja się synchronizuje. Nic nie jest dodawane za ciebie |
| **Dodaj do datasetu** | Zamienia najnowsze pytania tematu (do 200) na przypadki wybranego datasetu, jako jedną nową wersję. Każdy przypadek to pytanie osoby, a odpowiedź agenta jest kontrprzykładem. Pytanie zadane przez HTTP API nie ma zapisanej odpowiedzi i jest pomijane |
| **Odrzuć** | Oznacza temat jako niewymagający treści. Odrzucony temat zatrzymuje należące do niego pytania, więc nie wraca jako nowy temat. **Otwórz ponownie** to odwraca |

Po dodaniu dokumentu uruchom eval na datasecie. Przypadki, które nie
przechodziły z powodu brakującej wiedzy, powinny teraz przejść.

## Dostęp { #access }

Temat składa się z pytań ludzi, więc czytanie luk wymaga `runs:view`, czyli
uprawnienia, które pozwala czytać w Activity każdy run w organizacji. Członek
bez niego nie widzi karty ani widżetu, a API mu odmawia.

| Żeby | Potrzebujesz |
|---|---|
| Czytać luki kolekcji | `runs:view` i `collections:view` na tej kolekcji |
| Czytać luki agenta | `runs:view` i `agents:view` na agencie; tematy kolekcji, których nie możesz czytać, są pomijane |
| Odrzucić, otworzyć ponownie albo pogrupować | `runs:view` i `collections:edit` na kolekcji |
| Dodać temat do datasetu | `runs:view` i `datasets:edit` na datasecie |

Kolekcja, agent, temat albo dataset, do którego nie masz dostępu, odpowiada „nie
znaleziono”; tak samo ten z innej organizacji. Zobacz
[Uprawnienia](permissions.md).

## Dane osobowe { #personal-data }

Zapisane wyszukiwanie to treść użytkownika: agent sformułował je z tego, o co
ktoś zapytał. Jest usuwane razem z runem, w którym powstało, i z rozmową, z
której pochodzi. Usunięcie osoby usuwa wyszukiwania wykonane podczas
odpowiadania jej, także w runach bez rozmowy. Jej eksport je zawiera.

Temat nie kopiuje tekstu. Jego nazwa, przykłady i liczba są czytane z
wyszukiwań, które jeszcze zawiera, więc gdy te wyszukiwania zostaną usunięte,
tematowi nic nie zostaje i następne przejście grupowania go usuwa. Zobacz
[Ochrona danych](data-protection.md#where-personal-data-lives).

## Czego luki jeszcze nie wykrywają { #limits }

Luki pochodzą tylko z wyszukiwania. Odpowiedź, w której agent powiedział, że nie
wie, albo odpowiedź ocenioną łapką w dół z komentarzem o brakującej informacji,
nie jest wykrywana sama z siebie. Wykrywanie takich odpowiedzi wymaga modelu i
jest śledzone w [#2135](https://github.com/vstorm-co/agenticos/issues/2135). Gdy
odpowiedź oceniona łapką w dół należy do runa, w którym wyszukiwanie było
chybione, jej komentarz jest pokazywany przy pytaniu.
