#!/usr/bin/env bash
# Promote only the two native, smoke-tested registry objects. No build runs here.
set -euo pipefail
: "${IMAGE:?image repository required}" "${AMD64_DIGEST:?amd64 digest required}" "${ARM64_DIGEST:?arm64 digest required}" "${IMAGE_METADATA:?metadata JSON required}"

for digest in "$AMD64_DIGEST" "$ARM64_DIGEST"; do
  [[ "$digest" =~ ^sha256:[a-f0-9]{64}$ ]] || { echo 'Invalid candidate digest' >&2; exit 1; }
done
test "$AMD64_DIGEST" != "$ARM64_DIGEST"

tags=()
tag_lines="$(jq -er '.tags | if type == "array" and length > 0 and all(.[]; type == "string") then .[] else error("Missing image tags") end' <<< "$IMAGE_METADATA")"
while IFS= read -r tag; do
  [[ "$tag" == "$IMAGE":* ]] || { echo 'Unexpected image tag' >&2; exit 1; }
  tags+=(--tag "$tag")
done <<< "$tag_lines"
test "${#tags[@]}" -gt 0

scratch="$(mktemp -d)"
trap 'rm -rf "$scratch"' EXIT
refs=("$IMAGE@$AMD64_DIGEST" "$IMAGE@$ARM64_DIGEST")
for architecture in amd64 arm64; do
  if [ "$architecture" = amd64 ]; then digest="$AMD64_DIGEST"; else digest="$ARM64_DIGEST"; fi
  docker buildx imagetools inspect --raw "$IMAGE@$digest" > "$scratch/$architecture.json"
  # Keep the native image and its provenance/SBOM descriptors together.
  jq -e --arg arch "$architecture" '
    ([.manifests[] | select(.platform.os == "linux" and .platform.architecture == $arch)] | length) == 1
    and ([.manifests[] | select(.platform.os != "unknown")] | length) == 1
    and ([.manifests[] | select(.annotations["vnd.docker.reference.type"] == "attestation-manifest")] | length) > 0
  ' "$scratch/$architecture.json" > /dev/null
done

# Dry-run first: a missing architecture or dropped attestation must not move tags.
docker buildx imagetools create --dry-run "${refs[@]}" > "$scratch/merged.json"
jq -e -s '
  (.[0].manifests + .[1].manifests | sort_by(.digest)) == (.[2].manifests | sort_by(.digest))
' "$scratch/amd64.json" "$scratch/arm64.json" "$scratch/merged.json" > /dev/null
docker buildx imagetools create "${tags[@]}" "${refs[@]}"
