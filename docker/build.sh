#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Multi-arch image build for Slipstream (linux/amd64 + linux/arm64).
#
#   docker/build.sh                          # build locally, amd64 only
#   docker/build.sh --push ghcr.io/you/slipstream
#   PLATFORMS=linux/arm64 docker/build.sh    # single non-native arch
#
# Cross-architecture builds go through QEMU emulation, which is slow: the
# frontend stage in particular can take several minutes under emulation. A
# native runner per architecture is faster if you have one (see the Docker
# matrix in .github/workflows/).
# ---------------------------------------------------------------------------
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

VERSION="$(grep -m1 '^version' backend/pyproject.toml | cut -d'"' -f2)"
# Whether the caller pinned PLATFORMS, so --push can widen the default without
# overriding a deliberate choice.
PLATFORMS_EXPLICIT="${PLATFORMS:+1}"
PLATFORMS="${PLATFORMS:-linux/amd64}"
PUSH=0
IMAGE="slipstream"

while [ $# -gt 0 ]; do
  case "$1" in
    --push)
      PUSH=1
      shift
      IMAGE="${1:?--push requires an image reference, e.g. ghcr.io/you/slipstream}"
      # A pushed image should be a manifest list covering both architectures.
      if [ -z "$PLATFORMS_EXPLICIT" ]; then
        PLATFORMS="linux/amd64,linux/arm64"
      fi
      shift
      ;;
    -h|--help)
      sed -n '2,14p' "${BASH_SOURCE[0]}"
      exit 0
      ;;
    *)
      echo "unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

if ! docker buildx version >/dev/null 2>&1; then
  echo "docker buildx is required for multi-arch builds." >&2
  echo "Install the buildx plugin or use: docker build -t slipstream:${VERSION} ." >&2
  exit 1
fi

# A dedicated builder keeps the multi-arch cache separate from the default
# one, which cannot produce manifest lists.
if ! docker buildx inspect slipstream-builder >/dev/null 2>&1; then
  echo "==> creating buildx builder 'slipstream-builder'"
  docker buildx create --name slipstream-builder --driver docker-container --bootstrap
fi

ARGS=(
  buildx build
  --builder slipstream-builder
  --platform "$PLATFORMS"
  --file Dockerfile
  --tag "${IMAGE}:${VERSION}"
  --tag "${IMAGE}:latest"
  --build-arg "BUILDKIT_INLINE_CACHE=1"
)

if [ "$PUSH" -eq 1 ]; then
  ARGS+=(--push)
else
  case "$PLATFORMS" in
    *,*)
      # --load cannot import a manifest list into the local daemon, so a
      # multi-arch build without --push can only stay in the build cache.
      echo "==> multi-arch build without --push: result stays in the build cache"
      ;;
    *)
      ARGS+=(--load)
      ;;
  esac
fi

echo "==> building ${IMAGE}:${VERSION} for ${PLATFORMS}"
docker "${ARGS[@]}" .

echo "==> done"
if [ "$PUSH" -eq 0 ] && [[ "$PLATFORMS" != *,* ]]; then
  echo "    run it with: docker run --rm -p 8000:8000 -e SECRET_KEY=dev ${IMAGE}:${VERSION}"
fi
