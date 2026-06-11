# Nginx Reverse Proxy Architecture — MCQGen

---

## 概述 — Tổng quan

MCQGen sử dụng **Nginx làm reverse proxy** để:
1. **Route requests** đến các backend service (FastAPI API, Next.js Frontend)
2. **Thực hiện URL rewriting** (strip `/api/` prefix)
3. **Quản lý WebSocket upgrades** (real-time progress updates)
4. **Rate limiting** (bảo vệ từ abuse)
5. **Load balancing** (phân tán request giữa API replicas)
6. **Timeout management** (generation tasks mất ~10 phút)

---

## 1. Hai cấu hình Nginx

### 1.1 `nginx.conf` — Docker Environment

**Dùng cho**: Docker Compose deployment với `api` service có multiple replicas

**Topology**:
```
Browser (port 80)
    ↓ HTTP request
Nginx (port 80)
    ↓ upstream resolution
    ├─ /api/*  → api:7860 (Docker DNS round-robin)
    ├─ /api/ws/* → api:7860 (WebSocket)
    └─ /  → webapp:3000 (Next.js frontend)
```

### 1.2 `mcqgen.conf` — Baremetal/System-wide

**Dùng cho**: Production server chạy services trực tiếp hoặc system-level Nginx

**Installation**:
```bash
sudo ln -sf /path/to/nginx/mcqgen.conf /etc/nginx/sites-enabled/mcqgen.conf
sudo nginx -t && sudo systemctl reload nginx
```

**Topology**:
```
Browser (port 80)
    ↓ HTTP request
Nginx (port 80)
    ↓ upstream resolution (localhost)
    ├─ /api/ws/* → 127.0.0.1:8080 (FastAPI WebSocket)
    ├─ /api/*    → 127.0.0.1:8080 (FastAPI REST, strip /api)
    ├─ /         → 127.0.0.1:3000 (Next.js prod, port 8081 khi dev)
    └─ /_next/webpack-hmr → 127.0.0.1:3000 (HMR WebSocket, dev only)
```

---

## 2. Flow hoạt động chi tiết

### 2.1 REST API Request Flow

```
Browser (client-side axios)
    ↓
POST /api/auth/login
    ↓ [Nginx]
    Khớp location /api/
    ↓
    Rewrite: ^/api/(.*)$ /$1 break
        /api/auth/login  →  /auth/login
    ↓
    Rate limit check (20 req/s per IP, burst 50)
    ↓
    proxy_pass http://api_backend
    ↓
Backend receives: POST /auth/login
    (không còn /api prefix)
    ↓
Response: { access_token, ... }
    ↓ [Nginx forwards back]
Browser nhận response
```

**Lý do rewrite**:
- Frontend gọi `/api/...` (Next.js proxy convention)
- Backend FastAPI chỉ expose `/auth/login`, không `/api/auth/login`
- Nginx strip prefix trước forwarding

### 2.2 WebSocket Flow (Real-time Generation Progress)

```
Browser (generate/page.tsx)
    ↓
new WebSocket("ws://hostname:8080/ws/{taskId}")
    ↓ [Nginx location /api/ws/]
    Match: location /api/ws/
    ↓
    No rate limit (WebSocket không bị rate limit)
    ↓
    Upgrade headers:
        Upgrade: websocket
        Connection: upgrade
    ↓
    proxy_pass http://api_backend
    ↓
    proxy_read_timeout 3600s (1 giờ WebSocket connection)
    ↓
Backend FastAPI upgrades HTTP → WS
    ↓
Real-time messages: { state: "running", progress: 45, ... }
    ↓ [Nginx bidirectional tunnel]
Browser ws.onmessage nhận progress
```

**Lưu ý quan trọng**: Browser kết nối trực tiếp `ws://hostname:8080`, **không qua `/api/ws/`**

```ts
// lib/api.ts
const WS_URL = `ws://${window.location.hostname}:8080`
// → ws://localhost:8080/ws/{taskId}
//   (không phải ws://localhost/api/ws/{taskId})
```

Vì lý do này, **Next.js proxy rewrite không hỗ trợ WebSocket**, nên browser phải kết nối trực tiếp port 8080.

### 2.3 Frontend Request Flow

```
Browser
    ↓
GET / (hoặc /dashboard/generate)
    ↓ [Nginx]
    Match location /
    ↓
    proxy_pass http://webapp_backend
    ↓ (Next.js port 3000 ở prod, 8081 ở dev)
Backend Next.js
    ↓
    Render React page
    ↓
Response: HTML + JS bundles
    ↓
