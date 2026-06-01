#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT="$(cd "$SCRIPT_DIR/.." && pwd)"
LANGFUSE_DIR="$PROJECT/monitoring/langfuse"
ENV_FILE="$LANGFUSE_DIR/.env"
ENV_EXAMPLE="$LANGFUSE_DIR/.env.example"
RESET_DATA=0

for arg in "$@"; do
    case "$arg" in
        --init-only)
            INIT_ONLY=1
            ;;
        --reset-data)
            RESET_DATA=1
            ;;
        -h|--help)
            cat <<EOF
Usage: bash scripts/start_langfuse.sh [--init-only] [--reset-data]

Options:
  --init-only   Create or repair monitoring/langfuse/.env only.
  --reset-data  Recreate LangFuse Docker volumes. This deletes local LangFuse users/traces.
EOF
            exit 0
            ;;
        *)
            echo "Unknown option: $arg" >&2
            exit 2
            ;;
    esac
done
INIT_ONLY=${INIT_ONLY:-0}

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
    if grep -q "^${key}=" "$ENV_FILE"; then
        sed -i "s|^${key}=.*|${key}=${value}|" "$ENV_FILE"
    else
        printf '%s=%s\n' "$key" "$value" >> "$ENV_FILE"
    fi
}

get_env_value() {
    local key=$1
    sed -n "s/^${key}=//p" "$ENV_FILE" | tail -n 1
}

sql_quote_identifier() {
    printf '%s' "$1" | sed 's/"/""/g'
}

sql_quote_literal() {
    printf '%s' "$1" | sed "s/'/''/g"
}

is_hex_len() {
    local value=$1
    local len=$2
    [ "${#value}" -eq "$len" ] && [[ "$value" =~ ^[0-9a-fA-F]+$ ]]
}

ensure_hex_secret() {
    local key=$1
    local bytes=$2
    local current
    current=$(get_env_value "$key")
    if ! is_hex_len "$current" "$((bytes * 2))"; then
        set_env_value "$key" "$(random_hex "$bytes")"
        echo "Updated $key in $ENV_FILE"
    fi
}

ensure_non_placeholder_secret() {
    local key=$1
    local bytes=$2
    local current
    current=$(get_env_value "$key")
    if [ -z "$current" ] || [[ "$current" == replace-with-* ]]; then
        set_env_value "$key" "$(random_hex "$bytes")"
        echo "Updated $key in $ENV_FILE"
    fi
}

langfuse_url() {
    local port=$1
    if [ -n "${LANGFUSE_PUBLIC_URL:-}" ]; then
        echo "$LANGFUSE_PUBLIC_URL"
    else
        local host_ip
        host_ip=$(hostname -I 2>/dev/null | awk '{print $1}')
        if [ -n "$host_ip" ]; then
            echo "http://${host_ip}:${port}"
        else
            echo "http://localhost:${port}"
        fi
    fi
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

    local langfuse_port=${LANGFUSE_PORT:-8083}
    set_env_value LANGFUSE_PORT "$langfuse_port"
    set_env_value NEXTAUTH_URL "$(langfuse_url "$langfuse_port")"
    set_env_value NEXTAUTH_SECRET "$(random_hex 32)"
    set_env_value SALT "$(random_hex 16)"
    set_env_value ENCRYPTION_KEY "$(random_hex 32)"
    set_env_value POSTGRES_PASSWORD "$(random_hex 24)"
    set_env_value CLICKHOUSE_PASSWORD "$(random_hex 24)"
    set_env_value MINIO_ROOT_PASSWORD "$(random_hex 24)"

    echo "Created $ENV_FILE with local generated secrets."
}

ensure_env_file
LANGFUSE_PORT_VALUE=${LANGFUSE_PORT:-$(get_env_value LANGFUSE_PORT)}
LANGFUSE_PORT_VALUE=${LANGFUSE_PORT_VALUE:-8083}
set_env_value LANGFUSE_PORT "$LANGFUSE_PORT_VALUE"
set_env_value NEXTAUTH_URL "$(langfuse_url "$LANGFUSE_PORT_VALUE")"
set_env_value AUTH_DISABLE_SIGNUP "false"
set_env_value AUTH_DISABLE_USERNAME_PASSWORD "false"
set_env_value NEXT_PUBLIC_SIGN_UP_DISABLED "false"
ensure_hex_secret NEXTAUTH_SECRET 32
ensure_hex_secret SALT 16
ensure_hex_secret ENCRYPTION_KEY 32
ensure_non_placeholder_secret POSTGRES_PASSWORD 24
ensure_non_placeholder_secret CLICKHOUSE_PASSWORD 24
ensure_non_placeholder_secret MINIO_ROOT_PASSWORD 24

if [ "$INIT_ONLY" = "1" ]; then
    echo "LangFuse env ready: $ENV_FILE"
    echo "LangFuse URL: $(get_env_value NEXTAUTH_URL)"
    exit 0
fi

cd "$LANGFUSE_DIR"

if [ "$RESET_DATA" = "1" ]; then
    echo "Resetting local LangFuse containers and volumes..."
    docker compose --env-file "$ENV_FILE" down -v --remove-orphans
fi

docker compose --env-file "$ENV_FILE" up -d postgres clickhouse redis minio

POSTGRES_USER_SQL=$(sql_quote_identifier "$(get_env_value POSTGRES_USER)")
POSTGRES_PASSWORD_SQL=$(sql_quote_literal "$(get_env_value POSTGRES_PASSWORD)")
if docker compose --env-file "$ENV_FILE" exec -T -u postgres postgres \
    psql -U "$(get_env_value POSTGRES_USER)" -d "$(get_env_value POSTGRES_DB)" \
    -v ON_ERROR_STOP=1 \
    -c "ALTER USER \"${POSTGRES_USER_SQL}\" WITH PASSWORD '${POSTGRES_PASSWORD_SQL}';" >/dev/null 2>&1; then
    echo "Postgres password is aligned with $ENV_FILE"
else
    echo "Warning: could not align existing Postgres password. If LangFuse keeps restarting with P1000, run:"
    echo "  bash scripts/start_langfuse.sh --reset-data"
fi

docker compose --env-file "$ENV_FILE" up -d --remove-orphans --force-recreate langfuse-worker langfuse-web minio-create-bucket

echo "LangFuse: $(get_env_value NEXTAUTH_URL)"
