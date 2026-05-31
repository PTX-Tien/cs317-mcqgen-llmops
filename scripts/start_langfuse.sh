#!/bin/bash
set -euo pipefail

PROJECT=/mmlab_students/storageStudents/nguyenvd/trangbtt/cs317-mcqgen-llmops
LANGFUSE_DIR="$PROJECT/monitoring/langfuse"
ENV_FILE="$LANGFUSE_DIR/.env"
ENV_EXAMPLE="$LANGFUSE_DIR/.env.example"

random_hex() {
    local bytes=$1
    if command -v openssl >/dev/null 2>&1; then
        openssl rand -hex "$bytes"
    else
        python -c "import secrets; print(secrets.token_hex($bytes))"
    fi
}

set_env_value() {
    local key=$1
    local value=$2
    sed -i "s|^${key}=.*|${key}=${value}|" "$ENV_FILE"
}

ensure_env_file() {
    if [ -f "$ENV_FILE" ]; then
        return 0
    fi

    if [ ! -f "$ENV_EXAMPLE" ]; then
        echo "Missing $ENV_EXAMPLE"
        exit 1
    fi

    cp "$ENV_EXAMPLE" "$ENV_FILE"
    chmod 600 "$ENV_FILE"

    local langfuse_port=${LANGFUSE_PORT:-3003}
    set_env_value LANGFUSE_PORT "$langfuse_port"
    set_env_value NEXTAUTH_URL "http://localhost:${langfuse_port}"
    set_env_value NEXTAUTH_SECRET "$(random_hex 32)"
    set_env_value SALT "$(random_hex 16)"
    set_env_value ENCRYPTION_KEY "$(random_hex 32)"
    set_env_value POSTGRES_PASSWORD "$(random_hex 24)"
    set_env_value CLICKHOUSE_PASSWORD "$(random_hex 24)"
    set_env_value MINIO_ROOT_PASSWORD "$(random_hex 24)"

    echo "Created $ENV_FILE with local generated secrets."
}

ensure_env_file

if [ "${1:-}" = "--init-only" ]; then
    PORT=$(sed -n 's/^LANGFUSE_PORT=//p' "$ENV_FILE" | tail -n 1)
    echo "LangFuse env ready: $ENV_FILE"
    echo "LangFuse URL: http://localhost:${PORT:-3003}"
    exit 0
fi

cd "$LANGFUSE_DIR"
docker compose --env-file "$ENV_FILE" up -d

PORT=$(sed -n 's/^LANGFUSE_PORT=//p' "$ENV_FILE" | tail -n 1)
echo "LangFuse: http://localhost:${PORT:-3003}"
