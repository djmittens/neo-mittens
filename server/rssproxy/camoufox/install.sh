#!/usr/bin/env bash
#
# Build and install the Camoufox render sidecar as a rootless-podman systemd user service.
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_NAME="camoufox"
SERVICE_FILE="${SCRIPT_DIR}/${SERVICE_NAME}.service"
SYSTEMD_USER_DIR="${HOME}/.config/systemd/user"
IMAGE="localhost/rss-camoufox:latest"

if ! command -v podman &>/dev/null; then
    echo "Error: podman is required."
    exit 1
fi

echo "Building Camoufox image (downloads ~700MB Camoufox Firefox on first build)..."
podman build -t "${IMAGE}" -f "${SCRIPT_DIR}/Containerfile" "${SCRIPT_DIR}"
echo "✓ Image built: ${IMAGE}"

mkdir -p "${SYSTEMD_USER_DIR}"
cp "${SERVICE_FILE}" "${SYSTEMD_USER_DIR}/"
systemctl --user daemon-reload
systemctl --user enable "${SERVICE_NAME}.service"
loginctl enable-linger "${USER}"
systemctl --user restart "${SERVICE_NAME}.service"
echo "Waiting for sidecar to come up (Camoufox boots Firefox; ~10-20s)..."
ok=0
for _ in $(seq 1 30); do
    if curl -fsS -o /dev/null http://127.0.0.1:7072/healthz; then ok=1; break; fi
    sleep 2
done
if [ "${ok}" = "1" ]; then
    echo "✓ Camoufox sidecar healthy at http://127.0.0.1:7072"
else
    echo "✗ Sidecar not healthy after 60s. Logs:"
    journalctl --user -u "${SERVICE_NAME}" -n 20 --no-pager
    exit 1
fi

echo ""
echo "Done. Point the proxy at it with RSSPROXY_RENDER_URL=http://127.0.0.1:7072/render"
