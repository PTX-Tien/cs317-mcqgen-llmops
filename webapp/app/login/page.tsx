"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { useAuthStore } from "@/lib/store";

export default function LoginPage() {
  const router = useRouter();
  const setAuth = useAuthStore((s) => s.setAuth);
  const [form, setForm] = useState({ username: "", password: "" });
  const [loading, setLoading] = useState(false);

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    console.log("LOGIN CLICKED");
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
      console.log(err?.response);
      console.log(err?.response?.data);

      toast.error(err?.response?.data?.detail || "Login failed");
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-slate-900 to-slate-700">
      <Card className="w-full max-w-md shadow-2xl">
        <CardHeader className="text-center space-y-2">
          <div className="text-4xl">📝</div>
          <CardTitle className="text-2xl font-bold">MCQGen CS116</CardTitle>
          <CardDescription>
            Hệ thống sinh câu hỏi trắc nghiệm tự động
            <br />
            <span className="text-xs text-slate-400">
              ĐH Công nghệ Thông tin ĐHQG-HCM
            </span>
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleLogin} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="username">Username</Label>
              <Input
                id="username"
                placeholder="giaovien / sinhvien"
                value={form.username}
                onChange={(e) => setForm({ ...form, username: e.target.value })}
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                type="password"
                placeholder="••••••••"
                value={form.password}
                onChange={(e) => setForm({ ...form, password: e.target.value })}
                required
              />
            </div>
            <button
              type="submit"
              className="w-full bg-black text-white p-2 rounded"
            >
              {loading ? "Đang đăng nhập..." : "Đăng nhập"}
            </button>
          </form>
          <div className="mt-4 p-3 bg-slate-50 rounded-lg text-xs text-slate-500 space-y-1">
            <p>
              <strong>Giảng viên:</strong> giaovien / gv2026
            </p>
            <p>
              <strong>Sinh viên:</strong> sinhvien / sv2026
            </p>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
