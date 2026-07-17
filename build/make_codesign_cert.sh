#!/bin/bash
# Vytvoří STABILNÍ self-signed code-signing certifikát "Spillway Self-Signed"
# a naimportuje ho do login keychainu. Běží JEDNOU na daném stroji.
#
#   bash build/make_codesign_cert.sh
#
# Proč: ad-hoc podpis mění identitu při každém buildu → macOS resetuje TCC
# oprávnění i Keychain ACL (B22/B23/R3). Stabilní certifikát = stabilní identita
# → oprávnění přežijí rebuildy. NEpotřebuje placený Apple Developer ID.
#
# Certifikát NENÍ v gitu (privátní klíč). Záloha .p12 se ukládá do
# ~/Library/Application Support/Spillway/ (mimo repo, práva 600).

set -euo pipefail

NAME="Spillway Self-Signed"
KEYCHAIN="$HOME/Library/Keychains/login.keychain-db"
OUTDIR="$HOME/Library/Application Support/Spillway"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

if security find-certificate -c "$NAME" >/dev/null 2>&1; then
  echo "✅ Certifikát '$NAME' už existuje — nic nedělám."
  exit 0
fi

echo "▶︎ Generuji self-signed certifikát (Code Signing EKU)…"
openssl req -x509 -newkey rsa:2048 -keyout "$TMP/cs.key" -out "$TMP/cs.crt" \
  -days 3650 -nodes -subj "/CN=$NAME/O=Spillway" \
  -addext "keyUsage=critical,digitalSignature" \
  -addext "extendedKeyUsage=critical,codeSigning" \
  -addext "basicConstraints=critical,CA:false"

openssl pkcs12 -export -inkey "$TMP/cs.key" -in "$TMP/cs.crt" \
  -name "$NAME" -out "$TMP/cs.p12" -passout pass:sw

echo "▶︎ Importuji do login keychainu (povoluji přístup pro codesign)…"
security import "$TMP/cs.p12" -k "$KEYCHAIN" -P sw -T /usr/bin/codesign

mkdir -p "$OUTDIR"
cp "$TMP/cs.p12" "$OUTDIR/codesign-identity.p12"; chmod 600 "$OUTDIR/codesign-identity.p12"
cp "$TMP/cs.crt" "$OUTDIR/codesign-identity.crt"

echo "✅ Hotovo. Záloha: $OUTDIR/codesign-identity.p12 (heslo: sw)"
echo "   Při prvním podpisu klikni v dialogu na 'Vždy povolit'."
