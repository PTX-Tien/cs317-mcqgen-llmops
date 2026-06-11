# Redis & Celery — Tại sao sử dụng?

---

## 1. Tổng quan

MCQGen sử dụng **Redis** + **Celery** để xử lý công việc nặng (generation pipeline) một cách **asynchronous** — không block user request.

```
Traditional (blocking):
  User → POST /generate → Wait 10 minutes → Response ❌

MCQGen (async):
  User → POST /generate → Response (task queued) ✓
         Celery Worker → Process in background
                      → Update progress via WebSocket
                      → Complete → User fetch results
```

---

## 2. Tại sao dùng Redis?

### 2.1 Vấn đề mà Redis giải quyết

**Không dùng Redis**:
```
FastAPI instance 1: running generate task 1
FastAPI instance 2: running generate task 2
FastAPI instance 3: có request mới, muốn check task 1 status

→ Không biết task 1 đang chạy ở instance 1
→ In-memory cache không shared
→ Rate limiting per-IP không chính xác
→ Session state mất khi instance restart
```

**Dùng Redis**:
```
Redis (single source of truth)
  ├─ Task queue: FIFO (Celery broker)
  ├─ Task results: completed tasks
  ├─ Rate limit counters: per-user/IP
  ├─ Session state: token blacklist, active sessions
  ├─ Cache: dedup generation requests
  └─ Shared across all API instances
```

### 2.2 4 vai trò của Redis trong MCQGen

#### 2.2.1 Celery Broker (DB 0)

```
Queue công việc chờ xử lý:

LPUSH celery:generate_queue {
  task_id: "abc123",
  topics: [...],
  user: "thanh",
  created_at: 1735690000
}

Workers poll queue:
  RPOP celery:generate_queue → Pick task
  Process...
  LPUSH celery:results:abc123 { result }
```

**Tại sao Redis**: FastAPI không thể process hết, cần queue

#### 2.2.2 Celery Result Backend (DB 1)

```
Lưu kết quả task đã xong:

SET celery:result:abc123 {
  state: "SUCCESS",
  result: { mcqs: [...], accepted: 45, failed: 2 },
  timestamp: 1735692000
}
TTL: 7 days (TASK_RESULT_TTL)
```

**Tại sao Redis**: Fast retrieval, auto-expire, not persistent (ok mất khi restart)

#### 2.2.3 Rate Limiting (DB 0)

```
Limit requests per user:

INCR ratelimit:api_limit:thanh  ← increment counter
EXPIRE ratelimit:api_limit:thanh 1  ← reset every 1 second

Nếu counter > 20 → 429 Too Many Requests
```

**Tại sao Redis**: Atomic increment, shared across instances, fast

#### 2.2.4 Session Management (DB 3)

```
Token blacklist:
SET mcq:blacklist:{jti} "1" EX 1800
(Redis auto-delete sau 1800s)

Active sessions:
SADD mcq:sessions:thanh {jti1} {jti2}
(Set của JTI đang active của user)

User context:
SET mcq:context:thanh [...conversation...]
```

**Tại sao Redis**: Session ephemeral (không cần persist), fast, TTL-based cleanup

### 2.3 Redis Architecture

```
redis://localhost:6379

6 databases (0-15 mặc định):
├─ DB 0: Celery broker (task queue)
├─ DB 1: Celery backend (results)
├─ DB 2: Cache (generation dedup)
├─ DB 3: Session (token blacklist, active sessions)
└─ DB 4-15: Unused

Persistence: None (cách cấu hình)
  → Mất data khi restart (acceptable cho cache/queue)
  → Nhanh hơn RDB/AOF
  → Nếu mất task ok, user retry
```

### 2.4 Fail-safe with Redis

**Redis down**?

```python
# api/core/cache.py
try:
    return _client().get(key)
except Exception:
    log.warning("cache_get_failed")
    return None  # Fail-open: continue without cache

# api/core/auth.py: get_current_user
try:
    if is_token_blacklisted(jti):
        → 401 Unauthorized
except Exception:
    pass  # Redis down → fail-open, allow token
```

Redis failure → app degrades gracefully, không crash

---

## 3. Tại sao dùng Celery?

### 3.1 Vấn đề Celery giải quyết

**Không dùng Celery** (sync generation):

```python
@app.post("/generate")
async def generate(topics):
    # Bắt đầu chạy generation (10 phút!)
    result = run_generation_pipeline(topics)
    
    # Request bị hang 10 phút
    # Client timeout (axios timeout 30s)
    # Browser hiển thị loading, user chờ, page crash
    # Nếu restart API → task restart từ đầu → mất công
    
    return result
```

**Dùng Celery** (async generation):

