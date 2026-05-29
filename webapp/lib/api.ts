import axios from "axios";

const normalizeUrl = (value?: string) => value?.trim().replace(/\/$/, "") || "";

const browserBackendUrl = (kind: "http" | "ws") => {
  if (typeof window === "undefined") return "";
  const protocol =
    kind === "ws"
      ? window.location.protocol === "https:"
        ? "wss"
        : "ws"
      : window.location.protocol.replace(":", "");
  return `${protocol}://${window.location.hostname}:8080`;
};

const API_URL =
  normalizeUrl(process.env.NEXT_PUBLIC_API_URL) ||
  browserBackendUrl("http") ||
  "http://127.0.0.1:8080";

export const api = axios.create({
  baseURL: API_URL,
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

export const WS_URL =
  normalizeUrl(process.env.NEXT_PUBLIC_WS_URL) ||
  browserBackendUrl("ws") ||
  "ws://127.0.0.1:8080";
