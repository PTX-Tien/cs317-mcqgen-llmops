"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { useAuthStore } from "@/lib/store";
import { Eye, EyeOff, LogIn, Lock, User, ShieldCheck, UserPlus } from "lucide-react";

type Tab = "login" | "register";

export default function LoginPage() {
  const router = useRouter();
  const setAuth = useAuthStore((s) => s.setAuth);

  const [tab, setTab] = useState<Tab>("login");
  const [loginForm, setLoginForm]     = useState({ username: "", password: "" });
  const [registerForm, setRegisterForm] = useState({ username: "", password: "", confirm: "", full_name: "" });
  const [loading, setLoading]         = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirm, setShowConfirm]   = useState(false);

  /* ── Login ── */
  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    try {
      const body = new URLSearchParams({ username: loginForm.username, password: loginForm.password });
      const { data } = await api.post("/auth/login", body, {
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
      });
      localStorage.setItem("refresh_token", data.refresh_token);
      setAuth(
        { username: loginForm.username, role: data.role, full_name: data.full_name },
        data.access_token,
      );
      toast.success(`Chào mừng, ${data.full_name}!`);
      router.push("/dashboard");
    } catch (err: any) {
      toast.error(err?.response?.data?.detail || "Đăng nhập thất bại");
    } finally {
      setLoading(false);
    }
  };

  /* ── Register ── */
  const handleRegister = async (e: React.FormEvent) => {
    e.preventDefault();
    if (registerForm.password !== registerForm.confirm) {
      toast.error("Mật khẩu xác nhận không khớp");
      return;
    }
    setLoading(true);
    try {
      await api.post("/auth/register", {
        username:  registerForm.username,
        password:  registerForm.password,
        full_name: registerForm.full_name || registerForm.username,
      });
      toast.success("Đăng ký thành công! Hãy đăng nhập.");
      setLoginForm({ username: registerForm.username, password: "" });
      setTab("login");
    } catch (err: any) {
      toast.error(err?.response?.data?.detail || "Đăng ký thất bại");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="h-screen w-screen flex flex-col bg-[#050d2e] overflow-hidden relative">
      {/* Ambient blobs */}
      <div className="pointer-events-none absolute inset-0">
        <div className="absolute -top-20 -left-20 w-96 h-96 rounded-full bg-[#0B5CFF]/20 blur-[100px]" />
        <div className="absolute top-1/2 -right-24 w-80 h-80 rounded-full bg-purple-600/20 blur-[120px]" />
        <div className="absolute bottom-0 left-1/3 w-72 h-72 rounded-full bg-[#00B8D9]/10 blur-[90px]" />
        <svg className="absolute inset-0 w-full h-full opacity-[0.05]" xmlns="http://www.w3.org/2000/svg">
          <defs>
            <pattern id="dots" x="0" y="0" width="24" height="24" patternUnits="userSpaceOnUse">
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
            <div className="flex items-center gap-2.5">
              <div className="w-8 h-8 rounded-xl bg-white/10 flex items-center justify-center text-base border border-white/20">📝</div>
              <span className="text-white font-bold text-base tracking-tight">MCQGen</span>
            </div>
            <div className="flex flex-col items-center py-2">
              <div className="relative h-40 w-full flex items-center justify-center mb-5">
                <div className="w-20 h-20 rounded-2xl bg-gradient-to-br from-white/20 to-white/5 border border-white/20 flex items-center justify-center text-4xl shadow-xl">📋</div>
                {[
                  { emoji: "🧠", style: { top: "0%",    left: "12%" } },
                  { emoji: "💬", style: { top: "0%",    right: "12%" } },
                  { emoji: "📊", style: { bottom: "0%", left: "8%"  } },
                  { emoji: "⚡", style: { bottom: "0%", right: "8%" } },
                ].map(({ emoji, style }) => (
                  <div key={emoji} className="absolute w-10 h-10 rounded-xl bg-white/10 border border-white/20 flex items-center justify-center text-lg" style={style}>{emoji}</div>
                ))}
                <div className="absolute w-36 h-36 rounded-full border border-white/10" />
              </div>
              <h2 className="text-2xl font-extrabold text-white leading-tight mb-1 text-center">
                MCQGen <span className="text-[#4D9FFF]">Platform</span>
              </h2>
              <p className="text-blue-200/60 text-xs text-center mb-5">AI-powered MCQ Generation</p>
              <div className="w-full rounded-xl bg-white/5 border border-white/10 p-3 flex items-start gap-2.5">
                <div className="w-7 h-7 rounded-lg bg-[#0B5CFF]/40 border border-[#0B5CFF]/60 flex items-center justify-center shrink-0 mt-0.5">
                  <ShieldCheck size={13} className="text-[#4D9FFF]" />
                </div>
                <p className="text-[11px] text-blue-200/60 leading-relaxed">
                  Mỗi tài khoản có <span className="text-blue-300 font-medium">dữ liệu riêng biệt</span> — đề thi, lịch sử và kết quả không bị chia sẻ giữa các user.
                </p>
              </div>
            </div>
            <p className="text-white/20 text-[11px]">ĐH Công nghệ Thông tin – ĐHQG-HCM</p>
          </div>

          {/* Right panel */}
          <div className="flex-1 bg-white flex flex-col justify-center px-8 py-8">
            {/* Mobile brand */}
            <div className="lg:hidden flex items-center gap-2 mb-6">
              <div className="w-8 h-8 rounded-xl bg-[#001B4D] flex items-center justify-center text-base">📝</div>
              <span className="font-bold text-[#001B4D]">MCQGen</span>
            </div>

            {/* Header */}
            <div className="mb-5">
              <div className="w-12 h-12 rounded-2xl bg-[#EEF3FF] flex items-center justify-center text-2xl mb-3 shadow-sm">📝</div>
              <h1 className="text-xl font-extrabold text-slate-800 mb-0.5">MCQGen Platform</h1>
              <p className="text-xs text-slate-500">Hệ thống sinh câu hỏi trắc nghiệm tự động</p>
            </div>

            {/* Tabs */}
            <div className="flex rounded-xl bg-slate-100 p-1 mb-5 gap-1">
              <button
                type="button"
                onClick={() => setTab("login")}
                className={`flex-1 flex items-center justify-center gap-1.5 h-8 rounded-lg text-xs font-semibold transition ${
                  tab === "login" ? "bg-white text-[#0B5CFF] shadow-sm" : "text-slate-500 hover:text-slate-700"
                }`}
              >
                <LogIn size={13} /> Đăng nhập
              </button>
              <button
                type="button"
                onClick={() => setTab("register")}
                className={`flex-1 flex items-center justify-center gap-1.5 h-8 rounded-lg text-xs font-semibold transition ${
                  tab === "register" ? "bg-white text-[#0B5CFF] shadow-sm" : "text-slate-500 hover:text-slate-700"
                }`}
              >
                <UserPlus size={13} /> Đăng ký
              </button>
            </div>

            {/* ── Login form ── */}
            {tab === "login" && (
              <form onSubmit={handleLogin} className="space-y-4">
                <div className="space-y-1">
                  <label className="text-xs font-medium text-slate-700">Username</label>
                  <div className="relative">
                    <User size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
                    <input
                      type="text" placeholder="Tên đăng nhập"
                      value={loginForm.username}
                      onChange={(e) => setLoginForm({ ...loginForm, username: e.target.value })}
                      required suppressHydrationWarning
                      className="w-full h-10 pl-8 pr-3 rounded-xl border border-slate-200 bg-slate-50 text-sm text-slate-800 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-[#0B5CFF]/30 focus:border-[#0B5CFF] transition"
                    />
                  </div>
                </div>
                <div className="space-y-1">
                  <label className="text-xs font-medium text-slate-700">Password</label>
                  <div className="relative">
                    <Lock size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
                    <input
                      type={showPassword ? "text" : "password"} placeholder="••••••••"
                      value={loginForm.password}
                      onChange={(e) => setLoginForm({ ...loginForm, password: e.target.value })}
                      required suppressHydrationWarning
                      className="w-full h-10 pl-8 pr-9 rounded-xl border border-slate-200 bg-slate-50 text-sm text-slate-800 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-[#0B5CFF]/30 focus:border-[#0B5CFF] transition"
                    />
                    <button type="button" onClick={() => setShowPassword((v) => !v)} className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 transition">
                      {showPassword ? <EyeOff size={14} /> : <Eye size={14} />}
                    </button>
                  </div>
                </div>
                <button type="submit" disabled={loading}
                  className="w-full h-10 rounded-xl bg-gradient-to-r from-[#0B5CFF] to-[#1E7FFF] hover:from-[#0a4de0] hover:to-[#1a6ee0] text-white text-sm font-semibold flex items-center justify-center gap-2 shadow-lg shadow-blue-500/25 transition disabled:opacity-60 disabled:cursor-not-allowed"
                >
                  <LogIn size={15} />
                  {loading ? "Đang đăng nhập..." : "Đăng nhập"}
                </button>
              </form>
            )}

            {/* ── Register form ── */}
            {tab === "register" && (
              <form onSubmit={handleRegister} className="space-y-3">
                <div className="space-y-1">
                  <label className="text-xs font-medium text-slate-700">Username <span className="text-red-400">*</span></label>
                  <div className="relative">
                    <User size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
                    <input
                      type="text" placeholder="Ít nhất 3 ký tự"
                      value={registerForm.username}
                      onChange={(e) => setRegisterForm({ ...registerForm, username: e.target.value })}
                      required minLength={3} suppressHydrationWarning
                      className="w-full h-10 pl-8 pr-3 rounded-xl border border-slate-200 bg-slate-50 text-sm text-slate-800 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-[#0B5CFF]/30 focus:border-[#0B5CFF] transition"
                    />
                  </div>
                </div>
                <div className="space-y-1">
                  <label className="text-xs font-medium text-slate-700">Họ và tên</label>
                  <input
                    type="text" placeholder="Tên hiển thị (tuỳ chọn)"
                    value={registerForm.full_name}
                    onChange={(e) => setRegisterForm({ ...registerForm, full_name: e.target.value })}
                    suppressHydrationWarning
                    className="w-full h-10 px-3 rounded-xl border border-slate-200 bg-slate-50 text-sm text-slate-800 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-[#0B5CFF]/30 focus:border-[#0B5CFF] transition"
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-xs font-medium text-slate-700">Password <span className="text-red-400">*</span></label>
                  <div className="relative">
                    <Lock size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
                    <input
                      type={showPassword ? "text" : "password"} placeholder="Ít nhất 6 ký tự"
                      value={registerForm.password}
                      onChange={(e) => setRegisterForm({ ...registerForm, password: e.target.value })}
                      required minLength={6} suppressHydrationWarning
                      className="w-full h-10 pl-8 pr-9 rounded-xl border border-slate-200 bg-slate-50 text-sm text-slate-800 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-[#0B5CFF]/30 focus:border-[#0B5CFF] transition"
                    />
                    <button type="button" onClick={() => setShowPassword((v) => !v)} className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 transition">
                      {showPassword ? <EyeOff size={14} /> : <Eye size={14} />}
                    </button>
                  </div>
                </div>
                <div className="space-y-1">
                  <label className="text-xs font-medium text-slate-700">Xác nhận password <span className="text-red-400">*</span></label>
                  <div className="relative">
                    <Lock size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
                    <input
                      type={showConfirm ? "text" : "password"} placeholder="Nhập lại password"
                      value={registerForm.confirm}
                      onChange={(e) => setRegisterForm({ ...registerForm, confirm: e.target.value })}
                      required suppressHydrationWarning
                      className="w-full h-10 pl-8 pr-9 rounded-xl border border-slate-200 bg-slate-50 text-sm text-slate-800 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-[#0B5CFF]/30 focus:border-[#0B5CFF] transition"
                    />
                    <button type="button" onClick={() => setShowConfirm((v) => !v)} className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 transition">
                      {showConfirm ? <EyeOff size={14} /> : <Eye size={14} />}
                    </button>
                  </div>
                </div>
                <button type="submit" disabled={loading}
                  className="w-full h-10 rounded-xl bg-gradient-to-r from-emerald-500 to-teal-500 hover:from-emerald-600 hover:to-teal-600 text-white text-sm font-semibold flex items-center justify-center gap-2 shadow-lg shadow-emerald-500/25 transition disabled:opacity-60 disabled:cursor-not-allowed"
                >
                  <UserPlus size={15} />
                  {loading ? "Đang đăng ký..." : "Tạo tài khoản"}
                </button>
                <p className="text-center text-[11px] text-slate-400">
                  Đã có tài khoản?{" "}
                  <button type="button" onClick={() => setTab("login")} className="text-[#0B5CFF] hover:underline font-medium">Đăng nhập</button>
                </p>
              </form>
            )}
          </div>
        </div>
      </div>

      {/* Footer */}
      <div className="relative z-10 text-center pb-3">
        <p className="text-white/20 text-[11px] flex items-center justify-center gap-1.5">
          <Lock size={10} />© 2026 MCQGen. All rights reserved.
        </p>
      </div>
    </div>
  );
}
