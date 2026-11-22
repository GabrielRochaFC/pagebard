#!/usr/bin/env bash
# Builds LeitorPDF.flatpak, a single file that installs the application.
# Needs flatpak and flatpak-builder; everything else is downloaded from Flathub.
set -euo pipefail
cd "$(dirname "$0")"

APP_ID=io.github.leitorpdf.LeitorPDF
FLATHUB=https://dl.flathub.org/repo/flathub.flatpakrepo
OUTPUT=../../LeitorPDF.flatpak

flatpak remote-add --user --if-not-exists flathub "$FLATHUB"
flatpak-builder --user --force-clean --install-deps-from=flathub \
    --repo=repo build-dir "$APP_ID.json"
# --runtime-repo lets the installer fetch the runtime the application needs.
flatpak build-bundle --runtime-repo="$FLATHUB" repo "$OUTPUT" "$APP_ID"

echo "Pronto: $(realpath "$OUTPUT")"
