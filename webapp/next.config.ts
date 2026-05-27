import type { NextConfig } from "next";
import os from "os";

const configuredAllowedOrigins = (process.env.NEXT_ALLOWED_DEV_ORIGINS ?? "")
  .split(",")
  .map((origin) => origin.trim())
  .filter(Boolean);

const localNetworkOrigins = Object.values(os.networkInterfaces())
  .flat()
  .filter((item) => item && !item.internal && item.family === "IPv4")
  .map((item) => item.address);

const nextConfig: NextConfig = {
  allowedDevOrigins: Array.from(
    new Set([...configuredAllowedOrigins, ...localNetworkOrigins]),
  ),
};
export default nextConfig;
