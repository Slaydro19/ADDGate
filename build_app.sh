#!/usr/bin/env bash
# Builds ADDGate.app and puts it in your Applications folder. Run on a Mac:  ./build_app.sh
# Takes a few minutes the first time. Re-run after every update to rebuild the app.
set -e
cd "$(dirname "$0")"

if [ "$(uname)" != "Darwin" ]; then
  echo "The desktop app is built on a Mac. Elsewhere, use ./start.sh."; exit 1
fi

if [ ! -d .venv ]; then
  echo "Setting up Python environment..."
  python3 -m venv .venv
fi
echo "Installing build tools (first time takes a minute)..."
.venv/bin/pip install -q -r backend/requirements.txt -r desktop/requirements.txt

if [ ! -f backend/static/index.html ]; then
  echo "Building the UI (needs Node)..."
  (cd frontend && npm install && npm run build)
fi

echo "Packaging ADDGate.app..."
rm -rf build/desktop dist/ADDGate dist/ADDGate.app
.venv/bin/pyinstaller --noconfirm --clean --log-level WARN \
  --workpath build/desktop --distpath dist desktop/ADDGate.spec

# Install: /Applications if you can write there, otherwise ~/Applications
DEST=/Applications
[ -w "$DEST" ] || { DEST="$HOME/Applications"; mkdir -p "$DEST"; }
if pgrep -f "ADDGate.app/Contents/MacOS/ADDGate" >/dev/null; then
  echo "Quitting the running ADDGate app first..."
  pkill -f "ADDGate.app/Contents/MacOS/ADDGate" || true; sleep 2
fi
rm -rf "$DEST/ADDGate.app"
cp -R dist/ADDGate.app "$DEST/"

echo
echo "Done: $DEST/ADDGate.app"
echo "Open it from Launchpad or Spotlight (Cmd+Space, type ADDGate). Drag it to the Dock to keep it there."
open "$DEST/ADDGate.app"
