#!/bin/sh
# Install helper: copies scripts/xdg-open and scripts/open to $HOME/bin and makes them executable.

set -e
dest="$HOME/bin"
mkdir -p "$dest"
cp "$(dirname "$0")/xdg-open" "$dest/xdg-open"
cp "$(dirname "$0")/open" "$dest/open"
chmod +x "$dest/xdg-open" "$dest/open"

printf 'Installed wrapper to %s\n' "$dest"
printf '\nTo use it in this shell run:\n'
printf '  export PATH="%s:$PATH"\n' "$dest"
printf '\nTo persist, add that line to your shell rc (e.g. ~/.bashrc) or your devcontainer shell config.\n'
