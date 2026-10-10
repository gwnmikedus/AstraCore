#!/bin/bash
# Double-click to put Astracore online (production mode, through the Cloudflare tunnel).
cd "$(dirname "$0")" || exit 1
./astracore start --prod
echo
read -r -n 1 -p "Press any key to close this window." _