```python
@app.post("/generate")
async def generate(topics):
    # Enqueue task, return immediately
    task = run_mcq_pipeline.delay(topics)
    return { "task_id": task.id, "queue_position": 1 }  # 1 second!

# Worker xử lý ở background
# Client poll /status/{task_id} hoặc WebSocket để track progress
# Nếu API restart → worker vẫn chạy, task đã xong
```

### 3.2 Celery Features

#### 3.2.1 Task Routing (Queue prioritization)

```python
# tasks.py
celery_app.conf.task_routes = {
    "api.tasks.run_mcq_pipeline": {"queue": "high_priority"},
    "api.tasks.warmup_system": {"queue": "low_priority"},
}

# 2 queues:
# high_priority: user requests (urgent)
# low_priority: warmup, background jobs (can wait)

# Workers:
celery -A api.tasks worker -Q high_priority  ← fast
celery -A api.tasks worker -Q low_priority   ← can be slower
```

#### 3.2.2 Time Limits (Prevent runaway tasks)

```python
celery_app.conf.update(
    task_soft_time_limit=30*60,   # 30 phút: soft warning
    task_time_limit=35*60,         # 35 phút: force kill
)

Task chạy quá lâu:
  ├─ 30 min: SoftTimeLimitExceeded exception
  │         (worker có cơ hội cleanup)
  └─ 35 min: SIGKILL (force terminate)
```

**Tại sao cần**: Generation có thể hang vì LLM timeout, prevent zombie processes

#### 3.2.3 Retry Logic (Resilience)

```python
@celery_app.task(
    max_retries=2,
    default_retry_delay=60,
    autoretry_for=(ConnectionError, TimeoutError),
    retry_backoff=True,
    retry_backoff_max=300,
)
def run_mcq_pipeline(...):
    ...

Nếu task fail:
  ├─ 1st fail → wait 60s → retry (60s delay)
  ├─ 2nd fail → wait 120s → retry (exponential backoff)
  └─ 3rd fail → give up, mark failed
```

**Tại sao cần**: Network hiccup, temporary service down, auto-recovery

#### 3.2.4 Worker Prefetch (No queue starvation)

```python
celery_app.conf.worker_prefetch_multiplier = 1

Mỗi worker chỉ nhận 1 task từ queue
  ├─ Process task
  ├─ Acknowledge (task_acks_late=True)
  └─ RPOP queue lấy task tiếp theo

Tránh: Worker A lấy 10 tasks, nhưng worker B idle
```

#### 3.2.5 Late Acknowledgment (Data safety)

```python
celery_app.conf.task_acks_late = True

Normal (early ACK):
  Worker: RPOP task → ACK (tell broker: task removed)
                    → Process
                    → Crash! (task lost)

Late ACK:
  Worker: RPOP task → Process
                    → Success → ACK
  Nếu crash: task vẫn trong queue → retry ở worker khác
```

**Tại sao cần**: Không mất task nếu worker crash

### 3.3 Celery Monitoring

#### 3.3.1 Flower Web UI

```
http://localhost:5555

Dashboard:
├─ Active tasks (đang chạy)
├─ Task history (đã chạy)
├─ Worker status (alive/dead)
├─ Queue depth (bao nhiêu task chờ)
└─ Task failure reasons
```

#### 3.3.2 Task States

```
PENDING    → Enqueued, chưa worker pick up
STARTED    → Worker đang process
PROGRESS   → Task emit progress (custom state)
SUCCESS    → ✓ Task completed
FAILURE    → ✗ Task failed
RETRY      → Retry after backoff
REVOKED    → Task bị cancel
```

---

## 4. Workflow — Generation Task End-to-End

### 4.1 Timeline

