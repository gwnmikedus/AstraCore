#!/bin/bash
# Double-click in Finder. Shows whether Astracore runs, in which mode, and whether the tunnel is up.
cd "$(dirname "$0")/.." || exit 1
./astracore status
echo
read -r -n 1 -p "Press any key to close this window." _
