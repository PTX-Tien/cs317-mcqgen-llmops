import axios from "axios";

const normalizeUrl = (value?: string) => value?.trim().replace(/\/$/, "") || "";

/**
 * Auto-detect API base URL.
 *
 * HTTP (REST):
 *   - Luôn dùng /api để Next.js server proxy tới FastAPI nội bộ.
 *   - Browser chỉ cần truy cập UI port, không cần gọi trực tiếp FastAPI port.
 *
 * WebSocket:
 *   - Luôn dùng port 8080 trực tiếp (Next.js rewrites không hỗ trợ WS)
 */
const browserBackendUrl = (kind: "http" | "ws") => {
  if (typeof window === "undefined") return "";
  const hostname = window.location.hostname;
  const httpProto = window.location.protocol.replace(":", "");
  const wsProto   = window.location.protocol === "https:" ? "wss" : "ws";

  if (kind === "ws") {
    // WebSocket luôn đi thẳng đến FastAPI (rewrites không support WS)
    return `${wsProto}://${hostname}:8080`;
  }

  return `${httpProto}://${window.location.host}/api`;
};

function resolveApiUrl() {
  const configured = normalizeUrl(process.env.NEXT_PUBLIC_API_URL);
  return configured || browserBackendUrl("http") || "/api";
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
