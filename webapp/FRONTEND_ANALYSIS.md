# Phân tích Frontend — MCQGen WebApp (Next.js)

---

## 1. Stack kỹ thuật tổng quan

| Thư viện | Version | Vai trò |
|---|---|---|
| Next.js | 16.2.4 | Framework chính (App Router) |
| React | 19.2.4 | UI runtime |
| TypeScript | ^5 | Kiểu dữ liệu |
| Tailwind CSS | ^4 | Styling |
| shadcn/ui | ^4.6 | Component library |
| Lucide React | ^1.14 | Icon set |
| Zustand | ^5 | Global state (auth) |
| Axios | ^1.15 | HTTP client |
| @tanstack/react-query | ^5.100 | Cài nhưng **không dùng** |
| Sonner | ^2.0 | Toast notification |
| next-themes | ^0.4.6 | Dark mode |
| js-cookie | ^3.0 | Cookie util (cài nhưng không dùng) |

---

## 2. Cấu trúc file theo App Router

```
webapp/
├── app/
│   ├── layout.tsx              ← Root layout (global font, Toaster)
│   ├── page.tsx                ← Redirect "/" → "/dashboard"
│   ├── login/
│   │   └── page.tsx            ← Trang đăng nhập/đăng ký
│   ├── quiz/
│   │   └── page.tsx
│   └── dashboard/
│       ├── layout.tsx          ← Sidebar + Navbar (bọc toàn bộ dashboard)
│       ├── page.tsx            ← Tổng quan hệ thống
│       ├── generate/
│       │   └── page.tsx        ← Sinh câu hỏi (core feature)
│       ├── history/
│       │   └── page.tsx        ← Lịch sử đề thi
│       ├── exam/[id]/
│       │   └── page.tsx        ← Xem đề thi (dynamic route)
│       ├── take/[id]/
│       │   └── page.tsx        ← Làm đề thi (dynamic route)
│       └── admin/
│           └── page.tsx        ← Admin panel
├── components/
│   ├── math-text.tsx           ← Custom LaTeX renderer
│   └── ui/                     ← shadcn components
├── lib/
│   ├── api.ts                  ← Axios instance + WS_URL
│   ├── store.ts                ← Zustand auth store
│   ├── course.ts               ← Dữ liệu chương/topic
│   ├── exam-name.ts            ← Format tên đề
│   └── utils.ts                ← cn() helper
└── next.config.ts              ← Rewrites /api/* → FastAPI:8080
```

---

## 3. Các workflow quan trọng

### 3.1 App Router & Layout Nesting

Next.js App Router dùng hệ thống file-based routing. Layout lồng nhau:

```
app/layout.tsx                       → bao toàn bộ app (font Inter, Toaster)
  └── app/dashboard/layout.tsx       → Sidebar + Navbar
        ├── dashboard/page.tsx
        ├── dashboard/generate/page.tsx
        ├── dashboard/history/page.tsx
        └── ...
```

**Toàn bộ các file đều có `"use client"`** — không có Server Component nào fetch data server-side. Mọi data đều fetch từ browser qua axios.

### 3.2 Next.js Proxy Rewrite (next.config.ts)

```ts
// next.config.ts
rewrites() → source: "/api/:path*" → destination: "http://127.0.0.1:8080/:path*"
```

Browser chỉ gọi `/api/...` (port 80) → Next.js server forward đến FastAPI `:8080` nội bộ. Không cần mở port 8080 ra ngoài.

**Ngoại lệ**: WebSocket không đi qua rewrite, phải kết nối thẳng `ws://hostname:8080/ws/{taskId}`.

### 3.3 Workflow sinh đề thi (generate/page.tsx)

Đây là workflow phức tạp nhất:

```
User bấm "Tạo đề thi"
    ↓
POST /generate → nhận task_id + queue_position
    ↓
genState = "queued" (hiện spinner + vị trí queue)
    ↓
WebSocket ws://hostname:8080/ws/{task_id}
    ↓
ws.onmessage:
  state=running → genState="running" (cập nhật progress bar, pipeline stepper)
  state=success → GET /results/{task_id} → hiện câu hỏi
  state=failed  → genState="failed"
    ↓
ws.onerror / ws.onclose → fallback: pollFallback()
  (poll GET /status/{task_id} mỗi 3000ms)
```

**Resume generation**: Khi user reload trang, `resumeActiveGeneration()` đọc `localStorage.getItem("mcqgen.active_generation")` và nối lại WebSocket với `task_id` đang chạy.

### 3.4 Pipeline Stepper (5 bước)

