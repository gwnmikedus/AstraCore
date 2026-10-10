#!/bin/bash
# Double-click in Finder. Stops whichever Astracore is running (tunnel first, then the app).
cd "$(dirname "$0")/.." || exit 1
./astracore stop
echo
read -r -n 1 -p "Press any key to close this window." _
