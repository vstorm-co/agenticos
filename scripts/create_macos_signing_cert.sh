#!/usr/bin/env bash
# Make the one self-signed code-signing certificate that every macOS release is
# signed with, so macOS keeps the Screen Recording and Microphone grants across
# updates (they are tied to the signing identity, and an ad-hoc one changes
# with every build). Run it once; keep the printed values in the `apps-release`
# environment as secrets and never regenerate the certificate, or every user
# is asked again.
#
# Usage: scripts/create_macos_signing_cert.sh [output-dir]
set -euo pipefail

name="AgenticOS Release Signing"
out="${1:-$(mktemp -d)}"
password="$(openssl rand -base64 24)"
mkdir -p "$out"

cat >"$out/openssl.cnf" <<CNF
[req]
distinguished_name = dn
x509_extensions = ext
prompt = no
[dn]
CN = $name
O = Vstorm
[ext]
basicConstraints = critical,CA:false
keyUsage = critical,digitalSignature
extendedKeyUsage = critical,codeSigning
CNF

openssl req -x509 -newkey rsa:3072 -sha256 -days 3650 -nodes \
  -config "$out/openssl.cnf" -keyout "$out/key.pem" -out "$out/cert.pem"
# The legacy algorithms are deliberate: macOS `security import` cannot read the
# AES/SHA-256 container OpenSSL 3 writes by default ("MAC verification failed").
openssl pkcs12 -export -certpbe PBE-SHA1-3DES -keypbe PBE-SHA1-3DES -macalg sha1 -inkey "$out/key.pem" -in "$out/cert.pem" \
  -name "$name" -passout "pass:$password" -out "$out/signing.p12"
rm "$out/key.pem" "$out/openssl.cnf"

echo "Certificate written to $out/signing.p12 (the private key is inside it)."
echo
echo "Add these to the apps-release environment:"
echo "  secret MACOS_SELF_SIGNED_P12           = $(base64 <"$out/signing.p12" | tr -d '\n')"
echo "  secret MACOS_SELF_SIGNED_P12_PASSWORD  = $password"
echo "  variable MACOS_SELF_SIGNED_IDENTITY    = $name"
echo
fingerprint="$(openssl x509 -in "$out/cert.pem" -noout -fingerprint -sha1 | sed 's/.*=//; s/://g' | tr 'A-F' 'a-f')"
echo "Commit this fingerprint to scripts/macos_signing_identity.txt, so the installer can"
echo "check that a download was signed by this certificate and not just that it matches"
echo "a checksum published beside it:"
echo "  $fingerprint"