Browser
```

---

## 3. URL Rewriting Rules

### 3.1 REST API Rewriting

```nginx
location /api/ {
    rewrite ^/api/(.*)$ /$1 break;
    proxy_pass http://api_backend;
}
```

| Incoming URL | Rewritten to | Backend sees |
|---|---|---|
| `/api/auth/login` | `/$1 = /auth/login` | POST /auth/login ✓ |
| `/api/generate` | `/$1 = /generate` | POST /generate ✓ |
| `/api/status/{taskId}` | `/$1 = /status/{taskId}` | GET /status/{taskId} ✓ |
| `/api/admin/global-stats` | `/$1 = /admin/global-stats` | GET /admin/global-stats ✓ |

**`break` directive**: Dừng rewrite processing (không match lại), forward ngay.

### 3.2 WebSocket Rewriting

```nginx
location /api/ws/ {
    rewrite ^/api(/ws/.*)$ $1 break;
    proxy_pass http://api_backend;
}
```

| Incoming | Rewritten | Backend sees |
|---|---|---|
| `/api/ws/{taskId}` | `/ws/{taskId}` | WS /ws/{taskId} ✓ |

**Tuy nhiên**: Browser gọi thẳng `ws://hostname:8080/ws/{taskId}` (không qua Nginx `/api/ws/`).

### 3.3 Metrics Endpoint (Private)

```nginx
location /api/metrics {
    allow 172.16.0.0/12;   # Docker internal network
    deny all;
}
```

Chỉ cho phép request từ Docker internal network (Prometheus scraping), block public.

---

## 4. Rate Limiting

### 4.1 Configuration (nginx.conf)

```nginx
# Shared memory zones (across all Nginx workers)
limit_req_zone $http_authorization zone=api_limit:10m rate=20r/s;
limit_req_zone $http_authorization zone=gen_limit:2m rate=2r/m;
```

| Zone | Storage | Rate | Purpose |
|---|---|---|---|
| `api_limit` | 10MB | 20 req/s per IP | General API endpoints |
| `gen_limit` | 2MB | 2 req/minute (0.033 req/s) | POST /generate (heavy) |

Key: `$http_authorization` = `Bearer {token}` → rate limit per user (not per IP).

### 4.2 Application

```nginx
location /api/ {
    limit_req zone=api_limit burst=50 nodelay;
    limit_req_status 429;
    ...
}

location /api/generate {
    limit_req zone=gen_limit burst=5 nodelay;
    limit_req_status 429;
    ...
}
```

| Parameter | Meaning |
|---|---|
| `burst=50` | Allow up to 50 queued requests |
| `nodelay` | Immediate 429 if exceeded (không queue) |
| `limit_req_status 429` | Return HTTP 429 (không 503) |

**Ngoại lệ**: WebSocket `location /api/ws/` **không rate limit** (real-time progress không nên bị delay).

### 4.3 Response khi Rate Limited

```nginx
error_page 429 @rate_limited;
location @rate_limited {
    return 429 '{"detail":"Rate limit exceeded. Please slow down.","status":429}';
}
```

Frontend nhận `{ detail: "Rate limit exceeded..." }` → hiện toast notification (Sonner).

---

## 5. Timeout Management

**Vấn đề**: Generation task mất ~10 phút, mà HTTP default timeout ~30s.

### 5.1 Nginx Timeout Settings

```nginx
proxy_connect_timeout  10s;      # Kết nối backend
proxy_send_timeout     60s;      # Send request body
proxy_read_timeout    600s;      # Chờ response (10 phút!)
```

Được set trong `location /api/` block.

### 5.2 WebSocket Timeout

```nginx
location /api/ws/ {
    proxy_read_timeout 3600s;   # 1 giờ
}
```

WebSocket kết nối dài, cần timeout dài để tránh disconnect giữa chừng.

### 5.3 Keepalive Connection

```nginx
upstream api_backend {
    server api:7860;
    keepalive 32;              # Giữ 32 persistent connections
    keepalive_requests 1000;   # Reuse connection cho 1000 requests
}
```

Persistent connections giảm latency (không tạo TCP handshake mỗi lần).

---

## 6. Load Balancing (Docker)

### 6.1 Docker DNS Round-Robin

```nginx
upstream api_backend {
    server api:7860;    # Docker service name
}
```

Docker Compose `api` service có thể scale:
```yaml
services:
  api:
    image: mcqgen-api:v1.0
    deploy:
      replicas: 3   # 3 instances
```

Docker DNS tự động resolve `api:7860` → tất cả replicas, Nginx round-robin.

### 6.2 Manual Replicas (Explicit)

```nginx
upstream api_backend {
    server api_1:7860;
    server api_2:7860;
    server api_3:7860;
}
```

---

## 7. Health Checks

### 7.1 Nginx Health Endpoint

```nginx
location /nginx-health {
    access_log off;
    return 200 "healthy\n";
}
```

