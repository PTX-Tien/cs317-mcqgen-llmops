# === STAGE 1: C�i d?t dependencies v� Build source code ===
FROM node:20-alpine AS builder
WORKDIR /app

# Copy c�c file qu?n l� thu vi?n tru?c d? t?n d?ng Docker layer cache
COPY package*.json ./
RUN npm ci

# Copy to�n b? m� ngu?n frontend v�o container
COPY . .

# Khai b�o d?i s? nh?n v�o t? docker-compose l�c build
ARG NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL

ARG NEXT_PUBLIC_API_BACKEND
ENV NEXT_PUBLIC_API_BACKEND=$NEXT_PUBLIC_API_BACKEND

# Ti?n h�nh build ?ng d?ng Next.js sang production
RUN npm run build

# === STAGE 2: Container v?n h�nh g?n nh? (Production runner) ===
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