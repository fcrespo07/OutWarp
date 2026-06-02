#!/usr/bin/env bash
# Build the outwarp-server image on the Pi and import it into k3s containerd.
#
# Run this script FROM THE REPO ROOT on the Pi:
#   chmod +x deploy/build-pi.sh
#   ./deploy/build-pi.sh            # → outwarp-server:latest
#   ./deploy/build-pi.sh v0.5.5     # → outwarp-server:v0.5.5
#
# Requirements on the Pi: docker (just for building — k3s uses its own containerd).
#   sudo apt-get install -y docker.io
#   sudo usermod -aG docker $USER   # then log out + in
set -euo pipefail

IMAGE_NAME="outwarp-server"
TAG="${1:-latest}"
FULL_REF="${IMAGE_NAME}:${TAG}"

echo "==> Building ${FULL_REF} (context: server/)"
docker build -t "${FULL_REF}" server/

echo "==> Importing into k3s containerd..."
docker save "${FULL_REF}" | sudo k3s ctr images import -

echo ""
echo "Image imported: ${FULL_REF}"
echo ""
echo "Next steps:"
echo "  1. Edit deploy/kubernetes/configmap.yaml — set OUTWARP_ENDPOINT to your WAN IP"
echo "  2. kubectl apply -k deploy/kubernetes/"
echo "  3. Watch startup:  kubectl -n outwarp logs -f deployment/outwarp-server -c outwarp-init"
echo "                     kubectl -n outwarp logs -f deployment/outwarp-server"
echo "  4. Add a client:   kubectl -n outwarp exec deployment/outwarp-server -- \\"
echo "                       outwarp-server --config-dir /data add-client laptop"
echo "     Copy the .owcfg: kubectl -n outwarp cp \\"
echo "                       \$(kubectl -n outwarp get pod -l app=outwarp-server -o name | head -1 | cut -d/ -f2):/data/laptop.owcfg ./laptop.owcfg"
