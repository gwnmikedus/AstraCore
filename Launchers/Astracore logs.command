#!/bin/bash
# Double-click in Finder. Follows the app and tunnel logs (close the window to stop).
cd "$(dirname "$0")/.." || exit 1
./astracore logs
echo
read -r -n 1 -p "Press any key to close this window." _