```
t=0: User click "Tạo đề"
     │
     ├─→ Browser POST /api/generate { topics: [...] }
     │
     ├─→ [Nginx] rewrite /api/generate → /generate
     │
     ├─→ [FastAPI] @app.post("/generate")
     │    ├─ Validate topics
     │    ├─ Check Redis cache (dedup same request)
     │    │  ├─ Hit: return { task_id: cached_task_id }
     │    │  └─ Miss: continue
     │    ├─ Generate task_id: "abc123"
     │    ├─ Create Exam record in SQLite (status: pending)
     │    │
     │    ├─ Enqueue Celery task:
     │    │  run_mcq_pipeline.delay(topics, ...) → Redis DB 0
     │    │
     │    └─ Return: { task_id: "abc123", queue_position: 1 }
     │       Response time: ~100ms ✓
     │
     ├─ t≈100ms: Browser receives { task_id, queue_position }
     │
     ├─ genState = "queued"
     │
     ├─→ Browser: WebSocket connect
     │    ws://hostname:8080/ws/abc123
     │
     ├─→ [Nginx] Match location /api/ws/
     │    ├─ Upgrade headers: websocket
     │    └─ proxy_pass → FastAPI WS handler
     │
     ├─→ [FastAPI] @app.websocket("/ws/{task_id}")
     │    ├─ Accept connection
     │    └─ Start monitoring task
     │
     │
     │ QUEUE PHASE (depends on queue depth)
     │
     ├─ t=1-5s: Celery worker picks up task from queue
     │    RPOP from redis://...6379/0
     │    genState = "running"
     │    │
     │    ├─→ [WebSocket] Send: { state: "pending" }
     │    │    Browser: genState="running", progress=0%
     │    │
     │    ├─ Start generation pipeline
     │    │
     │    ├─→ Retrieve context from documents
     │    │    emit progress: 20%
     │    │    ├─→ [WebSocket] Send: { progress: 20, step: "retrieving_context" }
     │    │    └─ Browser updates progress bar
     │    │
     │    ├─→ Generate questions via LLM (longest phase)
     │    │    emit progress: 40%, 60%
     │    │    ├─→ [WebSocket] updates
     │    │    └─ Browser: stepper shows "Câu hỏi" step
     │    │
     │    ├─→ Generate options + validate
     │    │    emit progress: 80%
     │    │    ├─→ [WebSocket] updates
     │    │    └─ Browser: stepper shows "Phương án" step
     │    │
     │    └─→ Quality assessment
     │         emit progress: 100%
     │
     ├─ t=10min: Generation complete
     │
     │    ├─ Celery task success
     │    │  ├─ Persist to SQLite: UPDATE Exam SET status="success"
     │    │  ├─ Set result in Redis DB 1:
     │    │  │  SET celery:result:abc123 { mcqs: [...] } EX 604800
     │    │  └─ Cache generation result in Redis DB 2:
     │    │     SET mcq:gen:v1:hash task_id EX 604800
     │    │
     │    ├─→ [WebSocket] Send: { state: "success", mcqs: [...] }
     │    │    Browser: genState="success", mcqs rendered
     │    │    ├─→ "Bắt đầu làm đề" button enabled
     │    │    ├─→ "Download PDF" button enabled
     │    │    └─→ MCQ list displayed
     │    │
     │    └─→ Clear task from queue
     │
     └─ User can now take exam, download PDF, or generate new exam
```

### 4.2 Redis Operations During Generation

```
┌─ Redis DB 0 (Broker) ────────────────────────────────┐
│                                                       │
│ t=0: LPUSH celery:queue:high_priority {task}         │
│      [{"task_id": "abc123", ...}]                    │
│                                                       │
│ t=1s: Worker RPOP → get task                         │
│      [empty]                                         │
│                                                       │
└───────────────────────────────────────────────────────┘

┌─ Redis DB 1 (Result Backend) ─────────────────────────┐
│                                                       │
│ t=10m: SET celery:result:abc123 {                    │
│          state: "SUCCESS",                           │
│          result: { mcqs: [...], accepted: 45 }       │
│        } EX 604800                                   │
│                                                       │
│ Browser: GET /api/results/abc123                    │
│ ├─ FastAPI: celery_app.AsyncResult("abc123")        │
│ └─ Read from Redis DB 1 → return MCQs              │
│                                                       │
└───────────────────────────────────────────────────────┘

┌─ Redis DB 2 (Cache) ──────────────────────────────────┐
│                                                       │
│ Next user: same topics configuration                │
│ GET mcq:gen:v1:{hash} → returns "abc123"            │
│ → Reuse results, don't generate again!              │
│ ✓ Saves 10 minutes!                                 │
│                                                       │
└───────────────────────────────────────────────────────┘

┌─ Redis DB 3 (Session) ────────────────────────────────┐
│                                                       │
│ User authenticated:                                 │
│ SADD mcq:sessions:thanh {jti}                       │
│                                                       │
│ → Track active sessions for "logout everywhere"    │
│                                                       │
└───────────────────────────────────────────────────────┘
```

---

## 5. Scenario: Production Issues & How Redis/Celery Help

### Scenario 1: API Instance Restart

```
Without Redis/Celery:
  ├─ generation running in memory
  └─ API restart → generation lost, start over ❌

With Redis/Celery:
  ├─ generation task in Redis queue
  ├─ API restart → worker continue (different instance)
  └─ User resume WebSocket → fetch progress ✓
```

### Scenario 2: Multiple API Instances

```
Without Redis:
  ├─ Request 1: instance-1 (load balancer)
  ├─ Request 2: instance-2
  ├─ Check rate limit:
  │  ├─ instance-1: 5 requests today
  │  ├─ instance-2: 3 requests today
  │  └─ Total: unclear ❌

With Redis:
  ├─ Request 1: instance-1
  │  └─ INCR ratelimit:user:thanh → Redis
  ├─ Request 2: instance-2
  │  └─ INCR ratelimit:user:thanh → Redis (same counter!)
  └─ Rate limit accurate ✓
```

### Scenario 3: Long-running Task Timeout

