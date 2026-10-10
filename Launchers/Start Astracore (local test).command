#!/bin/bash
# Double-click in Finder. Starts Astracore locally (http://localhost:8765, .env.local, data/local) and opens it.
cd "$(dirname "$0")/.." || exit 1
./astracore start && open "http://localhost:8765"
echo
read -r -n 1 -p "Press any key to close this window." _
