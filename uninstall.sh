#!/bin/bash
# Removes Pixel Claude Desktop Pet and everything install.sh added.
set -euo pipefail

DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
APP="$DATA/pixel-claude"
HYPR="${XDG_CONFIG_HOME:-$HOME/.config}/hypr"
CLAUDE_SETTINGS="$HOME/.claude/settings.json"
say() { printf '\033[1;33m•\033[0m %s\n' "$*"; }

# say goodbye if he's running (a second launch makes him wave and quit)
if [[ -x $APP/pixel-claude ]] && command -v hyprctl >/dev/null \
   && hyprctl layers 2>/dev/null | grep -q 'namespace: pixel-claude'; then
  "$APP/pixel-claude" >/dev/null 2>&1 &
  sleep 3
fi

rm -rf "$APP" "$DATA/applications/pixel-claude.desktop" \
  "$DATA/icons/hicolor/256x256/apps/pixel-claude.png" "${XDG_RUNTIME_DIR:-/tmp}/pixel-claude"
[[ -L $HOME/.local/bin/pixel-claude ]] && rm "$HOME/.local/bin/pixel-claude"
say "Removed the app"

for bindfile in "$HYPR/bindings.lua" "$HYPR/bindings.conf"; do
  if [[ -f $bindfile ]] && grep -q '\.local/bin/pixel-claude' "$bindfile"; then
    cp "$bindfile" "$bindfile.bak.pixel-claude-uninstall"
    sed -i '/Pixel Claude desktop pet/d; \#\.local/bin/pixel-claude#d' "$bindfile"
    command -v hyprctl >/dev/null && hyprctl reload >/dev/null 2>&1 || true
    say "Removed the keybinding from $bindfile"
  fi
done

if [[ -f $CLAUDE_SETTINGS ]] && grep -q 'pixel-claude/claude-hook' "$CLAUDE_SETTINGS"; then
  cp "$CLAUDE_SETTINGS" "$CLAUDE_SETTINGS.bak.pixel-claude-uninstall"
  tmp="$(mktemp)"
  jq '
    .hooks |= with_entries(
      .value |= map(select(any(.hooks[]?; (.command // "") | test("pixel-claude/claude-hook")) | not))
      | select(.value | length > 0))
    | if .hooks == {} then del(.hooks) else . end
  ' < "$CLAUDE_SETTINGS" > "$tmp"
  mv "$tmp" "$CLAUDE_SETTINGS"
  say "Removed the Claude Code hooks"
fi

say "Pixel Claude is gone. Bye for now!"
