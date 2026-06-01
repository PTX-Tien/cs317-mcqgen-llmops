import type { NextConfig } from "next";
import os from "os";

const configuredAllowedOrigins = (process.env.NEXT_ALLOWED_DEV_ORIGINS ?? "")
  .split(",")
  .map((origin) => origin.trim())
  .filter(Boolean);

const localNetworkOrigins = Object.values(os.networkInterfaces())
  .flat()
  .filter((item): item is os.NetworkInterfaceInfo => Boolean(item && !item.internal && item.family === "IPv4"))
  .map((item) => item.address);

const API_BACKEND = process.env.NEXT_PUBLIC_API_BACKEND ?? "http://127.0.0.1:8080";

const nextConfig: NextConfig = {
  allowedDevOrigins: Array.from(
    new Set([...configuredAllowedOrigins, ...localNetworkOrigins]),
  ),

  // Proxy /api/* → FastAPI (port 8080) — không cần thay đổi Nginx hay mở port 8080 ra ngoài.
  // Browser chỉ cần kết nối port 80; Next.js server-side forward request đến FastAPI.
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${API_BACKEND}/:path*`,
      },
    ];
  },
};
export default nextConfig;
