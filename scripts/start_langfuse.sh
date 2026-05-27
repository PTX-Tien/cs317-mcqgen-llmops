#!/bin/bash
set -euo pipefail

PROJECT=/mmlab_students/storageStudents/nguyenvd/Thanhld/cs317-mcqgen-llmops
LANGFUSE_DIR="$PROJECT/monitoring/langfuse"
ENV_FILE="$LANGFUSE_DIR/.env"

if [ ! -f "$ENV_FILE" ]; then
    echo "Missing $ENV_FILE"
    echo "Create it from monitoring/langfuse/.env.example and replace all secrets."
    exit 1
fi

cd "$LANGFUSE_DIR"
docker compose --env-file "$ENV_FILE" up -d

PORT=$(sed -n 's/^LANGFUSE_PORT=//p' "$ENV_FILE" | tail -n 1)
echo "LangFuse: http://localhost:${PORT:-3000}"
