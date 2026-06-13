# === STAGE 1: Cài d?t dependencies và Build source code ===
FROM node:20-alpine AS builder
WORKDIR /app

# Copy các file qu?n lý thu vi?n tru?c d? t?n d?ng Docker layer cache
COPY package*.json ./
RUN npm ci

# Copy toàn b? mã ngu?n frontend vào container
COPY . .

# Khai báo d?i s? nh?n vào t? docker-compose lúc build
ARG NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL

# Ti?n hành build ?ng d?ng Next.js sang production
RUN npm run build

# === STAGE 2: Container v?n hành g?n nh? (Production runner) ===
FROM node:20-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production

# Ch? copy nh?ng file th?c s? c?n thi?t d? ch?y ?ng d?ng t? Stage 1 sang
COPY --from=builder /app/package*.json ./
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/public ./public
COPY --from=builder /app/node_modules ./node_modules

# Next.js m?c d?nh ch?y c?ng 3000 trong container
EXPOSE 3000

# L?nh kh?i ch?y ?ng d?ng Next.js ? ch? d? Production
CMD ["npm", "run", "start"]