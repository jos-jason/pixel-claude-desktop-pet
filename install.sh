#!/bin/bash
# Installs Pixel Claude Desktop Pet for the current user.
#   ./install.sh        asks before each optional step
#   ./install.sh --yes  accepts every step
set -euo pipefail

SRC="$(dirname "$(readlink -f "$0")")"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
APP="$DATA/pixel-claude"
BIN="$HOME/.local/bin"
HYPR="${XDG_CONFIG_HOME:-$HOME/.config}/hypr"
CLAUDE_SETTINGS="$HOME/.claude/settings.json"
EVENTS=(SessionStart SessionEnd UserPromptSubmit Stop PreToolUse PostToolUse PostToolUseFailure
        StopFailure Notification)

yes=0
[[ ${1:-} == -y || ${1:-} == --yes ]] && yes=1

ask() {
  ((yes)) && return 0
  local a
  read -rp "$1 [Y/n] " a
  [[ -z $a || $a == [Yy]* ]]
}
say() { printf '\033[1;33m•\033[0m %s\n' "$*"; }

# ---- dependencies ----
missing=()
python3 -c 'import gi; gi.require_version("Gtk", "4.0"); from gi.repository import Gtk' 2>/dev/null \
  || missing+=(python-gobject gtk4)
[[ -e /usr/lib/libgtk4-layer-shell.so ]] || missing+=(gtk4-layer-shell)
command -v jq >/dev/null || missing+=(jq)
if ((${#missing[@]})); then
  say "Missing packages: ${missing[*]}"
  if command -v pacman >/dev/null && ask "Install them with pacman?"; then
    sudo pacman -S --needed "${missing[@]}"
  else
    echo "Please install ${missing[*]} and run this again." >&2
    exit 1
  fi
fi

# ---- the app ----
mkdir -p "$APP" "$BIN" "$DATA/applications" "$DATA/icons/hicolor/256x256/apps"
install -m755 "$SRC/pixel-claude.py" "$SRC/pixel-claude" "$SRC/claude-hook" "$APP/"
ln -sf "$APP/pixel-claude" "$BIN/pixel-claude"
install -m644 "$SRC/assets/icon.png" "$DATA/icons/hicolor/256x256/apps/pixel-claude.png"
cat > "$DATA/applications/pixel-claude.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Pixel Claude
Comment=A tiny orange buddy who hangs out at the bottom of your screen
Exec=$BIN/pixel-claude
Icon=pixel-claude
Terminal=false
Categories=Utility;
EOF
say "Installed to $APP (run it with: pixel-claude)"

# ---- keybinding ----
if [[ -f $HYPR/bindings.lua ]] && grep -q 'o\.bind' "$HYPR/bindings.lua"; then
  bindfile="$HYPR/bindings.lua"
  line="o.bind(\"SUPER + ALT + C\", \"Pixel Claude\", { launch = os.getenv(\"HOME\") .. \"/.local/bin/pixel-claude\" })"
  taken='^[^-]*"SUPER \+ ALT \+ C"'
  comment="--"
elif [[ -f $HYPR/bindings.conf ]]; then
  bindfile="$HYPR/bindings.conf"
  line="bindd = SUPER ALT, C, Pixel Claude, exec, $BIN/pixel-claude"
  taken='^[^#]*SUPER ALT, C,'
  comment="#"
else
  bindfile=""
fi
if [[ -z $bindfile ]]; then
  say "No Hyprland bindings file found; skipping the keybinding."
elif grep -q 'pixel-claude' "$bindfile"; then
  say "Keybinding already set up in $bindfile"
elif grep -Eq "$taken" "$bindfile"; then
  say "Super+Alt+C is already used in $bindfile; skipping. Bind pixel-claude to another key yourself."
elif ask "Add Super+Alt+C to show/hide him (in $bindfile)?"; then
  cp "$bindfile" "$bindfile.bak.pixel-claude"
  printf '\n%s Pixel Claude desktop pet. Pressing again while he is out makes him wave goodbye.\n%s\n' \
    "$comment" "$line" >> "$bindfile"
  if command -v hyprctl >/dev/null; then
    hyprctl reload >/dev/null 2>&1 || true
    errors="$(hyprctl configerrors 2>/dev/null | grep -v '^$' || true)"
    if [[ -n $errors && $errors != *"no errors"* ]]; then
      mv "$bindfile.bak.pixel-claude" "$bindfile"
      hyprctl reload >/dev/null 2>&1 || true
      say "Hyprland didn't accept the binding, so it was removed again:"
      echo "$errors"
    fi
  fi
  [[ -f $bindfile.bak.pixel-claude ]] && say "Added Super+Alt+C (backup: $bindfile.bak.pixel-claude)"
fi

# ---- Claude Code hooks ----
if [[ -d $HOME/.claude ]] || command -v claude >/dev/null; then
  if ask "Let him follow what Claude Code is doing (adds async hooks to $CLAUDE_SETTINGS)?"; then
    [[ -s $CLAUDE_SETTINGS ]] || echo '{}' > "$CLAUDE_SETTINGS"
    cp "$CLAUDE_SETTINGS" "$CLAUDE_SETTINGS.bak.pixel-claude"
    tmp="$(mktemp)"
    jq --arg hook "$APP/claude-hook" '
      .hooks //= {}
      | reduce $ARGS.positional[] as $e (.;
          .hooks[$e] = ((.hooks[$e] // [])
            | map(select(any(.hooks[]?; (.command // "") | test("pixel-claude/claude-hook")) | not))
            + [{hooks: [{type: "command", command: "\"\($hook)\" \($e)", async: true, timeout: 5}]}]))
    ' --args "${EVENTS[@]}" < "$CLAUDE_SETTINGS" > "$tmp"
    mv "$tmp" "$CLAUDE_SETTINGS"
    say "Hooks added (backup: $CLAUDE_SETTINGS.bak.pixel-claude). New Claude Code sessions will pick them up."
  fi
fi

echo
say "All set! Start him from the app launcher, your keybinding, or: pixel-claude"
say "Left-click to pet him, drag to carry him, right-click for a menu."
