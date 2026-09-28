---
source_sha: "50cf8da35126"
title: "Automatycznie segreguj nowe issues na GitHubie"
description: "Uruchamiaj agenta w chwili otwarcia issue, niech sam na podstawie dostawy proponuje priorytet i etykiety, a trigger przetestuj, podpisując dostawę samodzielnie."
---

# Automatycznie segreguj nowe issues na GitHubie { #triage-new-github-issues-automatically }

Podłącz [trigger zdarzeń](../triggers.md) do webhooka `issues` repozytorium, żeby nowe issue trafiało do agenta w chwili otwarcia, i niech agent na podstawie tekstu dostawy proponuje priorytet, etykiety i sprawdzenie duplikatu. Ta strona testuje samą połowę z triggerem: podpisuje syntetyczną dostawę i wysyła ją prosto do webhooka, bez żadnego konta GitHub. To instrukcja wykonania z jednym zapisanym runem jako punktem odniesienia dla tej połowy. Dodawanie etykiet i komentarzy w issue wymaga połączenia z GitHubem, którego to środowisko nie ma, więc tego tu nie uruchomiono.

## Czego potrzebujesz { #what-you-need }

- [Działająca instalacja](../install.md) z profilem modelu.
- Żeby uruchomić to naprawdę: repozytorium, do którego możesz dodać webhook (źródło **GitHub** jako OAuth App), albo GitHub App zarejestrowana dla Twojej organizacji (**GitHub (App)**). Zobacz [dwa sposoby podłączenia GitHuba](../triggers.md#two-ways-to-connect-github-and-how-to-tell-which-you-are-running). Żadne z nich nie jest skonfigurowane na potrzeby sprawdzenia poniżej.
- Żeby agent mógł faktycznie dodawać etykiety albo komentarze: [połączenie MCP z GitHubem](../mcp.md#development) (uwierzytelnianie tokenem) albo uprawnienia zapisu samej GitHub App, przypisane do agenta. Tego też tu nie skonfigurowano.

## Przygotuj dane wejściowe { #prepare-the-input }

Przycięty, ale realistyczny payload webhooka `issues` dla fikcyjnego repozytorium, na tyle mały, żeby sprawdzić segregację ręcznie:

```json
{
  "action": "opened",
  "issue": {
    "number": 42,
    "title": "Export button does nothing on Safari",
    "html_url": "https://github.com/acme/widgets/issues/42",
    "body": "Steps to reproduce:\n1. Open the reports page in Safari 18\n2. Click Export as CSV\n3. Nothing happens, no download, no error in the console\n\nWorks fine in Chrome. This is blocking our weekly export for finance."
  },
  "repository": {"full_name": "acme/widgets"}
}
```

Nic tu nie jest prawdziwym repozytorium ani prawdziwym zgłoszeniem.

## Zbuduj agenta { #build-the-agent }

1. Utwórz agenta w **Agents → New agent** i wybierz swój profil modelu.
2. Zostaw Toolbox pusty na czas tej próby: agent ma tylko przeczytać dostawę i przeanalizować ją. **Date and time** wystarczy, jeśli segregacja ma odnosić się do dzisiejszej daty.
3. Ustaw jako instrukcje prompt z gotowego szablonu, a potem **Publish**:

```text
You triage new GitHub issues from the delivery described in the task message.
Suggest a priority (low, medium, high) and one or two labels.
Say whether it looks like a duplicate of an existing issue, using only what the message gives you.
Flag immediately, in the first line, if it looks like a security report.
End with a short comment-ready summary a maintainer could paste onto the issue.
You have no tool to read the repository or post the comment yourself - say so if asked to do either.
```

To prompt kryjący się za **Triage the new issue** w szablonach triggerów (`GET /trigger-templates`), który dokładnie tak wypełnia nowy trigger zdarzeń **GitHub**.

## Skonfiguruj trigger { #set-up-the-trigger }

W **Routines → New event trigger → GitHub** wybierz tego agenta, zostaw domyślny filtr (uruchamia tylko przy `opened`) i wklej otrzymany adres URL webhooka oraz sekret podpisu w **Settings → Webhooks → Add webhook** repozytorium, z typem treści `application/json`. Dokładne pola opisuje [przepis dla GitHuba](../triggers.md#a-github-recipe-5-minutes). Ten krok wymaga repozytorium, którego ta próba nie ma.

## Uruchom { #run-it }

Bez repozytorium, z którego mogłaby przyjść dostawa, podpisz syntetyczną dostawę sam, dokładnie tak, jak [samodzielne podpisanie dostawy](../triggers.md#signing-a-delivery-yourself) opisuje dla źródła ogólnego. Dostawy z GitHuba używają identycznego schematu `HMAC-SHA256`, zmienia się tylko nazwa nagłówka:

```python
import hashlib, hmac, json, httpx

secret = b"<the trigger's signing secret>"
body = json.dumps(payload).encode()  # the fixture above
signature = "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()

httpx.post(
    f"{BASE}/api/v1/webhooks/triggers/github/{trigger_id}",
    content=body,
    headers={
        "Content-Type": "application/json",
        "X-Hub-Signature-256": signature,
        "X-GitHub-Event": "issues",
    },
)
```

## Sprawdź wynik { #check-the-result }

| Sprawdzenie | Kryterium |
| --- | --- |
| Podpisany POST | `202`, od razu |
| Run w Activity | Powierzchnia `schedule` (trigger zdarzeń uruchamia się tak samo jak harmonogram), status completed |
| Segregacja | Podaje priorytet i jedną albo dwie etykiety, odnosi się do pytania o duplikat i nie jest oznaczona jako zgłoszenie bezpieczeństwa |
| Ostatnia linia odpowiedzi | Krótkie podsumowanie gotowe do wklejenia jako komentarz |
| Wywołania narzędzi | Żadnych. Ten agent nie ma narzędzia GitHuba, więc tylko analizuje dostarczony tekst |
| Prośba o samodzielne dodanie etykiety w rozmowie tego samego runu | Mówi, że nie ma do tego narzędzia, zamiast je wymyślać |
| Ten sam payload podpisany złym sekretem | `403`, zanim run w ogóle zostanie rozważony |
| Dostawa z `"action": "edited"` | `202` i brak nowego runu, bo domyślny filtr uruchamia tylko przy `opened` |

!!! example "Zapisano na v0.0.504, 25 września 2026"

    Model: Claude Sonnet 4.6 przez OpenRouter. Podpisana dostawa odpowiedziała `202`. Run pojawił się w Activity około dziesięć sekund później na powierzchni `schedule`, kosztował 0,003861 USD i zawierał wiadomość dołączoną przez trigger: „A GitHub issue was opened in acme/widgets. Issue #42: Export button does nothing on Safari …”.

    Odpowiedź: „**Not a security report.** Priority: High. Labels: `bug`, `browser-compatibility`. Duplicate check: Nothing in the provided information suggests this is a duplicate …”, zakończona akapitem gotowym do komentarza, który wymieniał kroki odtworzenia i sugerował maintainerowi sprawdzenie obsługi `Blob`/`<a download>` w Safari. Nie było żadnych wywołań narzędzi. Dostawa podpisana złym sekretem wróciła jako `403` z `"Webhook signature did not verify"`. Ten sam payload z `"action": "edited"` wrócił jako `202` bez nowego runu.

## Gdy coś pójdzie nie tak { #when-it-goes-wrong }

- **`403` przy każdej dostawie, prawdziwej czy syntetycznej.** Sekret się nie zgadza albo typ treści to nie `application/json`: dostawa zakodowana jako formularz podpisuje inne bajty niż wysłał GitHub. Zakładka **Recent Deliveries** przy webhooku na GitHubie pokazuje dokładne żądanie i odpowiedź dla prawdziwego repozytorium.
- **`202`, ale nic w Activity.** `202` znaczy „przyjęto”, a nie „zakończono”, i znaczy też „nic nie pasowało”: nieaktywny trigger albo odfiltrowana akcja odpowiadają identycznie. Sprawdź filtr triggera, zanim uznasz, że to błąd.
- **Trigger `GitHub (App)` nie ma webhooka w ustawieniach repozytorium.** Tak ma być: App dostarcza na jeden wspólny adres URL na instalację, a nie na adres na trigger. Zobacz [gdy przychodzi dostawa](../triggers.md#when-a-delivery-arrives).
- **Agent próbuje skomentować i nie może.** Agent w tej próbie celowo nie ma narzędzia GitHuba. Dodanie go to osobny, świadomy krok; zobacz niżej.

## Zapisz próbę { #record-the-trial }

Zachowaj podpisany payload, filtr triggera, run w Activity i jego odpowiedź. To dowodzi tylko działania triggera i promptu. Nie dowodzi dodawania etykiet ani komentowania, które wymaga własnej capability i własnego przeglądu.

## Kolejne kroki { #next-steps }

Żeby agent działał, a nie tylko proponował, przypisz [połączenie MCP z GitHubem](../mcp.md#development) albo uprawnienia zapisu GitHub App i zdecyduj, kto przegląda etykietę albo komentarz przed publikacją. Narzędzia MCP nie mają własnego zatwierdzania, więc przegląd musi zapewnić człowiek obserwujący run albo tryb czatu **Ask about everything**, tak samo jak przy [zamianie zadań ze spotkania na taski](meeting-to-tasks.md). Trigger zawsze działa jako [członek organizacji, który go utworzył](../concepts.md#it-runs-as-a-person), więc tę rolę daj temu, kto ma odpowiadać za źle działający trigger, a nie temu, kto akurat go skonfigurował.
