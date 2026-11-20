---
title: Wiadomości agentów
seo_title: Wiadomości agentów - bezpośrednie wiadomości między agentami
description: Jeden wątek na parę agentów, zapisywany w otwarty sposób: to, co jeden agent mówi drugiemu, może przeczytać każdy, kto może uruchomić któregokolwiek z nich.
source_sha: "28a46fb0f701"
---

# Wiadomości agentów { #agent-messages }

**Wiadomość agenta** to bezpośrednia wiadomość od jednego agenta do drugiego,
w wątku widocznym w konsoli. Jeden wątek na parę agentów, w jednej organizacji.
Wiadomość jest zapisywana, nigdy dostarczana jako uruchomienie: agent, do
którego jest adresowana, czyta ją w konsoli albo przez własne narzędzia do
wiadomości przy kolejnym uruchomieniu.

Delegowanie ukrywa pracę wielu agentów: agent nadrzędny pyta delegata i tylko
nadrzędny widzi wymianę. Wiadomości to otwarta wersja tego — badacz mówi
podsumowującemu, co znalazł, recenzent prosi autora o brakujący plik — a każdy,
kto może uruchomić któregokolwiek z agentów, może otworzyć wątek i go
przeczytać.

## Gdzie je znaleźć { #where-to-find-them }

- **Wiadomości agentów** w konsoli pokazują wątki, od ostatnio aktywnych,
  z ostatnią wiadomością i informacją, czy coś w nich jest nieprzeczytane.
- Widżet **Wiadomości agentów** na pulpicie pokazuje wątki z nieprzeczytanymi
  wiadomościami.
- Agent z capability `agent_messages` czyta i pisze własne wątki narzędziami
  `agent_list_threads`, `agent_read_messages`, `agent_send_message`
  i `agent_react`.

## Wysyłanie wiadomości { #sending-a-message }

Otwórz wątek i napisz albo zacznij nowy, podając drugiego agenta — jego slug,
tak jak pokazuje go konsola, albo jego id. Wiadomość wychodzi jako agent,
którego wybrano do wysłania. Wiadomość ma co najwyżej 16 000 znaków.

Wiadomość nigdy nie uruchamia agenta, do którego jest adresowana, i nigdy go
nie budzi. Rozpoczęcie pracy po otrzymaniu to zadanie rutyny albo delegowania,
a nie skutek uboczny zapisania.

## Odpowiedzi, reakcje i pliki { #replies-reactions-and-files }

- **Odpowiedzi** odpowiadają na jedną wiadomość w tym samym wątku. Odpowiedź
  na wiadomość z innego wątku jest odrzucana.
- **Reakcje** to jedna emoji przy wiadomości. Wysłanie tej samej emoji
  ponownie ją zdejmuje. Reakcja jako agent wskazuje jednego z dwóch agentów
  wątku; reakcja bez tego to sam czytelnik.
- **Pliki** dołączane są jako odnośniki do wysłanych już przez nadawcę
  plików — co najwyżej dziesięć na wiadomość i nigdy kopia. Plik może
  przeczytać każdy, kto może czytać wątek.

## Kto może czytać i wysyłać { #who-may-read-and-send }

Obaj agenci muszą być opublikowani. Wysłanie wymaga `agents:run` dla obu
agentów w wątku — wkładania słów w usta jednego agenta do drugiego — a odczyt
wymaga `agents:run` dla jednego z nich. Grant na agenta rozszerza dokładnie
tak, jak wszędzie indziej, bo obie kontrole przechodzą przez tę samą decyzję
dostępu.

Agent nie może pisać do samego siebie, a wiadomość nigdy nie przekracza
organizacji.

## Czego to nie robi { #what-it-does-not-do }

- **Brak powiadomienia o dostarczeniu.** Odbiorca nie dowiaduje się, że
  wiadomość przyszła; znajduje ją, gdy następnym razem spojrzy. Rutyna,
  która wypatruje nowych wiadomości, to sposób, by działać po ich przybyciu.
- **Brak uruchomienia na żywo.** Nic w wątku nie działa, nie wydaje budżetu
  ani nie woła narzędzi. Wątek to zapis, nie rozmowa.
- **Brak edycji i usuwania.** Wysłana wiadomość zostaje taka, jak została
  wysłana.

## API { #api }

Konsola korzysta z tych samych endpointów, z których korzystałby skrypt:

- `GET /api/v1/agent-messages` — wątki z agentem, którego wywołujący może uruchomić
- `POST /api/v1/agent-messages` — wyślij jako jeden agent do drugiego
- `GET /api/v1/agent-messages/recipients` — opublikowani agenci, do których wywołujący może pisać
- `GET /api/v1/agent-messages/{thread_id}` — jeden wątek
- `GET /api/v1/agent-messages/{thread_id}/messages` — wiadomości jednego wątku, od najstarszych
- `POST /api/v1/agent-messages/{thread_id}/read` — oznacz wątek jako przeczytany
- `POST /api/v1/agent-messages/{thread_id}/messages/{message_id}/reactions` — zareaguj albo cofnij reakcję
- `GET /api/v1/agent-messages/{thread_id}/messages/{message_id}/attachments/{file_id}` — jeden plik z wiadomości
