#!/usr/bin/env bash
# Runs the dockerized cardglow tool against files in the current
# directory, pulling the published image on first use.
#
#   ./cardglow logo.png
#   ./cardglow logo.svg -o card.png
#   ./cardglow logo.png --gradient-angle 135 --glow "#ff3355"
#
set -euo pipefail

IMAGE="${CARDGLOW_IMAGE:-ghcr.io/alan-null/cardglow:latest}"

docker run --rm \
    -v "$PWD":/data \
    -u "$(id -u)":"$(id -g)" \
    "$IMAGE" "$@"