| Bước | Label | Mô tả |
|---|---|---|
| 1 | Tài liệu | Đang thu thập nội dung từ nguồn |
| 2 | Câu hỏi | Đang tạo câu hỏi theo cấu hình |
| 3 | Phương án | Đang tạo các phương án trả lời |
| 4 | Ghép đề | Đang sắp xếp và điều phối câu hỏi |
| 5 | Đánh giá | Đang kiểm tra chất lượng đề thi |

Progress được tính từ `msg.progress` (0–100%) chia cho 5. Mỗi step có circle animated với CSS transition.

---

## 4. Trả lời câu hỏi: WebSocket? Polling? SSE?

### ✅ WebSocket — CÓ

File `app/dashboard/generate/page.tsx` dòng 708:

```ts
const ws = new WebSocket(`${WS_URL}/ws/${taskId}`)
// WS_URL = ws://hostname:8080 (luôn đi thẳng FastAPI, không qua proxy)
```

WebSocket nhận real-time progress trong khi generate MCQ. Đây là cơ chế **chính**.

### ✅ Polling /status — CÓ (nhiều chỗ)

**1. `pollFallback()` trong generate** — fallback khi WS lỗi:

```ts
// generate/page.tsx dòng 663
setInterval(async () => {
  await api.get(`/status/${taskId}`)  // mỗi 3000ms
}, 3000)
```

**2. `history/page.tsx`** — auto-refresh nếu có exam đang pending:

```ts
// history/page.tsx dòng 98
useEffect(() => {
  if (!exams.some(e => e.status === "pending")) return
  const interval = setInterval(() => loadHistory(), 5000)  // mỗi 5000ms
  return () => clearInterval(interval)
}, [exams])
```

**3. `admin/page.tsx` warmup** — polling trong while-loop:

```ts
// admin/page.tsx dòng 126
while (Date.now() < deadline) {
  await sleep(2000)
  await api.get(`/status/${taskId}`)  // mỗi 2000ms
}
```

### ❌ SSE (Server-Sent Events) — KHÔNG

Không có `EventSource`, không có `text/event-stream` ở bất kỳ đâu trong codebase.

---

## 5. Authentication & Authorization chi tiết

### 5.1 Luồng đăng nhập

```
LoginPage → POST /auth/login (application/x-www-form-urlencoded)
    ↓
Response: { access_token, refresh_token, role, full_name }
    ↓
localStorage.setItem("access_token", ...)
localStorage.setItem("refresh_token", ...)
useAuthStore.setAuth(user, token)   ← Zustand in-memory
    ↓
router.push("/dashboard")
```

### 5.2 Zustand Auth Store (lib/store.ts)

```ts
useAuthStore = {
  user: { username, role, full_name } | null,
  token: string | null,
  setAuth(user, token)  → ghi localStorage + set state
  clearAuth()           → xóa localStorage + reset state
  isAdmin()             → user?.role === "admin"
}
```

State **không persist** khi reload — khi reload, `user` trong Zustand sẽ là `null`. `DashboardPage` xử lý bằng cách gọi lại `GET /auth/me`:

```ts
// dashboard/page.tsx
if (!user) {
  api.get("/auth/me").then(({ data }) => setAuth(data, token))
}
```

### 5.3 Auto-inject token (lib/api.ts)

```ts
api.interceptors.request.use((config) => {
  const token = localStorage.getItem("access_token")
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})
```

Mọi request axios đều tự động đính kèm `Authorization: Bearer <token>`. Không cần truyền thủ công ở từng call.

### 5.4 Auto-redirect 401 (lib/api.ts)

```ts
api.interceptors.response.use(
  (res) => res,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem("access_token")
      localStorage.removeItem("refresh_token")
      window.location.href = "/login"
    }
    return Promise.reject(error)
  }
)
```

Khi token hết hạn hoặc không hợp lệ, tự động logout và hard-redirect về `/login`.

### 5.5 Route Guard (client-side)

Mỗi trang bảo vệ bằng `useEffect`:

```ts
useEffect(() => {
  const token = localStorage.getItem("access_token")
  if (!token) router.push("/login")
}, [router])
```

> **Lưu ý**: Không có `middleware.ts`. Guard hoàn toàn client-side — trang render một lần rồi mới redirect nếu chưa đăng nhập. Không có server-side protection.

### 5.6 Authorization theo Role

| Điều kiện | Hành vi |
|---|---|
| `user.role === "admin"` | Badge tím "Admin", thấy tab Admin trong sidebar |
| `user.role === "user"` | Badge xanh "User" |
| Gọi `/admin/*` không phải admin | Backend trả 403 (không ẩn route ở client) |
| Reset password trong admin panel | Chỉ hiện cho non-admin user |

