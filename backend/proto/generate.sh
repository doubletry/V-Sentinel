#!/usr/bin/env bash
# Script to regenerate protobuf Python files from .proto sources
# Run this from the backend/proto directory

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "Generating protobuf Python files..."

python -m grpc_tools.protoc \
    -I. \
    --python_out=. \
    --grpc_python_out=. \
    base.proto \
    detection_service.proto \
    classification_service.proto \
    action_service.proto \
    ocr_service.proto \
    upload_service.proto

echo "Fixing imports in generated files..."
# Fix relative imports in generated files
for f in *_pb2_grpc.py; do
    sed -i 's/^import \(.*\)_pb2 as/from backend.proto import \1_pb2 as/' "$f" 2>/dev/null || true
done

echo "Done! Protobuf files regenerated."
