#!/bin/bash
# Double-click in Finder. Puts Astracore online at https://astracore.hoppyhome.nl (app + Cloudflare tunnel) and opens it.
cd "$(dirname "$0")/.." || exit 1
./astracore start --prod && open "https://astracore.hoppyhome.nl"
echo
read -r -n 1 -p "Press any key to close this window." _
