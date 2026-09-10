#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
plugin_dir="${XDG_CONFIG_HOME:-$HOME/.config}/omarchy/plugins/dev.usb-boards"

# The shell rejects symlinks inside ~/.config/omarchy/plugins/, so install
# a real copy instead of linking back to the checkout.
if [[ -L "$plugin_dir" ]]; then
  rm "$plugin_dir"
fi

mkdir -p "$plugin_dir"
cp "$project_dir/manifest.json" "$project_dir/Panel.qml" "$project_dir/ProfileStore.js" "$project_dir/usb_boards.py" "$project_dir/serial_monitor.py" "$project_dir/usb_clone.py" "$plugin_dir/"
omarchy plugin validate "$plugin_dir"
omarchy-shell shell rescanPlugins

if ! omarchy bar put dev.usb-boards --section right; then
  printf 'Plugin copied, but it could not be added to the bar automatically.\n' >&2
  exit 1
fi

printf 'Installed dev.usb-boards from %s\n' "$project_dir"
