# MCQGen Webapp

Frontend Next.js của hệ thống MCQGen.

## Chạy trong repo này

Khuyến nghị chạy từ script gốc:

```bash
bash scripts/start_system.sh
```

Script gốc sẽ tự truyền `NEXT_PUBLIC_API_URL` và `NEXT_PUBLIC_API_BACKEND` cho frontend, nên không cần
duy trì `webapp/.env.local` trong Git.

## Chạy riêng frontend

```bash
cd webapp
npm install
npm run dev
```

Khi chạy riêng, frontend cần API backend đang hoạt động ở port 8080 hoặc URL tương đương.

## Build production

```bash
cd webapp
npm run build
npm run start
```

Nếu `next build` báo lỗi, hãy kiểm tra:
- API backend đã chạy chưa.
- `NEXT_PUBLIC_API_BACKEND` có trỏ đúng host/port không.
- Tài khoản `mcqgen_v2` / Node.js 20 đã được cài.
