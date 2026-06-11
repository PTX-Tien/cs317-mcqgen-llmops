# Authentication vs Authorization — Chi tiết & Luồng hoạt động

---

## 1. Phân biệt Authentication (Authen) vs Authorization (Author)

### 1.1 Authentication (Xác thực danh tính)

**Định nghĩa**: Xác minh một người là **ai** — họ có phải là chính họ không?

| Khía cạnh | Chi tiết |
|---|---|
| **Câu hỏi** | "Bạn là ai?" |
| **Phương pháp** | Username + Password → hash password bằng bcrypt |
| **Token** | JWT (JSON Web Token) chứng minh đã xác thực |
| **Thời điểm** | Khi user đăng nhập |
| **Ví dụ** | Đăng nhập Facebook bằng email + password |

### 1.2 Authorization (Cấp quyền)

**Định nghĩa**: Xác định một user đã xác thực **có quyền làm gì** — họ được phép hành động nào?

| Khía cạnh | Chi tiết |
|---|---|
| **Câu hỏi** | "Bạn được phép làm gì?" |
| **Phương pháp** | Role-based (admin/user) → check endpoint |
| **Token info** | JWT chứa role của user |
| **Thời điểm** | Trước khi xử lý request |
| **Ví dụ** | Admin truy cập `/admin/*`, user không được truy cập |

### 1.3 So sánh bảng

| Tiêu chí | Authentication | Authorization |
|---|---|---|
| Mục đích | **Xác minh danh tính** | **Phân quyền hành động** |
| Yêu cầu | Có token hợp lệ | Token + Role phù hợp |
| Thất bại → | HTTP 401 (Unauthorized) | HTTP 403 (Forbidden) |
| Ví dụ sai | Đăng nhập sai password | Admin truy cập API admin (nhưng là user) |
| Có thể bypass | Nếu không check token | Nếu không check role |

---

## 2. Luồng Authentication (Authen)

### 2.1 Đăng nhập (Login)

```
┌─────────────────────────────────────────────────────────────────┐
│                      Browser (Client)                           │
│                                                                 │
│  LoginPage.tsx                                                  │
│  ├─ user.username = "thanh"                                     │
│  └─ user.password = "123456"                                    │
└────┬────────────────────────────────────────────────────────────┘
     │
     │ 1. POST /auth/login
     │    body: { username: "thanh", password: "123456" }
     │
     ├──→ [Nginx :80]
     │    ├─ Rewrite /api/auth/login → /auth/login
     │    └─ proxy_pass → FastAPI :8080
     │
     ├──→ [FastAPI main.py /auth/login endpoint]
     │    ├─ Receive { username, password }
     │    │
     │    ├─ 2. Database lookup
     │    │    Get user from SQLite:
     │    │    SELECT * FROM UserAccount WHERE username='thanh'
     │    │    ├─ Found: UserAccount object
     │    │    │    username: "thanh"
     │    │    │    hashed_password: "$2b$12$encrypted_hash"
     │    │    │    role: "user"
     │    │    │    full_name: "Thanh Nguyễn"
     │    │    │    is_active: True
     │    │    └─ Not found → 401 Unauthorized
     │    │
     │    ├─ 3. Verify password (api/core/auth.py)
     │    │    pwd_context.verify(
     │    │       plain_password="123456",
     │    │       hashed_password="$2b$12$..."
     │    │    )
     │    │    ├─ Match → Continue
     │    │    └─ Not match → 401 Unauthorized
     │    │
     │    ├─ 4. Create JWT Token (create_token)
     │    │    Payload:
     │    │    {
     │    │      "sub": "thanh",                    ← username
     │    │      "jti": "550e8400-e29b-41d4-...",   ← unique token ID
     │    │      "exp": 1735689600,                 ← expires in 30 min
     │    │      "iat": 1735688000,                 ← issued at
     │    │      "iss": "mcqgen"                    ← issuer
     │    │    }
     │    │    Sign with: JWT_SECRET (from env)
     │    │    Algorithm: HS256
     │    │    Result: "eyJhbGc..."
     │    │
     │    ├─ 5. Register session (session.py)
     │    │    Redis DB 3:
     │    │    SET mcq:sessions:thanh JTI
     │    │    SET TTL = 30 min + 120s buffer
     │    │    ├─ Dùng để: "logout everywhere"
     │    │    └─ Fail-open: if Redis down, continue
     │    │
     │    ├─ 6. Prepare response
     │    │    {
     │    │      "access_token": "eyJhbGc...",
     │    │      "refresh_token": "...",
     │    │      "token_type": "bearer",
     │    │      "role": "user",
     │    │      "full_name": "Thanh Nguyễn"
     │    │    }
     │    │
     │    └─ Return HTTP 200
     │
     ├─← Response
     │
     └─→ [Browser]
          ├─ localStorage.setItem("access_token", JWT)
          ├─ localStorage.setItem("refresh_token", refresh_token)
          ├─ useAuthStore.setAuth(user, token)  ← Zustand state
          └─ router.push("/dashboard")  ← Navigate
```

