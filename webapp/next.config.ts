import type { NextConfig } from "next";
import path from "path";

const configuredAllowedOrigins = (process.env.NEXT_ALLOWED_DEV_ORIGINS ?? "")
  .split(",")
  .map((origin) => origin.trim())
  .filter(Boolean);

const API_BACKEND = process.env.NEXT_PUBLIC_API_BACKEND ?? "http://127.0.0.1:8080";

const nextConfig: NextConfig = {
  allowedDevOrigins: Array.from(new Set(configuredAllowedOrigins)),
  outputFileTracingRoot: path.resolve(__dirname),

  // Proxy /api/* → FastAPI (port 8080). Browser chỉ cần kết nối UI port;
  // Next.js server-side forward request đến FastAPI nội bộ.
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${API_BACKEND}/:path*`,
      },
    ];
  },
};


module.exports = {
  allowedDevOrigins: ['192.168.20.154'],
}


export default nextConfig;
