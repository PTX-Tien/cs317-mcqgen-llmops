"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { useAuthStore } from "@/lib/store";
import { Eye, EyeOff, LogIn, Lock, User, ShieldCheck } from "lucide-react";

export default function LoginPage() {
  const router = useRouter();
  const setAuth = useAuthStore((s) => s.setAuth);
  const [form, setForm] = useState({ username: "", password: "" });
  const [loading, setLoading] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [rememberMe, setRememberMe] = useState(true);

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    try {
      const body = new URLSearchParams(form);
      const { data } = await api.post("/auth/login", body, {
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
      });
      localStorage.setItem("refresh_token", data.refresh_token);
      setAuth(
        { username: form.username, role: data.role, full_name: data.full_name },
        data.access_token,
      );
      toast.success(`Chào mừng, ${data.full_name}!`);
      router.push(data.role === "teacher" ? "/dashboard" : "/quiz");
    } catch (err: any) {
      toast.error(err?.response?.data?.detail || "Đăng nhập thất bại");
    } finally {
      setLoading(false);
    }
  };

  const fillDemo = (username: string, password: string) => {
    setForm({ username, password });
  };

  return (
    <div className="h-screen w-screen flex flex-col bg-[#050d2e] overflow-hidden relative">
      {/* Ambient blobs */}
      <div className="pointer-events-none absolute inset-0">
        <div className="absolute -top-20 -left-20 w-96 h-96 rounded-full bg-[#0B5CFF]/20 blur-[100px]" />
        <div className="absolute top-1/2 -right-24 w-80 h-80 rounded-full bg-purple-600/20 blur-[120px]" />
        <div className="absolute bottom-0 left-1/3 w-72 h-72 rounded-full bg-[#00B8D9]/10 blur-[90px]" />
        <svg
          className="absolute inset-0 w-full h-full opacity-[0.05]"
          xmlns="http://www.w3.org/2000/svg"
        >
          <defs>
            <pattern
              id="dots"
              x="0"
              y="0"
              width="24"
              height="24"
              patternUnits="userSpaceOnUse"
            >
              <circle cx="1.5" cy="1.5" r="1.5" fill="white" />
            </pattern>
          </defs>
          <rect width="100%" height="100%" fill="url(#dots)" />
        </svg>
      </div>

      {/* Center card */}
      <div className="relative z-10 flex-1 flex items-center justify-center px-4">
        <div className="w-full max-w-[900px] flex rounded-2xl overflow-hidden shadow-[0_24px_64px_rgba(0,0,0,0.6)] border border-white/10">
          {/* Left panel */}
          <div className="hidden lg:flex flex-col justify-between w-[44%] bg-gradient-to-b from-[#001B4D]/90 to-[#000D2A]/90 backdrop-blur-xl p-8 relative overflow-hidden">
            <div className="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-[#0B5CFF] via-[#00B8D9] to-transparent" />

            {/* Brand */}
            <div className="flex items-center gap-2.5">
              <div className="w-8 h-8 rounded-xl bg-white/10 flex items-center justify-center text-base border border-white/20">
                📝
              </div>
              <span className="text-white font-bold text-base tracking-tight">
                MCQGen CS116
              </span>
            </div>

            {/* Illustration */}
            <div className="flex flex-col items-center py-2">
              <div className="relative h-40 w-full flex items-center justify-center mb-5">
                <div className="w-20 h-20 rounded-2xl bg-gradient-to-br from-white/20 to-white/5 border border-white/20 flex items-center justify-center text-4xl shadow-xl">
                  📋
                </div>
                {[
                  { emoji: "🧠", style: { top: "0%", left: "12%" } },
                  { emoji: "💬", style: { top: "0%", right: "12%" } },
                  { emoji: "📊", style: { bottom: "0%", left: "8%" } },
                  { emoji: "⚡", style: { bottom: "0%", right: "8%" } },
                ].map(({ emoji, style }) => (
                  <div
                    key={emoji}
                    className="absolute w-10 h-10 rounded-xl bg-white/10 border border-white/20 flex items-center justify-center text-lg"
                    style={style}
                  >
                    {emoji}
                  </div>
                ))}
                <div className="absolute w-36 h-36 rounded-full border border-white/10" />
              </div>

              <h2 className="text-2xl font-extrabold text-white leading-tight mb-1 text-center">
                MCQGen <span className="text-[#4D9FFF]">CS116</span>
              </h2>
              <p className="text-blue-200/60 text-xs text-center mb-5">
                AI-powered MCQ Generation Platform
              </p>

              <div className="w-full rounded-xl bg-white/5 border border-white/10 p-3 flex items-start gap-2.5">
                <div className="w-7 h-7 rounded-lg bg-[#0B5CFF]/40 border border-[#0B5CFF]/60 flex items-center justify-center shrink-0 mt-0.5">
                  <ShieldCheck size={13} className="text-[#4D9FFF]" />
                </div>
                <p className="text-[11px] text-blue-200/60 leading-relaxed">
                  Hệ thống sinh câu hỏi trắc nghiệm tự động sử dụng{" "}
                  <span className="text-blue-300 font-medium">
                    RAG pipeline
                  </span>{" "}
                  và{" "}
                  <span className="text-blue-300 font-medium">
                    LLM inference
                  </span>
                  .
                </p>
              </div>
            </div>

            <p className="text-white/20 text-[11px]">
              ĐH Công nghệ Thông tin – ĐHQG-HCM
            </p>
          </div>

          {/* Right panel */}
          <div className="flex-1 bg-white flex flex-col justify-center px-8 py-8">
            {/* Mobile brand */}
            <div className="lg:hidden flex items-center gap-2 mb-6">
              <div className="w-8 h-8 rounded-xl bg-[#001B4D] flex items-center justify-center text-base">
                📝
              </div>
              <span className="font-bold text-[#001B4D]">MCQGen CS116</span>
            </div>

            {/* Header */}
            <div className="mb-6">
              <div className="w-12 h-12 rounded-2xl bg-[#EEF3FF] flex items-center justify-center text-2xl mb-4 shadow-sm">
                📝
              </div>
              <h1 className="text-xl font-extrabold text-slate-800 mb-0.5">
                MCQGen CS116
              </h1>
              <p className="text-xs text-slate-500">
                Hệ thống sinh câu hỏi trắc nghiệm tự động
              </p>
              <p className="text-xs text-[#0B5CFF] mt-0.5">
                ĐH Công nghệ Thông tin – ĐHQG-HCM
              </p>
            </div>

            {/* Form */}
            <form onSubmit={handleLogin} className="space-y-4">
              <div className="space-y-1">
                <label className="text-xs font-medium text-slate-700">
                  Username
                </label>
                <div className="relative">
                  <User
                    size={13}
                    className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400"
                  />
                  <input
                    type="text"
                    placeholder="Tên đăng nhập"
                    value={form.username}
                    onChange={(e) =>
                      setForm({ ...form, username: e.target.value })
                    }
                    required
                    suppressHydrationWarning
                    className="w-full h-10 pl-8 pr-3 rounded-xl border border-slate-200 bg-slate-50 text-sm text-slate-800 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-[#0B5CFF]/30 focus:border-[#0B5CFF] transition"
                  />
                </div>
              </div>

              <div className="space-y-1">
                <label className="text-xs font-medium text-slate-700">
                  Password
                </label>
                <div className="relative">
                  <Lock
                    size={13}
                    className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400"
                  />
                  <input
                    type={showPassword ? "text" : "password"}
                    placeholder="••••••••"
                    value={form.password}
                    onChange={(e) =>
                      setForm({ ...form, password: e.target.value })
                    }
                    required
                    suppressHydrationWarning
                    className="w-full h-10 pl-8 pr-9 rounded-xl border border-slate-200 bg-slate-50 text-sm text-slate-800 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-[#0B5CFF]/30 focus:border-[#0B5CFF] transition"
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword((v) => !v)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 transition"
                  >
                    {showPassword ? <EyeOff size={14} /> : <Eye size={14} />}
                  </button>
                </div>
              </div>

              <div className="flex items-center justify-between">
                <label className="flex items-center gap-2 cursor-pointer select-none">
                  <div
                    onClick={() => setRememberMe((v) => !v)}
                    className={`w-4 h-4 rounded flex items-center justify-center border transition cursor-pointer ${
                      rememberMe
                        ? "bg-[#0B5CFF] border-[#0B5CFF]"
                        : "border-slate-300 bg-white"
                    }`}
                  >
                    {rememberMe && (
                      <svg viewBox="0 0 10 8" className="w-2.5 h-2.5">
                        <path
                          d="M1 4l3 3 5-6"
                          stroke="white"
                          strokeWidth="1.5"
                          fill="none"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                        />
                      </svg>
                    )}
                  </div>
                  <span className="text-xs text-slate-600">
                    Ghi nhớ đăng nhập
                  </span>
                </label>
                <button
                  type="button"
                  className="text-xs text-[#0B5CFF] hover:underline"
                >
                  Quên mật khẩu?
                </button>
              </div>

              <button
                type="submit"
                disabled={loading}
                className="w-full h-10 rounded-xl bg-gradient-to-r from-[#0B5CFF] to-[#1E7FFF] hover:from-[#0a4de0] hover:to-[#1a6ee0] text-white text-sm font-semibold flex items-center justify-center gap-2 shadow-lg shadow-blue-500/25 transition disabled:opacity-60 disabled:cursor-not-allowed"
              >
                <LogIn size={15} />
                {loading ? "Đang đăng nhập..." : "Đăng nhập"}
              </button>
            </form>

            {/* Demo accounts */}
            <div className="mt-5">
              <div className="flex items-center gap-3 mb-3">
                <div className="flex-1 h-px bg-slate-100" />
                <span className="text-[11px] text-slate-400">
                  Demo accounts
                </span>
                <div className="flex-1 h-px bg-slate-100" />
              </div>
              <div className="grid grid-cols-2 gap-2.5">
                <button
                  type="button"
                  onClick={() => fillDemo("giaovien", "gv2026")}
                  className="flex items-center gap-2.5 p-2.5 rounded-xl bg-slate-50 hover:bg-blue-50 border border-slate-100 hover:border-[#0B5CFF]/30 transition group text-left"
                >
                  <div className="w-7 h-7 rounded-lg bg-blue-100 flex items-center justify-center text-sm shrink-0">
                    🎓
                  </div>
                  <div>
                    <p className="text-[11px] font-semibold text-slate-700 group-hover:text-[#0B5CFF] transition">
                      Giảng viên
                    </p>
                    <p className="text-[10px] text-slate-400">
                      giaovien / gv2026
                    </p>
                  </div>
                </button>
                <button
                  type="button"
                  onClick={() => fillDemo("sinhvien", "sv2026")}
                  className="flex items-center gap-2.5 p-2.5 rounded-xl bg-slate-50 hover:bg-green-50 border border-slate-100 hover:border-green-400/30 transition group text-left"
                >
                  <div className="w-7 h-7 rounded-lg bg-green-100 flex items-center justify-center text-sm shrink-0">
                    🧑‍💻
                  </div>
                  <div>
                    <p className="text-[11px] font-semibold text-slate-700 group-hover:text-green-600 transition">
                      Sinh viên
                    </p>
                    <p className="text-[10px] text-slate-400">
                      sinhvien / sv2026
                    </p>
                  </div>
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Footer */}
      <div className="relative z-10 text-center pb-3">
        <p className="text-white/20 text-[11px] flex items-center justify-center gap-1.5">
          <Lock size={10} />© 2026 MCQGen CS116. All rights reserved.
        </p>
      </div>
    </div>
  );
}
