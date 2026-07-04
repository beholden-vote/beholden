#!/usr/bin/env bash
# Upload PMTiles archives to R2 (free egress behind Cloudflare custom domain).
# The project passes R2_* everywhere; the aws CLI wants AWS_* — map them here so
# the same credentials work in CI and locally.
set -euo pipefail
V="${1:?vintage}"
export AWS_ACCESS_KEY_ID="${R2_ACCESS_KEY_ID:?}"
export AWS_SECRET_ACCESS_KEY="${R2_SECRET_ACCESS_KEY:?}"
export AWS_DEFAULT_REGION="auto"
for f in us-*-$V.pmtiles; do
  aws s3 cp "$f" "s3://beholden/tiles/$f" \
    --endpoint-url "$R2_ENDPOINT" --checksum-algorithm CRC32
done