Load balancer (ngoài Nginx) gọi `GET /nginx-health` → xác nhận Nginx alive.

### 7.2 Upstream Health (Passive)

```nginx
# nginx.conf
# Bỏ qua server 30s nếu 3 lần fail liên tiếp
# (Nginx OSS dùng max_fails/fail_timeout)
```

Nginx OSS không hỗ trợ active health check (chỉ passive). Nginx Plus hỗ trợ.

### 7.3 Error Fallback

```nginx
error_page 502 503 504 @upstream_error;
location @upstream_error {
    return 502 '{"detail":"API server is temporarily unavailable.","status":502}';
}
```

Backend down → Nginx trả JSON error (không HTML error page).

---

## 8. Header Forwarding

### 8.1 Thiết lập Headers

```nginx
proxy_set_header Host              $host;
proxy_set_header X-Real-IP         $remote_addr;
proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
proxy_set_header X-Forwarded-Proto $scheme;
```

| Header | Giá trị | Dùng ở đâu |
|---|---|---|
| `Host` | `example.com` | FastAPI routing |
| `X-Real-IP` | Client IP | Logging, rate limit |
| `X-Forwarded-For` | `1.2.3.4, 5.6.7.8` | Trust chain (proxies) |
| `X-Forwarded-Proto` | `http` hoặc `https` | Redirect HTTP→HTTPS detection |

### 8.2 WebSocket Upgrade Headers

```nginx
proxy_set_header Upgrade    $http_upgrade;
proxy_set_header Connection "upgrade";
```

Bắt buộc cho WebSocket. Thay đổi HTTP → WS.

---

## 9. Performance Settings

### 9.1 Worker Processes

```nginx
worker_processes auto;      # Auto-detect CPU cores
events {
    worker_connections 1024;  # Max connections per worker
    use epoll;                # Linux epoll (efficient)
    multi_accept on;          # Accept multiple connections
}
```

### 9.2 Network Optimization

```nginx
sendfile on;        # Kernel-level sendfile
tcp_nopush on;      # Group small packets → TCP_CORK
tcp_nodelay on;     # Disable Nagle (instant send)
keepalive_timeout 65;
gzip on;
gzip_types application/json text/plain;
```

**sendfile**: Zero-copy từ file → socket (fast).

### 9.3 Logging

```nginx
log_format main '$remote_addr - $remote_user [$time_local] '
                '"$request" $status $body_bytes_sent '
                'rt=$request_time urt=$upstream_response_time '
                'corr=$http_x_correlation_id';
```

- `rt=...` → Request time (Nginx processing)
- `urt=...` → Upstream response time (backend)
- `corr=...` → Correlation ID (tracing)

---

## 10. Vì sao sử dụng Nginx?

### 10.1 Route Consolidation

**Trước Nginx**:
```
Browser → :3000 (Next.js)
Browser → :8080 (FastAPI)
```
Phức tạp, CORS issues, client phải biết ports.

**Sau Nginx**:
```
Browser → :80 (Nginx)
    → /api/* → :8080
    → /     → :3000
```
Single entry point.

### 10.2 URL Rewriting

FastAPI không expose `/api/*`, chỉ `/*`.
Nginx rewrite giản lộc:
- Client: `POST /api/generate`
- Backend: `POST /generate`

### 10.3 Rate Limiting

Nginx rate limit rẻ hơn app-level (C code in kernel).
Bảo vệ từ brute force, DoS.

### 10.4 WebSocket Routing

HTTP proxy → WebSocket cần `Upgrade` headers.
Nginx tự động xử lý upgrade.

### 10.5 Load Balancing

Nginx distribute requests giữa multiple API instances.
Docker DNS + upstream → zero downtime scaling.

### 10.6 Timeout Management

Generation task 10 phút → cần long timeout.
Nginx set `proxy_read_timeout 600s` → client không timeout.

### 10.7 Production Ready

- TLS/SSL termination (HTTPS)
- Compression (gzip)
- Caching (proxy cache)
- Security (rate limit, IP whitelist)
- Monitoring (access logs, metrics)

---