```
Without Celery:
  ├─ POST /generate (start processing in request handler)
  ├─ Wait 10 minutes...
  ├─ Browser: axios timeout 30s → error ❌
  ├─ User doesn't know if task is running
  └─ API can't handle other requests

With Celery:
  ├─ POST /generate (enqueue, return immediately)
  ├─ Browser: axios gets response in 100ms ✓
  ├─ Worker process in background (no timeout)
  ├─ WebSocket for real-time updates
  ├─ If worker crashes: task in queue → retry
  └─ API handles other requests concurrently
```

### Scenario 4: Duplicate Requests (Cache Hit)

```
User 1: Generate { topics: [CS1, CS2], difficulty: G2 }
  ├─ Hash config: abc123hash
  ├─ Cache miss → generate (10 min)
  └─ Save in Redis DB 2: mcq:gen:v1:abc123hash → task_id_1

User 2: Same config { topics: [CS1, CS2], difficulty: G2 }
  ├─ Hash config: abc123hash (same!)
  ├─ Cache hit → GET mcq:gen:v1:abc123hash → task_id_1
  ├─ Return existing results (instant!)
  └─ Save 10 minutes ✓

TTL = 7 days → cache auto-expire
```

---

## 6. Comparison: Alternatives

### 6.1 Why not just FastAPI async?

```python
# async FastAPI (no Celery)
@app.post("/generate")
async def generate(topics):
    result = await run_generation_pipeline(topics)  # Still takes 10 min
    return result

Issues:
├─ If request drops → generation lost
├─ No persistence across restarts
├─ No retry logic
├─ No distributed processing
├─ Hard to scale
└─ Can't monitor task progress separately
```

### 6.2 Why not use database instead of Redis?

```
SQLite for task queue:
├─ Poll every 100ms: SELECT * FROM tasks WHERE status='pending' LIMIT 1
├─ Update: UPDATE tasks SET status='running' WHERE task_id='abc123'
├─ Disk write slower than Redis in-memory
├─ File lock contention with WAL mode
└─ Not ideal for high-frequency polling ❌

Redis for task queue:
├─ RPOP: O(1) atomic operation
├─ In-memory (fast)
├─ Perfect for queue data structure
├─ Built for this use case ✓
```

### 6.3 Why not use simpler task queue (e.g., APScheduler)?

```
APScheduler (in-memory):
├─ Works for small scale
├─ No distributed workers
├─ No persistence
└─ Mất jobs khi process restart ❌

Celery + Redis:
├─ Distributed across workers
├─ Persistent (Redis)
├─ Retry logic
├─ Monitoring (Flower)
├─ Scales to 100+ tasks/sec ✓
```

---

## 7. Deployment Topology

```
┌────────────────────────────────────────────────────────────────┐
│ Production MCQGen                                              │
└────────────────────────────────────────────────────────────────┘

                    [Nginx :80]
                         │
          ┌──────────────┼──────────────┐
          │              │              │
    [API:3000]    [API:3000]    [API:3000]
    instance 1    instance 2    instance 3
          │              │              │
          └──────────────┼──────────────┘
                         │
          ┌──────────────┴──────────────┐
          │                             │
    ┌─────▼──────┐             ┌────────▼───────┐
    │ Redis:6379 │             │  SQLite/       │
    │            │             │  PostgreSQL    │
    │ DB 0: q    │             │                │
    │ DB 1: res  │             │ Persistent     │
    │ DB 2: cac  │             │ data storage   │
    │ DB 3: sess │             └────────────────┘
    └────────────┘
          │
          │ (broker + backend)
          │
    ┌─────▼────────────────────────────────┐
    │ Celery Workers (scale independently) │
    │                                      │
    │ Worker 1 (high_priority queue)      │
    │ Worker 2 (high_priority queue)      │
    │ Worker 3 (low_priority queue)       │
    └──────────────────────────────────────┘
          │
    ┌─────▼──────────┐
    │ vLLM:7681      │
    │ LLM inference  │
    └────────────────┘
```

---

## 8. Tóm tắt

| Vấn đề | Redis giải quyết | Celery giải quyết |
|---|---|---|
| **Long-running task** | Cache progress state | Async processing |
| **Shared state** | Distributed cache | Task broker |
| **Task retry** | Not directly | Auto-retry logic |
| **Queue management** | FIFO queue | Task routing, priority |
| **Session persistence** | Token blacklist, TTL | Not applicable |
| **Multi-instance** | Shared counter/state | Distributed worker pool |
| **Monitoring** | Not built-in | Flower dashboard |
| **Scaling** | Shared bottleneck | Scale workers independently |

**Kết luận**:
- **Redis** = shared state layer (cache, queue, session)
- **Celery** = async task execution framework (worker pool, retry, routing)
- **Together** = production-ready async system
