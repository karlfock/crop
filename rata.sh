#!/usr/bin/env bash
# rata.sh - rätar ut teckningar/vykort i foton.
# Lägg rata.sh och rata.py i samma mapp. Första körningen skapar en venv
# bredvid scripten och installerar det som behövs.
#
#   ./rata.sh                     # alla bilder i aktuell mapp (jpg, jpeg, png, heic)
#   ./rata.sh foto.jpg --edit     # vidare argument skickas till rata.py
#   ./rata.sh --pdf               # alla bilder i aktuell mapp + A4-PDF:er
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$SCRIPT_DIR/.venv"
DEPS=(opencv-python pillow numpy pillow-heif)

if [[ ! -x "$VENV/bin/python" ]]; then
  command -v python3 >/dev/null || { echo "python3 saknas (installera med: xcode-select --install)"; exit 1; }
  echo "Skapar venv i $VENV ..."
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install --quiet --upgrade pip
  "$VENV/bin/pip" install --quiet "${DEPS[@]}"
  echo "Klart."
fi

# Finns inga bildfiler bland argumenten: ta alla bilder i aktuell mapp
# (utom de som scriptet själv har skapat).
has_file=false
for a in "$@"; do [[ "$a" != -* && -f "$a" ]] && has_file=true; done

if ! $has_file; then
  shopt -s nullglob nocaseglob
  files=()
  for f in *.jpg *.jpeg *.png *.heic; do
    [[ "$f" == *_rak.jpg || "$f" == *_hörn.jpg ]] && continue
    files+=("$f")
  done
  shopt -u nocaseglob
  if (( ${#files[@]} == 0 )); then
    echo "Inga bilder i $(pwd)"; exit 1
  fi
  set -- "${files[@]}" "$@"
fi

exec "$VENV/bin/python" "$SCRIPT_DIR/rata.py" "$@"
