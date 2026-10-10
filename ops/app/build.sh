#!/bin/bash
# Builds "Astracore Control.app" in the repo root from AstracoreControl.applescript (macOS only).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
APP="$ROOT/Astracore Control.app"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

sed "s#__REPO__#$ROOT#" "$ROOT/ops/app/AstracoreControl.applescript" > "$TMP/control.applescript"
rm -rf "$APP"
osacompile -o "$APP" "$TMP/control.applescript"

# Icon from the Astracore mark (SVG -> PNG via Quick Look -> .icns)
qlmanage -t -s 1024 -o "$TMP" "$ROOT/src/astracore/static/img/mark.svg" >/dev/null 2>&1 || true
PNG="$TMP/mark.svg.png"
if [[ -f "$PNG" ]]; then
  mkdir -p "$TMP/icon.iconset"
  for s in 16 32 128 256 512; do
    sips -z $s $s "$PNG" --out "$TMP/icon.iconset/icon_${s}x${s}.png" >/dev/null
    sips -z $((s*2)) $((s*2)) "$PNG" --out "$TMP/icon.iconset/icon_${s}x${s}@2x.png" >/dev/null
  done
  iconutil -c icns "$TMP/icon.iconset" -o "$APP/Contents/Resources/applet.icns"
  rm -f "$APP/Contents/Resources/Assets.car"            # the default icon would win over applet.icns
  /usr/libexec/PlistBuddy -c "Delete :CFBundleIconName" "$APP/Contents/Info.plist" 2>/dev/null || true
fi
/usr/libexec/PlistBuddy -c "Set :CFBundleName Astracore Control" "$APP/Contents/Info.plist" 2>/dev/null || true
/usr/libexec/PlistBuddy -c "Add :CFBundleIdentifier string nl.hoppyhome.astracore.control" "$APP/Contents/Info.plist" 2>/dev/null \
  || /usr/libexec/PlistBuddy -c "Set :CFBundleIdentifier nl.hoppyhome.astracore.control" "$APP/Contents/Info.plist"
codesign --force --deep -s - "$APP" >/dev/null 2>&1 || true   # bundle was edited: re-sign (ad hoc)
touch "$APP"
echo "Built: $APP"
