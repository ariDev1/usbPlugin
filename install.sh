#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
plugin_dir="${XDG_CONFIG_HOME:-$HOME/.config}/omarchy/plugins/dev.usb-boards"

if [[ -e "$plugin_dir" && ! -L "$plugin_dir" ]]; then
  printf 'Refusing to replace existing directory: %s\n' "$plugin_dir" >&2
  exit 1
fi

mkdir -p "$(dirname -- "$plugin_dir")"
ln -sfn "$project_dir" "$plugin_dir"
omarchy-shell shell rescanPlugins

if ! omarchy bar put dev.usb-boards --section right; then
  printf 'Plugin linked, but it could not be added to the bar automatically.\n' >&2
  exit 1
fi

printf 'Installed dev.usb-boards from %s\n' "$project_dir"
