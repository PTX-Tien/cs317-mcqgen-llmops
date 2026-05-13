import axios from "axios";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:7860";

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

export const WS_URL = process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:786";
