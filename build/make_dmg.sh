#!/bin/bash
# Vytvoří jednoduchý DMG installer ze Spillway.app (drag-to-Applications).
# Předpokládá, že build/dist/Spillway.app už existuje (viz README).
#
#   bash build/make_dmg.sh
#
# Pozn.: appka je jen ad-hoc podepsaná (ne notarizovaná) — Gatekeeper při
# prvním otevření ukáže "nelze ověřit vývojáře". Uživatel musí kliknout
# pravým tlačítkem → Otevřít (nebo Nastavení systému → Soukromí → Otevřít i tak).

set -euo pipefail
cd "$(dirname "$0")/.."

APP="build/dist/Spillway.app"
STAGE="build/dmg_stage"
DMG="build/dist/Spillway.dmg"

if [ ! -d "$APP" ]; then
  echo "Chybí $APP — nejdřív: uv run pyinstaller build/spillway.spec --noconfirm --distpath build/dist --workpath build/work"
  exit 1
fi

rm -rf "$STAGE" "$DMG"
mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"

hdiutil create -volname "Spillway" -srcfolder "$STAGE" -ov -format UDZO "$DMG"
rm -rf "$STAGE"

echo "✅ $DMG"
