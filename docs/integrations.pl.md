---
source_sha: "7a39bdbfc81f"
---

# Wbudowane integracje { #built-in-integrations }

Połącz konto w **Ustawienia → Vault → Połączone konta**. Każdy produkt Google, Microsoft i Slack ma osobną capability w **Toolboxie** agenta: wybór konta i przełączniki poszczególnych narzędzi. Integracje używają bezpośrednio API dostawców. Nie wymagają serwerów MCP dostawców, programu Google Workspace MCP Preview ani licencji Microsoft Copilot.

## Konfiguracja konta { #set-up-an-account }

Kreator pokazuje dokładny URL callbacku tego wdrożenia, odnośnik do konsoli i żądane zakresy. Najpierw wybierz produkty. Domyślnie przyznajesz odczyt; zapis wymaga jawnego zaznaczenia. Administrator zapisuje jedną aplikację OAuth widoczną dla organizacji w Vault. Członkowie używają jej, łącząc własne konta. Przy kilku takich credentialach administrator musi rozstrzygnąć, który ma służyć wdrożeniu.

Google: utwórz projekt Cloud, włącz wskazane API (kreator podaje polecenie `gcloud services enable`), skonfiguruj ekran zgody i klienta OAuth typu **Web application**. Skopiuj callback i zapisz `google_oauth_app`. Internal służy organizacji Workspace będącej właścicielem projektu. Tokeny odświeżania aplikacji External w trybie Testing mogą wygasać po siedmiu dniach. Zwykła integracja API nie wymaga klienta AI-powered-agent ani API hostowanego MCP.

Microsoft: zarejestruj aplikację Entra, wybierz typy kont i tenant, dodaj przekierowanie Web oraz pokazane delegowane uprawnienia Graph i zapisz `microsoft_oauth_app`. Konta służbowe i osobiste działają tam, gdzie obsługuje je dany produkt Graph; Teams wymaga konta służbowego. Polityka tenanta może wymagać zgody administratora.

Slack: **Utwórz aplikację Slack** otwiera manifest z callbackiem wdrożenia i zakresami użytkownika do odczytu. Przed zapisem dodaj zakresy zapisu, ponownie zainstaluj aplikację i udziel zgody. Zapisz `slack_oauth_app`. Możesz wykorzystać istniejącą aplikację bota kanałowego, dodając callback i zakresy użytkownika. Nadal obowiązują limity aplikacji workspace i zgoda administratora. Przełącznik **Agents → MCP Server** jest potrzebny tylko przy osobnym użyciu hostowanego MCP Slacka.

## Alternatywy dla OAuth { #alternatives-to-oauth }

Wybór tożsamości konta aplikacyjnego wymaga prawa edycji jego credentiala w Vault, także dla kont osobistych. Sam odczyt współdzielonego credentiala nie upoważnia do działania jako inna osoba. Konto osobiste sprawdza prawo edycji przed każdą wymianą tokenu.

Google obsługuje `gcp_service_account` z Vault i subject dla delegacji domenowej Workspace. Administrator Workspace musi autoryzować wyświetlone zakresy. Samo konto serwisowe czyta tylko udostępnione mu zasoby; nie staje się osobistym kontem Gmail.

Microsoft obsługuje sekret klienta `entra_app` i uprawnienia aplikacyjne zatwierdzone przez administratora. Dla poczty/kalendarza podaj skrzynkę, a dla Teams identyfikator obiektu użytkownika w katalogu: pozwala to dopasować wzmianki bez dostępu do całego katalogu. Excel wymaga delegated OAuth. Uprawnienia aplikacyjne nie pozwalają na zwykłe publikowanie wiadomości Teams; użyj delegated OAuth. Kreator pokazuje właściwą listę uprawnień dla wybranego trybu.

Slack przyjmuje istniejące tokeny użytkownika `xoxp-` i bota `xoxb-`. Bot publikuje jako aplikacja, ale nie używa wyszukiwania dostępnego tylko użytkownikom. Przed operacją sprawdzane są rzeczywiście przyznane zakresy. Tokeny i klucze są szyfrowane przez Vault, nigdy zapisywane w specyfikacji agenta.