```ts
// dashboard/layout.tsx
<Badge className={user.role === "admin"
  ? "bg-purple-100 text-purple-700"
  : "bg-blue-100 text-blue-700"
}>
  {user.role === "admin" ? "Admin" : "User"}
</Badge>
```

### 5.7 Đăng ký tài khoản

```
RegisterForm → POST /auth/register { username, password, full_name }
    ↓
Thành công → chuyển sang tab Login (không tự đăng nhập)
```

Không có email verification. Admin có thể reset password từ Admin panel.

---

## 6. Components và Tools quan trọng

### 6.1 shadcn/ui Components

| Component | File | Vai trò |
|---|---|---|
| `Button` | Toàn bộ app | CTA, action buttons |
| `Card, CardContent, CardHeader` | Dashboard, History, Admin | Container layout |
| `Badge` | Layout, History, Admin | Role badge, status badge |
| `Dialog` | History, Admin | Confirm xóa, user detail modal |
| `Input, Label` | Generate, Login | Form inputs |
| `Select, SelectItem` | Generate | Chọn chương, topic, difficulty |
| `Tabs, TabsList, TabsTrigger` | Admin | Phân tab Users/Exams/System |
| `Progress` | Take exam | Progress bar làm bài |
| `Toaster (Sonner)` | Root layout | Toast notification toàn app |

### 6.2 MathText Component (components/math-text.tsx)

Custom LaTeX renderer, **không dùng thư viện ngoài**. Tự parse và render:

- `$...$` → inline math (`<span class="math-inline">`)
- `$$...$$` → block math (`<span class="math-display">`)
- `\frac{a}{b}` → phân số với CSS flexbox
- `\sqrt{x}` → căn với ký tự √
- `^{n}` → superscript `<sup>`
- `_{n}` → subscript `<sub>`
- Ký hiệu Hy Lạp: `\alpha` → α, `\beta` → β, `\sigma` → σ, ...

Dùng ở `generate/page.tsx` và `take/[id]/page.tsx` để hiển thị câu hỏi toán học.

### 6.3 next/font/google

```ts
const inter = Inter({ subsets: ["latin"] })
```

Font tự động self-hosted bởi Next.js, không load từ Google CDN lúc runtime.

### 6.4 next/navigation hooks

| Hook | Dùng ở đâu | Mục đích |
|---|---|---|
| `useRouter()` | Mọi page | `router.push()` navigate programmatic |
| `usePathname()` | dashboard/layout.tsx | Highlight active nav item sidebar |
| `useParams()` | take/[id], exam/[id] | Lấy `id` từ dynamic route |

### 6.5 next/link

Dùng trong sidebar (`NavItem`) và các shortcut card ở Dashboard để navigation client-side (không reload trang).

---

## 7. Kiến trúc dữ liệu tổng quan

```
Browser
  ├── localStorage
  │     ├── access_token          → JWT Bearer token
  │     ├── refresh_token         → Refresh token (lưu nhưng chưa dùng auto-refresh)
  │     └── mcqgen.active_generation → Resume job khi reload
  │
  ├── Zustand (in-memory)
  │     └── useAuthStore: { user, token }
  │           → mất khi reload, re-hydrate từ GET /auth/me
  │
  ├── React useState (per page)
  │     → UI state: forms, genState, exams, results, ...
  │
  ├── Axios (HTTP)
  │     → /api/* → Next.js rewrite proxy → FastAPI:8080
  │     → interceptor: auto-inject Bearer token
  │     → interceptor: auto-redirect on 401
  │
  └── WebSocket (generate page)
        → ws://hostname:8080/ws/{taskId}
        → thẳng FastAPI, không qua Next.js proxy
        → fallback: polling /status/{taskId} mỗi 3s khi WS lỗi
```

---

## 8. Điểm đáng chú ý

| Điểm | Chi tiết |
|---|---|
| Không có Server Components | Toàn bộ `"use client"`, data fetch ở browser |
| Không có Server Actions | Không dùng `action=` form, toàn dùng axios |
| Không có Middleware auth | Guard client-side bằng `useEffect` + localStorage |
| React Query cài nhưng không dùng | `@tanstack/react-query` trong dependencies nhưng không có `useQuery` nào |
| WS URL hard-code port 8080 | `ws://hostname:8080` — không qua proxy |
| Resume generation | Lưu `active_generation` vào localStorage, reconnect WS khi reload |
| Dark mode thủ công | Toggle `document.body.classList.toggle("dark")`, không dùng `next-themes` provider |
| `suppressHydrationWarning` | Dùng trên `<html>`, `<body>`, và các `<input>` để tránh hydration mismatch |
