#!/usr/bin/env bash
# Script to regenerate protobuf Python files from .proto sources.
# The .proto sources and the generated Python files now both live in core/proto/.
# Run this from the project root: bash core/proto/generate.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROTO_SRC="$SCRIPT_DIR"
PROTO_OUT="$SCRIPT_DIR"

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

for f in *_pb2.py; do
    sed -i 's/^import base_pb2 as/from core.proto import base_pb2 as/' "$f"
done

for f in *_pb2_grpc.py; do
    sed -i 's/^import base_pb2 as/from core.proto import base_pb2 as/' "$f"
    sed -i 's/^import \(.*_service_pb2\) as/from core.proto import \1 as/' "$f"
done

echo "Done! Protobuf files generated in core/proto/."