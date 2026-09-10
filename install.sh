#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
plugin_dir="${XDG_CONFIG_HOME:-$HOME/.config}/omarchy/plugins/dev.usb-boards"
runtime_files=(
  manifest.json
  Panel.qml
  ProfileStore.js
  usb_boards.py
  serial_monitor.py
  usb_clone.py
  clone_policy.py
  clone_probe.py
)

# The shell rejects symlinks inside ~/.config/omarchy/plugins/, so install
# a real copy instead of linking back to the checkout.
if [[ -L "$plugin_dir" ]]; then
  rm "$plugin_dir"
fi

mkdir -p "$plugin_dir"
for runtime_file in "${runtime_files[@]}"; do
  cp -- "$project_dir/$runtime_file" "$plugin_dir/$runtime_file"
done
omarchy plugin validate "$plugin_dir"
omarchy-shell shell rescanPlugins

if ! omarchy bar put dev.usb-boards --section right; then
  printf 'Plugin copied, but it could not be added to the bar automatically.\n' >&2
  exit 1
fi

printf 'Installed dev.usb-boards from %s\n' "$project_dir"