## 11. Sequence Diagram — Complete Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│                       Browser (User)                                │
└────┬────────────────────────────────────────────────────────────────┘
     │
     │ 1. GET /dashboard (HTML)
     │────────────────→ [Nginx :80]
     │                  ├─ Match location /
     │                  └─ proxy_pass http://webapp_backend
     │                     (Next.js :3000)
     │                        ↓
     │                    [Next.js]
     │                    Render page
     │                    ↓
     │←────── HTML + JS bundle ──────
     │
     │ 2. Browser runs React → Load auth state
     │    GET /auth/me (check logged in)
     │────────────────→ [Nginx]
     │                  ├─ Match location /api/
     │                  ├─ Rate limit check (api_limit zone)
     │                  ├─ Rewrite /api/auth/me → /auth/me
     │                  └─ proxy_pass http://api_backend
     │                     (FastAPI :8080)
     │                        ↓
     │                    [FastAPI]
     │                    /auth/me handler
     │                    ↓ Verify JWT from Authorization header
     │                    ↓ Return user data
     │                    ↓
     │←─── { user: {...} } ───────
     │
     │ 3. User clicks "Sinh câu hỏi"
     │    POST /api/generate { topics: [...] }
     │────────────────→ [Nginx]
     │                  ├─ Match location /api/generate
     │                  ├─ Rate limit check (gen_limit: 2 req/min)
     │                  ├─ Rewrite /api/generate → /generate
     │                  └─ proxy_pass http://api_backend
     │                     (FastAPI :8080)
     │                        ↓
     │                    [FastAPI /generate]
     │                    Create task
     │                    Return { task_id: "abc123", queue_position: 1 }
     │                    ↓
     │←─── task_id ──────────────
     │
     │ 4. Connect WebSocket for real-time progress
     │    new WebSocket("ws://hostname:8080/ws/abc123")
     │────────────────→ [Nginx]
     │                  ├─ Match location /api/ws/
     │                  ├─ Upgrade headers: websocket
     │                  ├─ proxy_read_timeout 3600s
     │                  └─ proxy_pass http://api_backend
     │                     (FastAPI :8080)
     │                        ↓
     │                    [FastAPI WebSocket /ws/abc123]
     │                    Accept connection
     │                    ↓ Worker processing...
     │                    Send: { state: "running", progress: 25, ... }
     │                    ↓
     │←─── progress update ───────
     │    ws.onmessage({ state: "running", ... })
     │    Update UI (progress bar)
     │
     │ 5. Generation complete
     │    ws message: { state: "success" }
     │────────────────→ [Nginx WS tunnel closes]
     │
     │ 6. Fetch results
     │    GET /api/results/abc123
     │────────────────→ [Nginx]
     │                  ├─ Rate limit check
     │                  ├─ Rewrite → /results/abc123
     │                  └─ proxy_pass http://api_backend
     │                     (FastAPI :8080)
     │                        ↓
     │                    [FastAPI /results/abc123]
     │                    Return { mcqs: [...] }
     │                    ↓
     │←─── MCQ list ──────────────
     │
     └─ Display results on screen
```

---

## 12. Debugging Nginx

### 12.1 Test Config

```bash
sudo nginx -t
# nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
# nginx: configuration file /etc/nginx/nginx.conf test is successful
```

### 12.2 Reload Without Downtime

```bash
sudo systemctl reload nginx
# Gracefully reload (no connection drop)
```

### 12.3 Check Logs

```bash
# Access log
tail -f /var/log/nginx/access.log

# Error log
tail -f /var/log/nginx/error.log

# Rate limit info (429 responses)
grep " 429 " /var/log/nginx/access.log
```

### 12.4 Test Rate Limit

```bash
# Simulate rapid requests
for i in {1..100}; do
  curl -H "Authorization: Bearer test-token" http://localhost/api/auth/me &
done

# Should see 429 responses after 20 requests (api_limit zone)
```

---

## 13. Tóm tắt kiến trúc

```
┌─────────────────────────────────────────────────────┐
│  Browser                                            │
│  - Axios: /api/* → :80 Nginx                        │
│  - WebSocket: ws://hostname:8080 (direct)          │
└─────────────┬───────────────────────────────────────┘
              │
        ┌─────▼──────┐
        │  Nginx :80 │ ← Reverse proxy
        │            │
        │ Routes:    │
        │ /api/*  → rewrite → :8080 (FastAPI)
        │ /api/ws → upgrade  → :8080 (FastAPI WS)
        │ /       → pass     → :3000 (Next.js)
        └─────┬──────┴─────────────────┬──────────────┐
              │                        │              │
        ┌─────▼──────┐        ┌────────▼──────┐  ┌───▼────┐
        │FastAPI:8080│        │Next.js:3000   │  │RateLimit
        │(REST API)  │        │(Frontend)     │  │Metrics
        │            │        │               │  │Health
        │ /generate  │        │ /dashboard    │  │checks
        │ /results   │        │ /login        │  │
        │ /status    │        │ /take         │  │
        └────────────┘        └───────────────┘  └────────┘
```

---

## 14. Khi nào không cần Nginx?

- Mỗi service trên domain/port khác nhau
- Dev environment, không cần production features
- Chỉ dùng trực tiếp FastAPI, không có frontend
- Không cần rate limiting, routing