**IMAP** to osobne połączenie poczty tylko do odczytu: host, port ze zweryfikowanym TLS, użytkownik, hasło aplikacji i stały folder. Operator musi dopuścić dokładny host w `MIRAGE_ALLOWED_HOSTS`. Połączenie korzysta z zainstalowanego klienta Mirage. Basic-auth IMAP Microsoft 365 nie jest tu alternatywą dla OAuth Microsoftu.

## Uprawnienia agenta { #choose-what-an-agent-can-do }

Produkty Google: Gmail (wyszukiwanie, odczyt, etykiety, szkice i wysyłka), Calendar (wydarzenia i dostępność), Drive (wyszukiwanie, metadane, odczyt, upload i kopie), Docs, Sheets i Slides (odczyt, tworzenie i edycja). Sheets obejmuje zakresy, dopisywanie wierszy i aktualizację komórek.

Produkty Microsoft: Outlook mail, Calendar, pliki OneDrive/SharePoint, Excel, dokumenty Word oraz rozmowy i kanały Teams. Slack oferuje wyszukiwanie, wzmianki o mnie, historię i wątki, kanały i użytkowników, publikację, odpowiedzi, DM i reakcje. IMAP wyszukuje i czyta wiadomości bez oznaczania ich jako przeczytane.

Wybierz **personal**, aby użyć konta aktualnej osoby po dokładnej nazwie, etykiecie lub adresie. Pusta nazwa działa tylko przy jednym pasującym koncie. Narzędzia osobiste wymagają prywatnej rozmowy i aktualnego członkostwa w organizacji. Dla wspólnych automatyzacji wybierz **organization** i ID połączenia. Capability nie pożycza konta innego członka.

Każdy zapis wymaga zatwierdzenia przez człowieka w uruchomieniach agenta, niezależnie od łagodniejszych ustawień narzędzia. Wyłączone narzędzie znika z oferty. Workflow udostępnia te same operacje jako `integration.<product>.<operation>`, z tym samym kontem i transportem. Zapisy nie są automatycznie ponawiane. Przed zapisem wymagającym zatwierdzenia w workflow umieść węzeł approval.

Węzły plikowe przyjmują base64, nigdy lokalną ścieżkę serwera. Word przyjmuje tytuł i akapity i tworzy `.docx`. Upload i download mają limit 20 MB, JSON 2 MB, a wyodrębniony tekst 100 000 znaków. Nieudany zapis mógł dotrzeć do dostawcy: przed ponowieniem sprawdź wynik po jego stronie.

## Wiedza, triggery i watche { #knowledge-triggers-and-watches }

Źródła Drive i SharePoint wybierają to samo konto organizacji zamiast osobnego credentiala. OneDrive używa konektora SharePoint z wybranym dyskiem/folderem. Slack indeksuje tylko wybrane kanały i ich wątki. Przy każdej synchronizacji sprawdzana jest autoryzacja konta; wspólna baza wiedzy nie używa po cichu prywatnych kont członków.

Triggery rutyn używają istniejącej kolejki transakcyjnej, deduplikacji i zatwierdzonych źródeł. Na kontach natywnych działają filtry Gmail/Outlook, zapowiedzi spotkań i zmiany plików. Slack dodaje wiadomości, wzmianki i DM, Teams wiadomości i wzmianki, a IMAP nową pocztę. Sheets śledzi **dopisywane wiersze** wybranego arkusza i zakładki; pierwsze sprawdzenie zapamiętuje ostatni zajęty wiersz w zakresie kolumn A:ZZ. Wstawianie/usuwanie wierszy i edycje istniejących nie są dopisaniem.

Watch wybiera jedno osobiste konto i produkt oraz otrzymuje stałe narzędzie zmian tylko do odczytu. Najpierw włącz produkt na agencie. Rozmowy Slack i delegowane czaty Teams wybiera się w capability. Kanały Teams mają zapis `channel/team-id/channel-id`; app-only Teams bez wskazanych rozmów czyta wszystkie czaty skonfigurowanego użytkownika.