### 2.2 Mỗi request sau đó — Token Injection

```
Browser → axios call: GET /api/dashboard
    ↓
axios interceptor (lib/api.ts):
    ├─ token = localStorage.getItem("access_token")
    ├─ config.headers.Authorization = `Bearer ${token}`
    └─ Add header: "Authorization: Bearer eyJhbGc..."
    ↓
Header gửi đến server:
    Authorization: Bearer eyJhbGc...
    ↓
[Nginx]
    ├─ Rewrite /api/dashboard → /dashboard
    └─ proxy_pass → FastAPI
    ↓
[FastAPI]
    ├─ FastAPI dependency: get_current_user()
    ├─ Extract token từ header
    └─ Decode JWT:
       ├─ Verify signature (HS256)
       ├─ Verify not expired (exp field)
       └─ Extract payload: { sub: "thanh", jti: "...", ... }
```

### 2.3 Verify Token Step-by-Step

```python
# api/core/auth.py: get_current_user() dependency
async def get_current_user(token: str = Depends(oauth2_scheme)):
    if not token:
        → HTTPException(401)  # Token không được gửi
    
    payload = decode_token(token)  # Verify JWT
    # Nếu signature không match, hết hạn, etc → 401
    
    username = payload.get("sub")
    if not username:
        → HTTPException(401)  # Token không có username
    
    jti = payload.get("jti")
    if jti and is_token_blacklisted(jti):
        → HTTPException(401)  # Token bị revoke (user logout)
    
    user = _get_user_from_db(username)
    if user is None or not user.is_active:
        → HTTPException(401)  # User không tồn tại hoặc bị lock
    
    return {
        "username": "thanh",
        "role": "user",
        "full_name": "Thanh Nguyễn",
        "jti": "550e8400-..."
    }
```

### 2.4 Token Refresh (Optional, chưa implement)

```
Access token hết hạn (30 phút)
    ↓
Browser chưa logout → có refresh_token
    ↓
POST /auth/refresh
    body: { refresh_token: "..." }
    ↓
Backend:
    ├─ Verify refresh_token
    └─ Issue new access_token (TTL: 30 phút)
    ↓
Browser update localStorage["access_token"]
```

> **Hiện tại MCQGen**: Refresh token lưu nhưng **chưa implement auto-refresh**. Khi access token hết hạn, user phải đăng nhập lại.

### 2.5 Đăng xuất (Logout)

```
Browser: "Đăng xuất"
    ↓
POST /auth/logout
    Headers: Authorization: Bearer eyJhbGc...
    ↓
[FastAPI endpoint]
    ├─ Get current_user (verify token còn hợp lệ)
    ├─ Extract jti, exp từ token
    │
    ├─ 1. Blacklist token
    │    Redis DB 3:
    │    SET mcq:blacklist:{jti} "1"
    │    TTL = exp - now (thời gian còn lại của token)
    │    ├─ Sau TTL → Redis tự xoá (không tốn bộ nhớ)
    │    └─ Mục đích: ngăn reuse token cũ
    │
    ├─ 2. Invalidate session
    │    Redis DB 3:
    │    SREM mcq:sessions:thanh {jti}  ← remove từ set
    │    (hoặc DELETE toàn bộ set cho "logout everywhere")
    │
    ├─ 3. Clear user context (optional)
    │    REDIS DB 3:
    │    DELETE mcq:context:thanh
    │
    └─ Return: { message: "Logged out successfully" }
         HTTP 200
    ↓
Browser:
    ├─ localStorage.removeItem("access_token")
    ├─ localStorage.removeItem("refresh_token")
    ├─ useAuthStore.clearAuth()
    └─ router.push("/login")
```

---

## 3. Luồng Authorization (Author)

### 3.1 Role-based Access Control (RBAC)

MCQGen có 2 roles:
- **"admin"** — Quản lý toàn hệ thống, 1 tài khoản
- **"user"** — Đăng ký tự do, mỗi user data isolated

