---
source_sha: "136ead96ab7d"
---

# Dlaczego macOS pokazuje ostrzeżenie { #why-macos-shows-a-warning }

AgenticOS pobrany ręcznie jako DMG może wyświetlić **Apple nie może zweryfikować tej aplikacji**. To kontrola wydawcy przez Gatekeepera. Domyślne wydanie używa stałego, samopodpisanego certyfikatu, który zachowuje tożsamość aplikacji, ale nie jest notaryzacją Apple Developer ID. Ostrzeżenie nie oznacza przyznania dostępu do ekranu ani mikrofonu.

## Zainstaluj wydanie { #install-a-release }

Pobieraj tylko z [wydań AgenticOS](https://github.com/vstorm-co/agenticos/releases/latest). Przenieś aplikację do Applications, spróbuj otworzyć ją raz, a potem użyj **Ustawienia systemowe → Prywatność i ochrona → Otwórz mimo to**, jeżeli zezwala na to organizacja. Zobacz [instrukcję Apple](https://support.apple.com/pl-pl/102445). Nie wyłączaj globalnie Gatekeepera.

Możesz też użyć `brew install --cask vstorm-co/agenticos/agenticos` lub [instalatora projektu](https://github.com/vstorm-co/agenticos/blob/main/scripts/install_macos.sh). Instalują wydanie i usuwają quarantine tylko z tej aplikacji. Skrypt sprawdza checksumę i zapisany fingerprint wydawcy. Brak lub błędna odpowiedź pliku pin, niezgodny podpis albo checksuma zatrzymują instalację. Homebrew opiera się na checksumie tapu; nie wykonuje dodatkowej kontroli wydawcy ze skryptu.

## Zachowaj uprawnienia po aktualizacji { #keep-permissions-across-updates }

Zgody na nagrywanie ekranu i mikrofon są związane z tożsamością podpisu. Zachowaj jeden certyfikat między wydaniami. Starszy build ad-hoc albo zmieniony certyfikat mogą wymagać ponownych zgód. Sam podpis aktualizacji nie zachowuje uprawnień systemowych. Włącz tylko potrzebne uprawnienia w konfiguracji aplikacji lub ustawieniach macOS.

## Skonfiguruj podpisywanie wydań { #configure-release-signing }

Maintainer tworzy stały certyfikat przez `scripts/create_macos_signing_cert.sh`. Zapisuje `MACOS_SELF_SIGNED_P12` i `MACOS_SELF_SIGNED_P12_PASSWORD` jako secrets, a `MACOS_SELF_SIGNED_IDENTITY` jako variable w `apps-release`. Do repo trafia tylko publiczny fingerprint SHA-1 w `scripts/macos_signing_identity.txt`, nigdy P12 ani hasło. Po publikacji pina instalator wymaga wydania podpisanego tym certyfikatem.

Podpis Developer ID i notaryzacja pozostają opcjonalnym trybem wymagającym konta Apple i credentials maintainera. Wymienia je [konfiguracja wydań desktopu](../desktop.md#installers-and-updates). Wydanie samopodpisane nie oznacza notaryzacji.
