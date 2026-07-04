#!/usr/bin/env bash
# Upload PMTiles archives to R2 (free egress behind Cloudflare custom domain).
set -euo pipefail
V="${1:?vintage}"
for f in us-*-$V.pmtiles; do
  aws s3 cp "$f" "s3://beholden/tiles/$f" \
    --endpoint-url "$R2_ENDPOINT" --checksum-algorithm CRC32
done
