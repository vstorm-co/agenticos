# Why macOS shows a warning

A manually downloaded AgenticOS DMG can show **Apple could not verify this app**. This is Gatekeeper's publisher check. The default release uses a stable self-signed certificate, which preserves the app's signing identity but is not Apple's Developer ID notarization. It does not indicate that the app has been granted screen or microphone access.

## Install a release

Download only from [AgenticOS releases](https://github.com/vstorm-co/agenticos/releases/latest). Move the app to Applications, try opening it once, then use **System Settings → Privacy & Security → Open Anyway** if your organization permits this. Follow [Apple's instructions](https://support.apple.com/en-us/102445). Do not disable Gatekeeper globally.

Alternatively, use `brew install --cask vstorm-co/agenticos/agenticos` or the [project installer](https://github.com/vstorm-co/agenticos/blob/main/scripts/install_macos.sh). These install the release and clear quarantine for this app only. The script checks the release checksum and the committed publisher fingerprint. It stops on a missing or malformed pin response, a signature mismatch or a failed checksum. Before publishing the Homebrew checksum, the release workflow mounts both Mac images and verifies each app against the committed publisher fingerprint. A missing pin, invalid signature or different signer stops publication.

## Keep permissions across updates

Screen Recording and Microphone permissions are tied to the app's signing identity. Keep one release certificate across versions. An older ad-hoc build or a changed certificate may require renewed permissions; update signatures alone do not preserve the operating system's permission grants. Enable only the permissions you need in the app's setup or macOS settings.

## Configure release signing

Maintainers create the persistent certificate with `scripts/create_macos_signing_cert.sh`. Store `MACOS_SELF_SIGNED_P12` and `MACOS_SELF_SIGNED_P12_PASSWORD` as secrets and `MACOS_SELF_SIGNED_IDENTITY` as a variable in `apps-release`. Commit only the public SHA-1 certificate fingerprint in `scripts/macos_signing_identity.txt`, never the P12 or its password. The installer requires releases signed with that certificate after the pin is published.

Developer ID signing and notarization remain an optional release mode requiring the maintainer's Apple account and credentials. The [desktop release configuration](../desktop.md#installers-and-updates) lists them. A self-signed release does not claim notarization.
