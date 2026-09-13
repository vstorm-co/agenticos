---
source_sha: 883886c71472
---

# Korzystaj z ocen wiadomości { #use-message-ratings }

Ludzie mogą oceniać odpowiedzi agenta, a te oceny da się odczytać na dwa
sposoby: przy samej odpowiedzi oraz zbiorczo — dla tych, którzy administrują
deploymentem.

## Ocenianie wiadomości { #rating-messages }

### Lubię / nie lubię { #likedislike }

Każda wiadomość asystenta ma dwa przyciski:

- **Like (👍)** — kliknij, żeby zaznaczyć, że odpowiedź była pomocna
- **Dislike (👎)** — kliknij, żeby zaznaczyć, że odpowiedź miała problemy

### Zachowanie przełącznika { #toggle-behavior }

- Ponowne kliknięcie tego samego przycisku **usuwa** twoją ocenę
- Kliknięcie przeciwnego przycisku **zmienia** twoją ocenę (lubię → nie lubię i odwrotnie)
- Oceniać można tylko wiadomości asystenta (nie własne)

### Dodawanie komentarza { #adding-feedback }

Gdy ocenisz odpowiedź negatywnie, pojawia się okno z pytaniem **"What went wrong?"**

Opcjonalnie możesz zostawić komentarz (do 2000 znaków) opisujący problem. Taka
informacja zwrotna jest cenna, żeby zrozumieć, dlaczego odpowiedzi nie pomogły.

Typowe powody negatywnej oceny:

- Nieprawdziwe albo zmyślone informacje
- Odpowiedź nie odnosiła się do pytania
- Zbyt rozwlekła albo zbyt zdawkowa
- Słabe formatowanie lub struktura

## Liczniki ocen { #rating-counts }

Każda wiadomość pokazuje łączną liczbę ocen pozytywnych i negatywnych od
wszystkich użytkowników. Twoja własna ocena jest wyróżniona (zielona dla lubię,
czerwona dla nie lubię).

## Dla administratorów { #for-administrators }

### Dashboard ocen { #ratings-dashboard }

Przejdź do **Admin → Response Ratings** (albo `/admin/ratings`), żeby otworzyć dashboard analityczny.

#### Statystyki zbiorcze { #summary-statistics }

- **Total ratings** — wszystkie oceny w całym systemie
- **Likes** — liczba ocen pozytywnych
- **Dislikes** — liczba ocen negatywnych
- **Average** — ogólny wskaźnik zadowolenia (od -1,0 do 1,0)

#### Wykres ocen { #ratings-chart }

Wykres słupkowy pokazuje oceny z ostatnich 30 dni. Zielone słupki to oceny
pozytywne, czerwone — negatywne.

!!! note "Okno czasowe tej strony jest na stałe ustawione na 30 dni"

    Żeby odczytać te same liczby w wybranym przez siebie okresie, użyj karty
    **Answer quality, deployment-wide** na dashboardzie — ona podąża za filtrem
    okresu u góry strony.

### Filtrowanie ocen { #filtering-ratings }

Zawężaj wyniki listami rozwijanymi z filtrami:

| Filtr | Opcje |
|--------|---------|
| Rodzaj oceny | All / Likes Only / Dislikes Only |
| Komentarze | All / With comments only |

### Tabela ocen { #ratings-table }

Tabela pokazuje pojedyncze oceny wraz z:

- **Date** — kiedy ocena została wystawiona
- **Rating** — 👍 lubię albo 👎 nie lubię
- **Comment** — treść komentarza (jeśli został podany)
- **Message** — podgląd ocenionej odpowiedzi
- **User** — kto wystawił ocenę
- **Actions** — link do pełnej rozmowy

### Eksport danych { #exporting-data }

Wyeksportuj oceny do analizy poza produktem:

- **JSON** — pełne dane strukturalne, odpowiednie dla skryptów i narzędzi analitycznych
- **CSV** — format arkusza dla Excela albo Google Sheets

!!! tip "Eksport respektuje ustawione filtry"

    Zawęź do ocen negatywnych z komentarzem, a potem wyeksportuj — i dokładnie
    to dostaniesz. Filtry są częścią zapytania, a nie widoku.

### Podgląd rozmów { #viewing-conversations }

Kliknij **"View conversation"** przy dowolnej ocenie, żeby otworzyć czat z wczytaną rozmową.
Przydaje się to do zrozumienia kontekstu oceny.

## Strona rozmów dla administratora { #admin-conversations-page }

Przejdź do **Admin → All Conversations** (albo `/admin/conversations`), żeby zobaczyć rozmowy wszystkich użytkowników.

Ta strona daje:

- Przeszukiwalną listę wszystkich rozmów
- Filtr po adresie e-mail albo nazwie użytkownika
- Filtr po zakresie dat (predefiniowanym albo własnym)
- Szybkie linki do szczegółów rozmowy

## Bezpośrednie linki do rozmowy { #direct-conversation-links }

Możesz udostępnić bezpośredni link do konkretnej rozmowy, dodając parametr `id` do adresu czatu:

```
http://localhost:3000/chat?id=550e8400-e29b-41d4-a716-446655440000
```

Przydaje się to do:

- Dzielenia się kontekstem rozmowy z zespołem
- Zapisywania ważnych rozmów w zakładkach
- Linkowania z zewnętrznych narzędzi albo z dokumentacji

Kliknięcie **"View conversation"** przy dowolnej ocenie albo na administracyjnej liście rozmów otwiera właśnie taki link.

## Dostęp przez API { #api-access }

Do programistycznego dostępu do danych o ocenach służą administracyjne endpointy API:

| Endpoint | Metoda | Opis |
|----------|--------|-------------|
| `/admin/ratings` | GET | Lista ocen ze stronicowaniem i filtrami |
| `/admin/ratings/summary` | GET | Statystyki zbiorcze w zakresie `from`/`to` (daty UTC włącznie, domyślnie ostatnie 30 dni) |
| `/admin/ratings/export` | GET | Eksport ocen (JSON/CSV) |
| `/admin/conversations` | GET | Lista wszystkich rozmów |

!!! warning "Każdy endpoint `/admin` należy do superadmina deploymentu, a nie do roli w organizacji"

    Bramką jest `CurrentAppAdmin` — zalogowany użytkownik, którego
    `users.is_app_admin` jest prawdziwe. Nie ma kolumny `users.role` i żadna
    rola w organizacji nie sięga tych tras. Zobacz
    [uprawnienia](../permissions.md#layer-1-usersis_app_admin-the-deployment-superadmin).
