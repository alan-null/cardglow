#!/usr/bin/env bash
# Runs the dockerized cardglow tool against files in the current
# directory, pulling the published image on first use.
#
#   ./cardglow logo.png
#   ./cardglow logo.svg -o card.png
#   ./cardglow /home/logo.png -o /tmp/card.png
#   ./cardglow logo.png --gradient-angle 135 --glow "#ff3355"
#
# Any argument that is an absolute path also gets its containing directory
# bind-mounted at the same path inside the container, so absolute paths
# (input or -o/--output) work exactly like relative ones.
set -euo pipefail

IMAGE="${CARDGLOW_IMAGE:-ghcr.io/alan-null/cardglow:latest}"

mounts=(-v "$PWD":/data)
args=()

for arg in "$@"; do
    if [[ "$arg" == /* && -d "$(dirname -- "$arg")" ]]; then
        dir="$(cd -- "$(dirname -- "$arg")" && pwd)"
        mounts+=(-v "$dir":"$dir")
    fi
    args+=("$arg")
done

docker run --rm \
    "${mounts[@]}" \
    -u "$(id -u)":"$(id -g)" \
    "$IMAGE" "${args[@]}"
