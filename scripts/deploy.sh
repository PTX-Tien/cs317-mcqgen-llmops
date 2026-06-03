#!/bin/bash
# scripts/deploy.sh — Deploy MCQGen lên production (chạy 1 lần hoặc khi cần cập nhật)
#
# Làm gì:
#   1. Build Next.js production (thay thế dev mode)
#   2. Cập nhật Nginx config (proxy /api/ → FastAPI, / → Next.js)
#   3. Khởi động lại Next.js ở production mode
#   4. Reload Nginx
#
# Cách dùng:
#   bash scripts/deploy.sh

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_DIR=$PROJECT/logs
WEBAPP=$PROJECT/webapp
NGINX_CONF=$PROJECT/nginx/mcqgen.conf
WEBAPP_PORT=${WEBAPP_PORT:-8081}

source /mmlab_students/storageStudents/nguyenvd/anaconda3/etc/profile.d/conda.sh
conda activate mcqgen_v2 2>/dev/null

mkdir -p $LOG_DIR

log() { echo "[$(date '+%H:%M:%S')] $*"; }

log "════════════════════════════════════════"
log "🚀 MCQGen Production Deploy"
log "════════════════════════════════════════"

# ── STEP 1: Build Next.js ─────────────────────────────────────────────────────
log "[1/4] Building Next.js for production..."
log "   (quá trình này mất 2-5 phút)"

cd $WEBAPP

# Dừng Next.js dev đang chạy
pkill -f "next.*--port $WEBAPP_PORT" 2>/dev/null && log "   Stopped dev server" || true
pkill -f "next.*dev" 2>/dev/null && sleep 1 || true
pkill -f "next-server" 2>/dev/null && sleep 1 || true

npm run build
log "✅ Next.js build done"

# ── STEP 2: Cập nhật Nginx config ─────────────────────────────────────────────
log "[2/4] Applying Nginx config..."

# Update upstream port trong nginx config để khớp với WEBAPP_PORT
sed "s/server 127.0.0.1:3000/server 127.0.0.1:$WEBAPP_PORT/" $NGINX_CONF > /tmp/mcqgen_nginx.conf

sudo bash -c "
    # Tắt config cũ nếu tồn tại (service.conf đang proxy port 80 → 8081)
    if [ -f /etc/nginx/sites-enabled/service.conf ]; then
        mv /etc/nginx/sites-enabled/service.conf /etc/nginx/sites-enabled/service.conf.bak
        echo 'Backed up service.conf'
    fi
    cp /tmp/mcqgen_nginx.conf /etc/nginx/sites-enabled/mcqgen.conf
    echo 'Nginx config applied'
"

# Test nginx config
sudo nginx -t
log "✅ Nginx config OK"

# ── STEP 3: Start Next.js production ──────────────────────────────────────────
log "[3/4] Starting Next.js production..."
cd $PROJECT
setsid bash -lc "cd $WEBAPP && PORT=$WEBAPP_PORT npm start" \
    > $LOG_DIR/nextjs.log 2>&1 < /dev/null &
NEXT_PID=$!
log "   PID=$NEXT_PID | port=$WEBAPP_PORT | log=$LOG_DIR/nextjs.log"

# Chờ Next.js khởi động
log "   Waiting for Next.js..."
for i in $(seq 1 20); do
    if curl -s http://localhost:$WEBAPP_PORT >/dev/null 2>&1; then
        log "✅ Next.js ready on port $WEBAPP_PORT"
        break
    fi
    sleep 2
done

# ── STEP 4: Reload Nginx ───────────────────────────────────────────────────────
log "[4/4] Reloading Nginx..."
sudo systemctl reload nginx 2>/dev/null || sudo nginx -s reload
log "✅ Nginx reloaded"

# ── Final summary ─────────────────────────────────────────────────────────────
IP=$(hostname -I | awk '{print $1}')

log "════════════════════════════════════════"
log "✅ Deployment complete!"
echo ""
echo "  🌐 App URL:    http://$IP"
echo "  🔧 API docs:   http://$IP/api/docs"
echo "  📡 API direct: http://$IP:8080/docs"
echo ""
echo "  Routing qua Nginx port 80:"
echo "    /api/*   → FastAPI  :8080"
echo "    /api/ws/ → FastAPI  :8080 (WebSocket)"
echo "    /        → Next.js  :$WEBAPP_PORT"
echo ""
echo "  Share link với người dùng: http://$IP"
log "════════════════════════════════════════"