Każdy watch ma osobny trwały kursor, przesuwany dopiero po pomyślnym sprawdzeniu. Nowy lub zresetowany kursor ustala cichy punkt startowy. Gmail używa history IDs, Outlook i kalendarze kursorów dostawcy, Slack czasu na rozmowę, a IMAP UIDVALIDITY/UID. Czaty Teams delegated używają `lastModifiedDateTime`, a kanały i app-only Graph delta. Przy przekroczeniu limitu zaległości zawęź źródło.

Zobacz [capabilities](reference/capabilities.md), [triggery](triggers.md), [zarządzanie i watche](governance.md#proactive-work) oraz [MCP](mcp.md).

Przy łączeniu nadaj etykietę, np. Praca; używaj tej samej etykiety dla odpowiedniego konta każdej osoby.

## Odoo { #odoo }

Połącz Odoo 19+ przez JSON-2, podając adres HTTPS, nazwę bazy i klucz API użytkownika biznesowego. Operator musi dodać dokładny host do `ODOO_ALLOWED_HOSTS`; ścieżki, przekierowania i niestandardowe porty są odrzucane. Zewnętrzne API Odoo Online wymaga planu Custom. Zainstaluj używane moduły i ogranicz uprawnienia oraz reguły rekordów użytkownika w Odoo. Klucze wygasają: po rotacji połącz konto ponownie. Zapis jest opcjonalny, a każdy zapis agenta wymaga zatwierdzenia.

Capabilities obejmują kontakty, CRM, sprzedaż, faktury, magazyn i projekty. Udostępniają metadane pól, ograniczone wyszukiwanie i odczyt oraz osobne narzędzia tworzenia i edycji tam, gdzie są obsługiwane. Stany magazynowe są tylko do odczytu; operacje magazynowe korzystają z transferów i ruchów. Narzędzia i węzły workflow używają wspólnego konta i adaptera JSON-2. Dowolne modele, metody i kontekst podany przez użytkownika są niedozwolone.

Watche i triggery rutyn czytają nowe i zmienione rekordy wybranego obszaru. Każdy model ma własny kursor `(write_date, id)`; pierwszy odczyt tworzy cichą bazę. Kolejne odczyty pobierają do 100 rekordów modelu, zachowując pozostałe do następnego przebiegu. Usunięcia nie są zdarzeniami. Znaczniki Odoo mają dokładność sekundy, więc zmiany tego samego rekordu w jednej sekundzie mogą się połączyć. Synchronizacja wiedzy indeksuje wyłącznie wskazane pola przez konto organizacji; niepełne listy nie usuwają niewidocznych dokumentów.

Potwierdzenie sprzedaży, księgowanie faktur oraz potwierdzanie, rezerwacja i zatwierdzanie transferów mają osobne narzędzia wymagające zatwierdzenia. Używaj tych akcji zamiast zmieniać pole stanu. Akcja może zwrócić kreator do dokończenia w Odoo; przed zgłoszeniem sukcesu odczytaj rekord. Tworzenie faktury wymaga jawnego `move_type` (klient, dostawca, korekta lub paragon). Obsługiwane są pola skalarne i dołączanie/zastępowanie/czyszczenie identyfikatorów relacji. Powiązane rekordy twórz i edytuj ich własnymi narzędziami; zagnieżdżone mutacje ORM i wartości pól będące obiektami JSON są odrzucane.

## Exchange Online { #exchange-online }

Outlook mail i Outlook Calendar łączą się z Microsoft Exchange Online przez Microsoft Graph. W kreatorze Microsoft użyj delegowanego OAuth albo konta aplikacyjnego Entra z uprawnieniami zatwierdzonymi przez administratora i wskazaną skrzynką. Osobne hasło IMAP i licencja Work IQ nie są potrzebne. Ta ścieżka dotyczy Exchange Online; nie dodaje obsługi lokalnego Exchange ani EWS.
