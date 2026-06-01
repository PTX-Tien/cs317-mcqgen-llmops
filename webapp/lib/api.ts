import axios from "axios";

const normalizeUrl = (value?: string) => value?.trim().replace(/\/$/, "") || "";

/**
 * Auto-detect API base URL.
 *
 * HTTP (REST):
 *   - Port 80/443  → /api prefix (Next.js rewrites → FastAPI:8080 nội bộ)
 *   - Port khác    → direct :8080
 *
 * WebSocket:
 *   - Luôn dùng port 8080 trực tiếp (Next.js rewrites không hỗ trợ WS)
 */
const browserBackendUrl = (kind: "http" | "ws") => {
  if (typeof window === "undefined") return "";
  const port = window.location.port;
  const hostname = window.location.hostname;
  const isStandardPort = !port || port === "80" || port === "443";
  const httpProto = window.location.protocol.replace(":", "");
  const wsProto   = window.location.protocol === "https:" ? "wss" : "ws";

  if (kind === "ws") {
    // WebSocket luôn đi thẳng đến FastAPI (rewrites không support WS)
    return `${wsProto}://${hostname}:8080`;
  }

  if (isStandardPort) {
    // HTTP qua Next.js proxy (/api rewrite → FastAPI:8080)
    return `${httpProto}://${hostname}/api`;
  }
  // Dev mode: HTTP trực tiếp
  return `${httpProto}://${hostname}:8080`;
};

function resolveApiUrl() {
  const configured = normalizeUrl(process.env.NEXT_PUBLIC_API_URL);
  return configured || browserBackendUrl("http") || "http://localhost:8080";
}

function resolveWsUrl() {
  const configured = normalizeUrl(process.env.NEXT_PUBLIC_WS_URL);
  return configured || browserBackendUrl("ws") || "ws://localhost:8080";
}

export const api = axios.create({
  baseURL: resolveApiUrl(),
  timeout: 30000,
});

// Auto-inject token
api.interceptors.request.use((config) => {
  if (typeof window !== "undefined") {
    const token = localStorage.getItem("access_token");
    if (token) config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Auto-redirect on 401
api.interceptors.response.use(
  (res) => res,
  (error) => {
    if (error.response?.status === 401 && typeof window !== "undefined") {
      localStorage.removeItem("access_token");
      localStorage.removeItem("refresh_token");
      window.location.href = "/login";
    }
    return Promise.reject(error);
  },
);

export const WS_URL = resolveWsUrl()
