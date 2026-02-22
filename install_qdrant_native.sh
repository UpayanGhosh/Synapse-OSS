#!/bin/bash
echo "=== Installing Qdrant Native (no Docker overhead) ==="

QDRANT_VERSION="1.13.2"
INSTALL_DIR="$HOME/.openclaw/qdrant"
mkdir -p "$INSTALL_DIR"

# Download ARM64 binary (assuming Mac M-series as per common setup in this repo)
# If it's Intel mac, the URL would be different.
ARCH=$(uname -m)
if [ "$ARCH" == "arm64" ]; then
    URL="https://github.com/qdrant/qdrant/releases/download/v${QDRANT_VERSION}/qdrant-aarch64-apple-darwin.tar.gz"
else
    URL="https://github.com/qdrant/qdrant/releases/download/v${QDRANT_VERSION}/qdrant-x86_64-apple-darwin.tar.gz"
fi

echo "📥 Downloading Qdrant for $ARCH..."
curl -L "$URL" -o /tmp/qdrant.tar.gz

tar -xzf /tmp/qdrant.tar.gz -C "$INSTALL_DIR"
rm /tmp/qdrant.tar.gz

# Create config with memory-optimized settings
cat > "$INSTALL_DIR/config.yaml" << 'CONFIG'
storage:
  storage_path: ./storage
  on_disk_payload: true

  optimizers:
    indexing_threshold: 10000

  hnsw_index:
    on_disk: true
    m: 12
    ef_construct: 80

service:
  host: 127.0.0.1
  http_port: 6333
  grpc_port: 6334

  max_request_size_mb: 32
CONFIG

echo "✅ Qdrant native installed at $INSTALL_DIR"
echo ""
echo "To migrate data from Docker:"
echo "  1. docker cp antigravity_qdrant:/qdrant/storage $INSTALL_DIR/storage"
echo "  2. docker stop antigravity_qdrant"
echo "  3. $INSTALL_DIR/qdrant --config-path $INSTALL_DIR/config.yaml"
