#!/usr/bin/env bash
# Script to regenerate protobuf Python files from .proto sources.
# The .proto sources live in backend/proto/, but the generated Python
# files are placed in core/proto/ (the canonical location).
# Run this from the project root: bash backend/proto/generate.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PROTO_SRC="$SCRIPT_DIR"
PROTO_OUT="$PROJECT_ROOT/core/proto"

echo "Proto source: $PROTO_SRC"
echo "Output dir:   $PROTO_OUT"

echo "Generating protobuf Python files..."
python -m grpc_tools.protoc \
    -I"$PROTO_SRC" \
    --python_out="$PROTO_OUT" \
    --grpc_python_out="$PROTO_OUT" \
    "$PROTO_SRC/base.proto" \
    "$PROTO_SRC/detection_service.proto" \
    "$PROTO_SRC/classification_service.proto" \
    "$PROTO_SRC/action_service.proto" \
    "$PROTO_SRC/ocr_service.proto" \
    "$PROTO_SRC/upload_service.proto"

echo "Fixing imports in generated files to use core.proto package..."
cd "$PROTO_OUT"

# Fix bare imports in _pb2.py files (e.g. 'import base_pb2 as ...')
for f in *_pb2.py; do
    sed -i 's/^import base_pb2 as/from core.proto import base_pb2 as/' "$f"
done

# Fix bare imports in _pb2_grpc.py files
for f in *_pb2_grpc.py; do
    sed -i 's/^import base_pb2 as/from core.proto import base_pb2 as/' "$f"
    sed -i 's/^import \(.*_service_pb2\) as/from core.proto import \1 as/' "$f"
done

echo "Done! Protobuf files generated in core/proto/."