### 3.2 Admin check decorator

```python
# api/core/auth.py
def require_role(*roles: str):
    """FastAPI dependency: chỉ cho phép role trong danh sách"""
    async def _check(user: dict = Depends(get_current_user)):
        if user["role"] not in roles:
            → HTTPException(403)  # Forbidden
        return user
    return _check

# Dùng ở endpoint:
@app.get("/admin/users")
async def list_users(user: dict = Depends(require_role("admin"))):
    # Chỉ admin mới vào được
    ...
```

### 3.3 Request flow với Authorization

```
Browser (user: "thanh", role: "user")
    ↓
GET /admin/global-stats
    Header: Authorization: Bearer eyJhbGc...{sub: "thanh", role: "user"}
    ↓
[FastAPI]
    ├─ 1. get_current_user() dependency
    │    ├─ Verify token, extract payload
    │    ├─ user = { username: "thanh", role: "user", ... }
    │    └─ Return user
    │
    ├─ 2. require_role("admin") dependency
    │    ├─ Check: user["role"] in ["admin"]
    │    ├─ "user" not in ["admin"]
    │    └─ → HTTPException(403, detail="Không có quyền...")
    │
    └─ Return HTTP 403 Forbidden
         {
           "detail": "Không có quyền thực hiện hành động này..."
         }
    ↓
Browser nhận lỗi 403
    ├─ axios interceptor không redirect (chỉ 401 redirect)
    └─ Hiện toast error: "Không có quyền"
```

### 3.4 Endpoint Authorization Summary

| Endpoint | Roles | Ý nghĩa |
|---|---|---|
| `GET /auth/me` | any | Public: lấy thông tin user hiện tại |
| `POST /generate` | any | Public: sinh đề thi |
| `GET /status/{taskId}` | any | Public: kiểm tra progress |
| `GET /admin/users` | admin | Admin: xem danh sách user |
| `PATCH /admin/users/{username}/status` | admin | Admin: enable/disable user |
| `DELETE /admin/users/{username}` | admin | Admin: xoá user |
| `POST /admin/warmup` | admin | Admin: warmup hệ thống |
| `GET /admin/global-stats` | admin | Admin: xem thống kê |

### 3.5 Data Isolation (User-level)

Ngoài role-based, còn phải check **ownership**:

```python
@app.get("/practice/{task_id}")
async def get_practice_exam(
    task_id: str,
    user: dict = Depends(get_current_user)
):
    # 1. Verify role (get_current_user)
    # 2. Verify ownership (user tạo task này)
    
    exam = db.get_exam(task_id)
    if exam.created_by != user["username"]:
        → HTTPException(403)  # User khác tạo → không được xem
    
    return exam
```

**Ví dụ**:
- User "thanh" tạo đề "De1" → `Exam.created_by = "thanh"`
- User "hoa" cố gắng `GET /practice/De1`
  - 1. get_current_user() → OK (hoa đã đăng nhập)
  - 2. Ownership check → Fail (De1.created_by = "thanh", không phải "hoa")
  - 3. Return 403 Forbidden

---

## 4. JWT Token Structure (Decode)

```
JWT = Header.Payload.Signature

Header:
{
  "alg": "HS256",
  "typ": "JWT"
}

Payload (base64-decoded):
{
  "sub": "thanh",                          ← subject (username)
  "jti": "550e8400-e29b-41d4-a716-...",   ← JWT ID (unique)
  "exp": 1735689600,                       ← expiration (unix timestamp)
  "iat": 1735688000,                       ← issued at
  "iss": "mcqgen"                          ← issuer
}

Signature:
HMACSHA256(
  base64(Header) + "." + base64(Payload),
  JWT_SECRET
)
```

**Bảo mật**:
- Payload visible (base64 chỉ là encode, không encrypt)
- Signature verify payload không bị sửa
- Secret (JWT_SECRET) chỉ backend biết

---

## 5. Session Management (Redis)

### 5.1 Token Blacklist

```
Khi user logout:
    ↓
Redis DB 3:
SET mcq:blacklist:{jti} "1" EX {ttl_seconds}

Ví dụ:
SET mcq:blacklist:550e8400-e29b-41d4 "1" EX 1800
```

**Mục đích**: Prevent token reuse sau logout (mặc dù token vẫn hợp lệ)

### 5.2 Active Sessions Tracking

