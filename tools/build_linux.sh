#!/usr/bin/env bash
# ===========================================================================
#  Build the Linux release: dist/HeightShift-Linux-x86_64.AppImage
#  (+ its .zsync, for AppImage update tools).
#
#  GitHub Actions runs this for every release (.github/workflows/release.yml)
#  and attaches both files to it. It runs the same on any x86_64 Linux with
#  Python 3.10+ (python3-venv), git and curl.
#
#      bash tools/build_linux.sh [v2.0.27]
#
#  1. A venv with the pinned dependencies (requirements.txt) + PyInstaller.
#  2. The version baked in (tools/bake_version.py: the tag, or version.py).
#  3. PyInstaller --onedir: the AppImage is already the single file, and a
#     onedir inside it starts at once instead of unpacking to /tmp.
#  4. The AppDir, packed by appimagetool with GitHub update information.
#  OscGoesPurrr's tools/build_linux.sh, without its toy engine.
# ===========================================================================
set -euo pipefail
cd "$(dirname "$0")/.."

APP=HeightShift
ARCH=x86_64
REPO_SLUG="Blise518B|HeightShiftOSC"
OUT_NAME="$APP-Linux-$ARCH.AppImage"
WORK=_linux_build
PY=${PYTHON:-python3}
TAG=${1:-}
ROOT=$(pwd)

say() { printf '\n=== %s ===\n' "$*"; }
die() { printf '[ERROR] %s\n' "$*" >&2; exit 1; }

[ "$(uname -m)" = "$ARCH" ] || die "this builds the $ARCH AppImage; this machine is $(uname -m)"
mkdir -p "$WORK" dist

# ---- 1. venv ---------------------------------------------------------------
say "Python dependencies"
VENV="$WORK/venv"
[ -x "$VENV/bin/python" ] || "$PY" -m venv "$VENV"
VPY="$VENV/bin/python"
"$VPY" -m pip install -q --upgrade pip
"$VPY" -m pip install -q -r requirements.txt pyinstaller

# ---- 2. version ------------------------------------------------------------
rm -f _version_baked.py
trap 'rm -f _version_baked.py' EXIT
"$VPY" tools/bake_version.py ${TAG:+"$TAG"}

# ---- 3. PyInstaller --------------------------------------------------------
say "PyInstaller"
rm -rf "$WORK/pyi-dist"
# readline / curses would pull in GPL readline; the app has no console.
"$VPY" -m PyInstaller --noconfirm --log-level WARN \
    --onedir --windowed --name "$APP" \
    --distpath "$WORK/pyi-dist" --workpath "$WORK/pyi-work" --specpath "$WORK" \
    --exclude-module readline --exclude-module curses --exclude-module _curses \
    --add-data "$ROOT/OSC_Scale.ico:." \
    --add-data "$ROOT/fonts:fonts" \
    --add-data "$ROOT/assets:assets" \
    main.py

# ---- 4. AppImage -----------------------------------------------------------
say "AppImage"
APPDIR="$WORK/AppDir"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/lib"
cp -a "$WORK/pyi-dist/$APP" "$APPDIR/usr/lib/$APP"
INTERNAL="$APPDIR/usr/lib/$APP/_internal"
# Libraries every desktop has, where the system's own (newer) copy must win:
# GPU drivers need the system's libstdc++, an older OpenSSL can refuse the
# system's crypto config (and then the update check fails), an older
# fontconfig misreads a newer system's fonts.
for lib in libstdc++.so.6 libgcc_s.so.1 libssl.so.3 libcrypto.so.3 \
           libfontconfig.so.1 libfreetype.so.6 libexpat.so.1; do
    rm -f "$INTERNAL/$lib"
done
# Qt's GTK3 theme would load the system's GTK next to our older GLib, a
# classic AppImage crash on GNOME. The app draws its own theme anyway.
rm -f "$INTERNAL/PySide6/Qt/plugins/platformthemes/libqgtk3.so"

cat > "$APPDIR/AppRun" <<EOF
#!/bin/sh
HERE="\$(dirname "\$(readlink -f "\$0")")"
exec "\$HERE/usr/lib/$APP/$APP" "\$@"
EOF
chmod 755 "$APPDIR/AppRun"

cat > "$APPDIR/$APP.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=$APP
Comment=Change your height in VRChat, smoothly
Exec=$APP
Icon=$APP
Categories=Utility;
Terminal=false
EOF
cp docs/site/icon.png "$APPDIR/$APP.png"
ln -sf "$APP.png" "$APPDIR/.DirIcon"

TOOL="$WORK/appimagetool-$ARCH.AppImage"
if [ ! -x "$TOOL" ]; then
    curl -fsSL -o "$TOOL" "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-$ARCH.AppImage"
    chmod 755 "$TOOL"
fi
rm -f "dist/$OUT_NAME" "dist/$OUT_NAME.zsync" "$OUT_NAME.zsync"
# Extract-and-run: works without FUSE (containers, CI runners).
APPIMAGE_EXTRACT_AND_RUN=1 ARCH=$ARCH "$TOOL" --no-appstream \
    -u "gh-releases-zsync|$REPO_SLUG|latest|$OUT_NAME.zsync" \
    "$APPDIR" "dist/$OUT_NAME"
[ -f "$OUT_NAME.zsync" ] && mv "$OUT_NAME.zsync" dist/
chmod 755 "dist/$OUT_NAME"
say "Built dist/$OUT_NAME"
ls -la dist/
