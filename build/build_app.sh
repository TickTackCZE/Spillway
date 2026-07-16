#!/bin/bash
# Sestaví Spillway.app a podepíše ji STABILNÍM self-signed certifikátem.
#
#   bash build/build_app.sh
#
# Proč self-signed a ne ad-hoc: ad-hoc podpis má jiný CDHash při každém buildu,
# takže macOS bere každý rebuild jako jinou appku a resetuje TCC oprávnění
# (Zpřístupnění/Monitorování vstupu) i Keychain ACL (řešilo B22/B23/R3).
# Self-signed certifikát má STABILNÍ identitu → oprávnění přežijí rebuildy.
#
# Certifikát "Spillway Self-Signed" musí být v login keychainu (vytvoří ho
# build/make_codesign_cert.sh, běží jednou). Při PRVNÍM podpisu macOS jednou
# zeptá "codesign chce přístup ke klíči" → klikni "Vždy povolit".

set -euo pipefail
cd "$(dirname "$0")/.."

IDENTITY="Spillway Self-Signed"
APP="build/dist/Spillway.app"

if ! security find-certificate -c "$IDENTITY" >/dev/null 2>&1; then
  echo "❌ Chybí certifikát '$IDENTITY' v keychainu. Spusť nejdřív: bash build/make_codesign_cert.sh"
  exit 1
fi

echo "▶︎ PyInstaller build…"
uv run pyinstaller build/spillway.spec --noconfirm --distpath build/dist --workpath build/work

echo "▶︎ Podepisuji stabilním certifikátem '$IDENTITY'…"
# --deep podepíše i vnořené .so/.dylib (PyInstaller jich má stovky).
codesign --force --deep --timestamp=none -s "$IDENTITY" "$APP"

echo "▶︎ Ověření podpisu:"
codesign -dvvv "$APP" 2>&1 | grep -E "Authority|Identifier|Signature|TeamIdentifier" | head
echo
echo "▶︎ Designated requirement (na tohle se váže TCC — musí být stabilní):"
codesign -d --requirements - "$APP" 2>&1 | tail -2

echo
echo "✅ Hotovo: $APP"
echo "   Poprvé: udělit Zpřístupnění + Monitorování vstupu. Díky stabilnímu"
echo "   podpisu to při dalších buildech už NEBUDEŠ muset dělat znovu."