```
Khi user login:
    ↓
Redis DB 3 (Set):
SADD mcq:sessions:thanh "550e8400-e29b-41d4"

Lấy tất cả active JTI:
SMEMBERS mcq:sessions:thanh
→ ["550e8400-...", "660e8400-...", ...]  (multiple devices)

"Logout everywhere":
SMEMBERS mcq:sessions:thanh
FOR EACH jti:
  SET mcq:blacklist:{jti} "1" EX ttl
DELETE mcq:sessions:thanh
```

### 5.3 User Context (Conversation History)

```
Lưu lịch sử LLM conversation per user:

Redis DB 3:
SET mcq:context:thanh [
  { role: "system", content: "You are MCQ generator", ts: "..." },
  { role: "user", content: "Generate CS116 questions", ts: "..." },
  { role: "assistant", content: "Here are 5 questions...", ts: "..." }
]
TTL = 7 days (SESSION_CONTEXT_TTL)

Max 20 turns (để tránh context quá dài)
```

---

## 6. Error Codes

| HTTP Code | Tên | Nguyên nhân | Giải pháp |
|---|---|---|---|
| **401** | Unauthorized | Chưa đăng nhập, token sai/hết hạn, user inactive | Đăng nhập lại |
| **403** | Forbidden | Đã đăng nhập nhưng không có quyền | Liên hệ admin |
| **429** | Too Many Requests | Quá nhiều request quá nhanh (rate limit) | Chờ vài phút |

---

## 7. Security Best Practices MCQGen

| Điểm | Thực hiện |
|---|---|
| **Password hashing** | bcrypt (cost=12) — khó crack |
| **Token signing** | HS256 (HMAC) — verify không bị sửa |
| **Token TTL** | 30 phút — giới hạn lifetime |
| **Token blacklist** | Redis — revoke khi logout |
| **Session tracking** | Redis — logout everywhere |
| **Rate limiting** | Nginx + FastAPI — prevent brute force |
| **CORS** | Allow "*" (dev, nên restrict ở prod) |
| **HTTPS** | TLS termination ở Nginx (prod) |
| **Secrets** | JWT_SECRET từ env, không hardcode |

---

## 8. Flow Diagram — Complete Auth Journey

```
┌─────────────────────────────────────────────────────────────────┐
│ User tương tác                                                  │
└────┬────────────────────────────────────────────────────────────┘
     │
     ├─ 1️⃣ REGISTER (tuỳ chọn)
     │    POST /auth/register
     │    { username, password, full_name }
     │    → SQLite: INSERT UserAccount
     │    → HTTP 201
     │
     ├─ 2️⃣ LOGIN
     │    POST /auth/login
     │    { username: "thanh", password: "123456" }
     │    ├─ Lookup SQLite: get user
     │    ├─ Verify password: bcrypt
     │    ├─ Create JWT: sign payload
     │    ├─ Register session: Redis SADD
     │    └─ Return: { access_token, role, full_name }
     │
     ├─ 3️⃣ STORE in Browser
     │    localStorage.access_token = "eyJhbGc..."
     │    Zustand.setAuth(user, token)
     │
     ├─ 4️⃣ EACH REQUEST (auto-inject token)
     │    GET /api/dashboard
     │    Headers: Authorization: Bearer eyJhbGc...
     │    ├─ get_current_user: Decode JWT
     │    ├─ Verify signature
     │    ├─ Check not expired
     │    ├─ Check not blacklisted
     │    └─ Check user active
     │
     ├─ 5️⃣ ADMIN endpoints
     │    GET /admin/global-stats
     │    ├─ get_current_user (verify authen)
     │    ├─ require_role("admin") (verify author)
     │    └─ Return admin data
     │
     └─ 6️⃣ LOGOUT
          POST /auth/logout
          ├─ Blacklist JWT: Redis SET
          ├─ Remove from sessions: Redis SREM
          ├─ Clear context: Redis DELETE
          └─ Browser: clear localStorage, redirect /login
```

---

## 9. Tóm tắt

| Khía cạnh | Authen | Author |
|---|---|---|
| **Chức năng** | Xác minh: "Bạn là ai?" | Kiểm tra: "Bạn được phép?" |
| **Công cụ** | JWT token + password | Role (admin/user) + ownership |
| **Storage** | SQLite (UserAccount) | JWT payload + SQLite (role) |
| **Thất bại** | 401 Unauthorized | 403 Forbidden |
| **Lifecycle** | 30 phút (TTL) | Suốt đời user hoặc endpoint |
| **Bypass check** | Logout → blacklist token | Không có role → 403 |
