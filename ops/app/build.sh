#!/bin/bash
# Builds "AstraCore Control.app" in the repo root from the SwiftUI sources in ops/app/Control (macOS 13+).
# Needs only the Command Line Tools (xcode-select --install), not Xcode. Build it per Mac, also after a fresh clone;
# the app isn't in git. It drives ./astracore and gh in this checkout.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
APP="$ROOT/AstraCore Control.app"
SRC="$ROOT/ops/app/Control"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

command -v swiftc >/dev/null || { echo "swiftc not found. Install the Command Line Tools: xcode-select --install" >&2; exit 1; }
VERSION=$(sed -n 's/^version = "\(.*\)"/\1/p' "$ROOT/pyproject.toml" | head -1)

echo "Compiling…"
swiftc -parse-as-library -O -swift-version 5 -target "$(uname -m)-apple-macos13" \
  -o "$TMP/AstraCoreControl" "$SRC"/*.swift

echo "Drawing the icon…"
swift "$ROOT/ops/app/make_icon.swift" "$TMP/icon.png" >/dev/null
mkdir -p "$TMP/AppIcon.iconset"
for s in 16 32 128 256 512; do
  sips -z $s $s "$TMP/icon.png" --out "$TMP/AppIcon.iconset/icon_${s}x${s}.png" >/dev/null
  sips -z $((s*2)) $((s*2)) "$TMP/icon.png" --out "$TMP/AppIcon.iconset/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns "$TMP/AppIcon.iconset" -o "$TMP/AppIcon.icns"

# Replace the app (also the old AppleScript "Astracore Control.app": same path on a case-insensitive disk).
rm -rf "$APP" "$ROOT/Astracore Control.app"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
mv "$TMP/AstraCoreControl" "$APP/Contents/MacOS/AstraCoreControl"
mv "$TMP/AppIcon.icns" "$APP/Contents/Resources/AppIcon.icns"
cat >"$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>AstraCore Control</string>
  <key>CFBundleDisplayName</key><string>AstraCore Control</string>
  <key>CFBundleIdentifier</key><string>nl.hoppyhome.astracore.control</string>
  <key>CFBundleExecutable</key><string>AstraCoreControl</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>${VERSION:-0.0.0}</string>
  <key>CFBundleVersion</key><string>$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || echo 0)</string>
  <key>LSMinimumSystemVersion</key><string>13.0</string>
  <key>LSApplicationCategoryType</key><string>public.app-category.developer-tools</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>AstraCoreRepo</key><string>$ROOT</string>
</dict>
</plist>
PLIST
codesign --force --deep -s - "$APP" >/dev/null 2>&1 || true   # ad hoc signature, so macOS runs the local build
touch "$APP"   # Finder and the Dock pick up the new icon
echo "Built: $APP"
