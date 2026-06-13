#!/usr/bin/env bash
set -euo pipefail

readonly ARCHIVE_URL="${PCLA_PRETRAINED_URL:-https://huggingface.co/datasets/MasoudJTehrani/PCLA/resolve/main/pretrained.zip}"
readonly ARCHIVE_SHA256="${PCLA_PRETRAINED_SHA256:-0d02c1aaf9ea81b892fef8815c1a8ab617c1906b89ee984ba8163332d659fa93}"
readonly DESTINATION="${1:-PCLA/pcla_agents}"
readonly ARCHIVE="${PCLA_PRETRAINED_ARCHIVE:-/tmp/pcla-pretrained.zip}"

command -v curl >/dev/null
command -v sha256sum >/dev/null
command -v unzip >/dev/null

mkdir -p "${DESTINATION}"

echo "Downloading PCLA pretrained weights to ${ARCHIVE}"
curl -fL --retry 5 --retry-delay 5 --continue-at - \
    --output "${ARCHIVE}" "${ARCHIVE_URL}"

echo "${ARCHIVE_SHA256}  ${ARCHIVE}" | sha256sum --check -

echo "Extracting PCLA pretrained weights to ${DESTINATION}"
unzip -n -q "${ARCHIVE}" -d "${DESTINATION}"

echo "Validating extracted weights"
python3 scripts/validate_pcla_pretrained.py \
    --pcla-root "$(dirname "${DESTINATION}")"

if [[ "${PCLA_KEEP_PRETRAINED_ARCHIVE:-0}" != "1" ]]; then
    rm -f "${ARCHIVE}"
fi
