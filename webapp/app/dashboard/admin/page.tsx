"use client";
import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { toast } from "sonner";
import {
  ClipboardList, Wrench, Users, BarChart3,
  ShieldCheck, UserX, UserCheck, Trash2,
  RefreshCw, Activity, X, KeyRound, ChevronRight,
  Eye, EyeOff,
} from "lucide-react";

// ── Types ──────────────────────────────────────────────────────────────────────
interface GlobalStats {
  total_users: number;
  active_users: number;
  total_exams: number;
  success_exams: number;
  total_questions: number;
  total_attempts: number;
  avg_quality: number;
  queue: { status: string; pending_jobs: number; active_jobs?: number; queued_jobs?: number };
}

interface UserRow {
  username: string;
  full_name: string;
  role: "admin" | "user";
  created_at: string | null;
  is_active: boolean;
  exam_count: number;
  success_exams: number;
  attempt_count: number;
  avg_score: number | null;
  last_active: string | null;
}

interface ExamSummary {
  id: string;
  task_id: string;
  exam_name: string;
  created_by: string;
  n_questions?: number;
  status: string;
  quality_avg?: number | null;
  created_at: string;
}

interface WarmupState {
  status: "idle" | "running" | "success" | "failed";
  progress: number;
  step: string;
  error?: string;
}

interface UserDetail extends UserRow {
  recent_exams: {
    task_id: string; exam_name: string; status: string;
    n_questions?: number; quality_avg?: number | null; created_at: string | null;
  }[];
  recent_attempts: {
    id: string; score: number; n_correct: number;
    n_total: number; submitted_at: string | null;
  }[];
}

const sleep = (ms: number) => new Promise((r) => window.setTimeout(r, ms));

// ── Page ───────────────────────────────────────────────────────────────────────
export default function AdminPage() {
  const router = useRouter();
  const [globalStats, setGlobalStats] = useState<GlobalStats | null>(null);
  const [users, setUsers]             = useState<UserRow[]>([]);
  const [exams, setExams]             = useState<ExamSummary[]>([]);
  const [loading, setLoading]         = useState(true);
  const [refreshing, setRefreshing]   = useState(false);
  const [warmup, setWarmup]           = useState<WarmupState>({ status: "idle", progress: 0, step: "" });
  const [deletingUser, setDeletingUser] = useState<string | null>(null);
  const [togglingUser, setTogglingUser] = useState<string | null>(null);

  // ── User detail modal state ──────────────────────────────────────────────────
  const [detailUser, setDetailUser]   = useState<UserDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [resetPw, setResetPw]         = useState("");
  const [resetPwConfirm, setResetPwConfirm] = useState("");
  const [showPw, setShowPw]           = useState(false);
  const [resetLoading, setResetLoading] = useState(false);

  const loadData = useCallback(async (quiet = false) => {
    const token = localStorage.getItem("access_token");
    if (!token) { router.push("/login"); return; }
    if (!quiet) setLoading(true); else setRefreshing(true);
    try {
      const [statsRes, usersRes, histRes] = await Promise.all([
        api.get<GlobalStats>("/admin/global-stats"),
        api.get<{ users: UserRow[] }>("/admin/users"),
        api.get<{ exams: ExamSummary[] }>("/history"),
      ]);
      setGlobalStats(statsRes.data);
      setUsers(usersRes.data.users);
      setExams(histRes.data.exams || []);
    } catch {
      if (!quiet) toast.error("Lỗi tải dữ liệu");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [router]);

  useEffect(() => { loadData(); }, [loadData]);

  const fmt = (s: string | null) =>
    s ? new Date(s).toLocaleString("vi-VN", { dateStyle: "short", timeStyle: "short" }) : "—";

  // ── Warmup ──────────────────────────────────────────────────────────────────
  const handleWarmup = async () => {
    setWarmup({ status: "running", progress: 0, step: "Đang gửi warmup job" });
    try {
      const { data } = await api.post("/admin/warmup");
      const taskId = data.task_id;
      const deadline = Date.now() + 15 * 60 * 1000;
      while (Date.now() < deadline) {
        await sleep(2000);
        const s = (await api.get(`/status/${taskId}`)).data;
        if (s.state === "running") {
          setWarmup({ status: "running", progress: s.progress ?? 0, step: s.step || "Warming..." });
        } else if (s.state === "success") {
          setWarmup({ status: "success", progress: 100, step: "Hệ thống sẵn sàng" });
          toast.success("Warmup hoàn tất");
          return;
        } else if (s.state === "failed") {
          throw new Error(s.error || "Warmup thất bại");
        }
      }
      throw new Error("Timeout");
    } catch (e: any) {
      const msg = e instanceof Error ? e.message : "Warmup thất bại";
      setWarmup({ status: "failed", progress: 0, step: "", error: msg });
      toast.error(msg);
    }
  };

  // ── User detail modal ────────────────────────────────────────────────────────
  const openUserDetail = async (username: string) => {
    setDetailLoading(true);
    setResetPw(""); setResetPwConfirm(""); setShowPw(false);
    try {
      const { data } = await api.get<UserDetail>(`/admin/users/${username}`);
      setDetailUser(data);
    } catch {
      toast.error("Lỗi tải thông tin user");
    } finally {
      setDetailLoading(false);
    }
  };

  const handleResetPassword = async () => {
    if (!detailUser) return;
    if (resetPw.length < 6) { toast.error("Mật khẩu phải có ít nhất 6 ký tự"); return; }
    if (resetPw !== resetPwConfirm) { toast.error("Mật khẩu xác nhận không khớp"); return; }
    setResetLoading(true);
    try {
      await api.post(`/admin/users/${detailUser.username}/reset-password`, { new_password: resetPw });
      toast.success(`Đã đặt lại mật khẩu cho ${detailUser.username}`);
      setResetPw(""); setResetPwConfirm("");
    } catch (e: any) {
      toast.error(e?.response?.data?.detail || "Lỗi đặt lại mật khẩu");
    } finally {
      setResetLoading(false);
    }
  };

  // ── User actions ────────────────────────────────────────────────────────────
  const handleToggleUser = async (username: string) => {
    setTogglingUser(username);
    try {
      const { data } = await api.patch(`/admin/users/${username}/status`);
      setUsers((prev) => prev.map((u) => u.username === username ? { ...u, is_active: data.is_active } : u));
      toast.success(data.message);
    } catch (e: any) {
      toast.error(e?.response?.data?.detail || "Lỗi thay đổi trạng thái");
    } finally {
      setTogglingUser(null);
    }
  };

  const handleDeleteUser = async (username: string) => {
    if (!window.confirm(`Xoá tài khoản "${username}" và toàn bộ data? Không thể khôi phục!`)) return;
    setDeletingUser(username);
    try {
      await api.delete(`/admin/users/${username}`);
      setUsers((prev) => prev.filter((u) => u.username !== username));
      toast.success(`Đã xoá user ${username}`);
    } catch (e: any) {
      toast.error(e?.response?.data?.detail || "Lỗi xoá user");
    } finally {
      setDeletingUser(null);
    }
  };

  // ── Status badges ───────────────────────────────────────────────────────────
  const examStatusBadge = (s: string) => {
    const map: Record<string, string> = {
      success:   "bg-emerald-50 text-emerald-700 border-emerald-200",
      pending:   "bg-amber-50 text-amber-700 border-amber-200",
      running:   "bg-amber-50 text-amber-700 border-amber-200",
      cancelled: "bg-slate-100 text-slate-500 border-slate-200",
      failed:    "bg-red-50 text-red-600 border-red-200",
    };
    const cls = map[s] || map.failed;
    const label = { success: "Success", pending: "Pending", running: "Running", cancelled: "Cancelled", failed: "Failed" }[s] || s;
    return <Badge className={`${cls} border hover:bg-opacity-100 font-medium text-xs`}>{label}</Badge>;
  };

  if (loading) return (
    <div className="flex items-center justify-center py-24 text-slate-400 text-sm gap-2">
      <div className="animate-spin w-4 h-4 border-2 border-slate-300 border-t-slate-600 rounded-full" />
      Đang tải...
    </div>
  );

  // ── Global stat cards ───────────────────────────────────────────────────────
  const statCards = [
    { label: "Người dùng", value: globalStats?.total_users ?? 0,     sub: `${globalStats?.active_users ?? 0} active`,       icon: <Users size={14} className="text-blue-500" /> },
    { label: "Đề thi",     value: globalStats?.total_exams ?? 0,     sub: `${globalStats?.success_exams ?? 0} thành công`,   icon: <ClipboardList size={14} className="text-emerald-500" /> },
    { label: "Câu hỏi",    value: globalStats?.total_questions ?? 0,  sub: `quality avg ${(globalStats?.avg_quality ?? 0).toFixed(2)}`, icon: <BarChart3 size={14} className="text-purple-500" /> },
    { label: "Lượt làm",   value: globalStats?.total_attempts ?? 0,   sub: `queue: ${globalStats?.queue?.status ?? "—"}`,    icon: <Activity size={14} className="text-orange-500" /> },
  ];

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="sticky -top-8 z-30 -mx-8 -mt-8 flex items-center justify-between gap-3 border-b border-slate-200/70 bg-[#F4F7FC]/95 px-8 py-4 backdrop-blur dark:border-slate-700 dark:bg-slate-900/95">
        <div>
          <h1 className="text-3xl font-bold text-slate-800">Admin Dashboard</h1>
          <p className="text-sm text-slate-500 mt-0.5">Quản lý hệ thống, người dùng và dữ liệu</p>
        </div>
        <Button variant="outline" size="sm" onClick={() => loadData(true)} disabled={refreshing}
          className="gap-2 text-slate-600 border-slate-200">
          <RefreshCw size={13} className={refreshing ? "animate-spin" : ""} />
          Làm mới
        </Button>
      </div>

      {/* Stat cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {statCards.map((s) => (
          <Card key={s.label} className="border-slate-200 shadow-sm">
            <CardContent className="p-3">
              <div className="flex items-center justify-between mb-1">
                <p className="text-xs text-slate-500">{s.label}</p>
                {s.icon}
              </div>
              <p className="text-2xl font-bold text-slate-800 leading-none">{s.value}</p>
              <p className="text-[11px] text-slate-400 mt-1">{s.sub}</p>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Tabs */}
      <Tabs defaultValue="users" className="space-y-0">
        <div className="flex items-center border-b border-slate-200">
          <TabsList className="h-10 bg-transparent p-0 gap-1 rounded-none">
            {[
              { value: "users",  icon: <Users size={14} className="text-blue-500" />,         label: `Người dùng (${users.length})` },
              { value: "exams",  icon: <ClipboardList size={14} className="text-slate-400" />, label: `Đề thi (${exams.length})` },
              { value: "system", icon: <Wrench size={13} className="text-slate-400" />,        label: "Hệ thống" },
            ].map((t) => (
              <TabsTrigger key={t.value} value={t.value} className="
                flex items-center gap-1.5 h-9 px-3 rounded-md text-sm font-medium
                text-slate-500 border border-transparent
                data-[state=active]:bg-white data-[state=active]:border-slate-200
                data-[state=active]:text-slate-800 data-[state=active]:shadow-sm
                data-[state=active]:font-semibold hover:text-slate-700 transition-colors
              ">
                {t.icon}{t.label}
              </TabsTrigger>
            ))}
          </TabsList>
        </div>

        {/* ── Users tab ── */}
        <TabsContent value="users" className="mt-0">
          <Card className="border-slate-200 shadow-sm rounded-tl-none border-t-0">
            <CardContent className="p-0">
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-slate-100 bg-slate-50/50">
                      {["Username", "Họ tên", "Role", "Trạng thái", "Đề thi", "Lượt làm", "Điểm TB", "Lần cuối", "Ngày tạo", "Thao tác"].map((h) => (
                        <th key={h} className="px-3 py-3 text-left text-xs font-semibold text-slate-600 uppercase tracking-wide whitespace-nowrap">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {users.length === 0 ? (
                      <tr><td colSpan={10} className="py-12 text-center text-sm text-slate-400">Chưa có user nào</td></tr>
                    ) : users.map((u) => (
                      <tr key={u.username}
                        className={`hover:bg-blue-50/30 transition-colors cursor-pointer ${!u.is_active ? "opacity-50" : ""}`}
                        onClick={() => openUserDetail(u.username)}
                      >
                        <td className="px-3 py-3 font-mono text-xs font-semibold text-slate-800">
                          <div className="flex items-center gap-1.5">
                            {u.role === "admin" && <ShieldCheck size={13} className="text-purple-500 shrink-0" />}
                            {u.username}
                            <ChevronRight size={11} className="text-slate-300 ml-auto" />
                          </div>
                        </td>
                        <td className="px-3 py-3 text-slate-700">{u.full_name || "—"}</td>
                        <td className="px-3 py-3">
                          <Badge className={`text-xs font-medium border hover:bg-opacity-100 ${u.role === "admin" ? "bg-purple-50 text-purple-700 border-purple-200" : "bg-blue-50 text-blue-700 border-blue-200"}`}>
                            {u.role === "admin" ? "Admin" : "User"}
                          </Badge>
                        </td>
                        <td className="px-3 py-3">
                          <Badge className={`text-xs font-medium border hover:bg-opacity-100 ${u.is_active ? "bg-emerald-50 text-emerald-700 border-emerald-200" : "bg-slate-100 text-slate-500 border-slate-200"}`}>
                            {u.is_active ? "Active" : "Inactive"}
                          </Badge>
                        </td>
                        <td className="px-3 py-3 text-slate-700 text-center">
                          <span className="font-semibold">{u.exam_count}</span>
                          {u.success_exams > 0 && <span className="text-emerald-500 text-xs ml-1">({u.success_exams}✓)</span>}
                        </td>
                        <td className="px-3 py-3 text-slate-700 text-center">{u.attempt_count}</td>
                        <td className="px-3 py-3 text-slate-700 text-center">
                          {u.avg_score !== null ? <span className="font-semibold">{u.avg_score.toFixed(1)}</span> : "—"}
                        </td>
                        <td className="px-3 py-3 text-slate-400 text-xs whitespace-nowrap">{fmt(u.last_active)}</td>
                        <td className="px-3 py-3 text-slate-400 text-xs whitespace-nowrap">{fmt(u.created_at)}</td>
                        <td className="px-3 py-3">
                          {u.role !== "admin" && (
                            <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
                              <button
                                onClick={() => handleToggleUser(u.username)}
                                disabled={togglingUser === u.username}
                                title={u.is_active ? "Vô hiệu hoá" : "Kích hoạt"}
                                className="p-1.5 rounded-lg hover:bg-slate-100 text-slate-500 hover:text-slate-700 transition disabled:opacity-50"
                              >
                                {u.is_active
                                  ? <UserX size={14} className="text-amber-500" />
                                  : <UserCheck size={14} className="text-emerald-500" />}
                              </button>
                              <button
                                onClick={() => handleDeleteUser(u.username)}
                                disabled={deletingUser === u.username}
                                title="Xoá tài khoản"
                                className="p-1.5 rounded-lg hover:bg-red-50 text-slate-400 hover:text-red-500 transition disabled:opacity-50"
                              >
                                <Trash2 size={14} />
                              </button>
                            </div>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {users.length > 0 && (
                <div className="flex items-center justify-between border-t border-slate-100 px-4 py-2.5">
                  <span className="text-xs text-slate-400">{users.length} tài khoản</span>
                  <span className="text-xs text-slate-400">{users.filter((u) => u.is_active).length} active • {users.filter((u) => !u.is_active).length} inactive</span>
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* ── Exams tab ── */}
        <TabsContent value="exams" className="mt-0">
          <Card className="border-slate-200 shadow-sm rounded-tl-none border-t-0">
            <CardContent className="p-0">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-100 bg-slate-50/50">
                    {["Tên đề", "Người tạo", "Số câu", "Trạng thái", "Quality", "Thời gian"].map((h) => (
                      <th key={h} className="px-4 py-3 text-left text-xs font-semibold text-slate-700 uppercase tracking-wide">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {exams.length === 0 ? (
                    <tr><td colSpan={6} className="py-12 text-center text-sm text-slate-400">Không có đề thi nào</td></tr>
                  ) : exams.map((exam) => (
                    <tr key={exam.task_id} className="hover:bg-slate-50/60 transition-colors">
                      <td className="px-4 py-3 font-medium text-slate-800">{exam.exam_name}</td>
                      <td className="px-4 py-3 text-slate-500 font-mono text-xs">{exam.created_by}</td>
                      <td className="px-4 py-3 text-slate-700">{exam.n_questions ?? "—"}</td>
                      <td className="px-4 py-3">{examStatusBadge(exam.status)}</td>
                      <td className="px-4 py-3 text-slate-700">{exam.quality_avg?.toFixed(2) ?? "—"}</td>
                      <td className="px-4 py-3 text-slate-400 text-xs">{fmt(exam.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {exams.length > 0 && (
                <div className="flex items-center justify-center border-t border-slate-100 py-2.5">
                  <span className="text-xs text-slate-400">{exams.length} đề thi gần nhất</span>
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* ── System tab ── */}
        <TabsContent value="system" className="mt-2">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <Card className="border-slate-200 shadow-sm">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-semibold text-slate-700">Trạng thái hệ thống</CardTitle>
              </CardHeader>
              <CardContent className="space-y-2 text-sm">
                {[
                  { label: "Queue status",      value: globalStats?.queue?.status ?? "—" },
                  { label: "Jobs đang chạy",     value: globalStats?.queue?.active_jobs ?? 0 },
                  { label: "Jobs đang chờ",      value: globalStats?.queue?.queued_jobs ?? 0 },
                  { label: "Total pending",      value: globalStats?.queue?.pending_jobs ?? 0 },
                ].map((row) => (
                  <div key={row.label} className="flex justify-between items-center py-1 border-b border-slate-50 last:border-0">
                    <span className="text-slate-500">{row.label}</span>
                    <strong className="text-slate-700">{row.value}</strong>
                  </div>
                ))}
                <Button onClick={handleWarmup} disabled={warmup.status === "running"}
                  className="w-full mt-3 h-9 text-sm bg-blue-500 hover:bg-blue-600 text-white gap-2">
                  <Activity size={13} />
                  {warmup.status === "running" ? `${warmup.progress}% — ${warmup.step}` : "Warm up hệ thống"}
                </Button>
                {warmup.status === "success" && <p className="text-xs text-emerald-600 text-center">{warmup.step}</p>}
                {warmup.status === "failed"  && <p className="text-xs text-red-500 text-center">{warmup.error}</p>}
              </CardContent>
            </Card>

            <Card className="border-slate-200 shadow-sm">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-semibold text-slate-700">Liên kết nhanh</CardTitle>
              </CardHeader>
              <CardContent className="space-y-1">
                {[
                  { label: "API Docs",       path: ":8080/docs" },
                  { label: "Langfuse",       path: ":8083" },
                  { label: "Flower Queue",    path: ":5555" },
                  { label: "Prometheus",      path: ":9090" },
                ].map((link) => {
                  const href = typeof window !== "undefined"
                    ? `${window.location.protocol}//${window.location.hostname}${link.path}`
                    : "#";
                  return (
                    <a key={link.label} href={href} target="_blank" rel="noopener noreferrer"
                      className="flex items-center justify-between rounded-lg px-3 py-2 hover:bg-slate-50 text-sm text-blue-500 hover:text-blue-600 transition-colors">
                      <span>{link.label}</span>
                      <span className="text-blue-400 text-xs">↗</span>
                    </a>
                  );
                })}
              </CardContent>
            </Card>
          </div>
        </TabsContent>
      </Tabs>

      {/* ── User Detail Modal ─────────────────────────────────────────────────── */}
      {(detailUser || detailLoading) && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-4"
          onClick={() => { setDetailUser(null); setResetPw(""); setResetPwConfirm(""); }}
        >
          <div
            className="bg-white rounded-2xl shadow-2xl w-full max-w-2xl max-h-[90vh] overflow-y-auto"
            onClick={(e) => e.stopPropagation()}
          >
            {detailLoading ? (
              <div className="flex items-center justify-center py-20 text-slate-400 text-sm gap-2">
                <div className="animate-spin w-4 h-4 border-2 border-slate-300 border-t-slate-600 rounded-full" />
                Đang tải...
              </div>
            ) : detailUser && (
              <>
                {/* Header */}
                <div className="flex items-start justify-between p-6 border-b border-slate-100">
                  <div className="flex items-center gap-3">
                    <div className="w-12 h-12 rounded-full bg-gradient-to-br from-blue-100 to-purple-100 flex items-center justify-center text-xl font-bold text-blue-600">
                      {detailUser.full_name?.charAt(0)?.toUpperCase() || detailUser.username?.charAt(0)?.toUpperCase() || "U"}
                    </div>
                    <div>
                      <h2 className="text-lg font-bold text-slate-800 flex items-center gap-2">
                        {detailUser.full_name || detailUser.username}
                        {detailUser.role === "admin" && (
                          <ShieldCheck size={15} className="text-purple-500" />
                        )}
                      </h2>
                      <p className="text-sm text-slate-400 font-mono">@{detailUser.username}</p>
                    </div>
                  </div>
                  <button
                    onClick={() => { setDetailUser(null); setResetPw(""); setResetPwConfirm(""); }}
                    className="p-2 rounded-lg hover:bg-slate-100 text-slate-400 transition"
                  >
                    <X size={18} />
                  </button>
                </div>

                <div className="p-6 space-y-6">
                  {/* Account info */}
                  <div>
                    <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-3">Thông tin tài khoản</h3>
                    <div className="grid grid-cols-2 gap-3">
                      {[
                        { label: "Username",    value: detailUser.username },
                        { label: "Họ và tên",   value: detailUser.full_name || "—" },
                        { label: "Role",        value: detailUser.role === "admin" ? "Admin" : "User" },
                        { label: "Trạng thái",  value: detailUser.is_active ? "Active" : "Inactive" },
                        { label: "Ngày tạo",    value: fmt(detailUser.created_at) },
                        { label: "Hoạt động gần nhất", value: fmt(detailUser.last_active) },
                      ].map((row) => (
                        <div key={row.label} className="bg-slate-50 rounded-xl p-3">
                          <p className="text-[11px] text-slate-400 mb-0.5">{row.label}</p>
                          <p className="text-sm font-semibold text-slate-700 break-all">{row.value}</p>
                        </div>
                      ))}
                    </div>
                  </div>

                  {/* Usage stats */}
                  <div>
                    <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-3">Thống kê sử dụng</h3>
                    <div className="grid grid-cols-4 gap-3">
                      {[
                        { label: "Đề thi",       value: detailUser.exam_count },
                        { label: "Thành công",    value: detailUser.success_exams },
                        { label: "Lượt làm bài",  value: detailUser.attempt_count },
                        { label: "Điểm TB",       value: detailUser.avg_score !== null ? detailUser.avg_score.toFixed(1) : "—" },
                      ].map((s) => (
                        <div key={s.label} className="bg-slate-50 rounded-xl p-3 text-center">
                          <p className="text-xl font-bold text-slate-800">{s.value}</p>
                          <p className="text-[11px] text-slate-400 mt-0.5">{s.label}</p>
                        </div>
                      ))}
                    </div>
                  </div>

                  {/* Recent exams */}
                  {detailUser.recent_exams.length > 0 && (
                    <div>
                      <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">Đề thi gần đây</h3>
                      <div className="rounded-xl border border-slate-100 overflow-hidden">
                        <table className="w-full text-xs">
                          <thead>
                            <tr className="bg-slate-50 border-b border-slate-100">
                              <th className="px-3 py-2 text-left font-semibold text-slate-500">Tên đề</th>
                              <th className="px-3 py-2 text-left font-semibold text-slate-500">Số câu</th>
                              <th className="px-3 py-2 text-left font-semibold text-slate-500">Trạng thái</th>
                              <th className="px-3 py-2 text-left font-semibold text-slate-500">Thời gian</th>
                            </tr>
                          </thead>
                          <tbody className="divide-y divide-slate-50">
                            {detailUser.recent_exams.map((e) => (
                              <tr key={e.task_id} className="hover:bg-slate-50/50">
                                <td className="px-3 py-2 font-medium text-slate-700">{e.exam_name}</td>
                                <td className="px-3 py-2 text-slate-500">{e.n_questions ?? "—"}</td>
                                <td className="px-3 py-2">{examStatusBadge(e.status)}</td>
                                <td className="px-3 py-2 text-slate-400">{fmt(e.created_at)}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  )}

                  {/* Recent attempts */}
                  {detailUser.recent_attempts.length > 0 && (
                    <div>
                      <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">Lần làm bài gần đây</h3>
                      <div className="rounded-xl border border-slate-100 overflow-hidden">
                        <table className="w-full text-xs">
                          <thead>
                            <tr className="bg-slate-50 border-b border-slate-100">
                              <th className="px-3 py-2 text-left font-semibold text-slate-500">Điểm</th>
                              <th className="px-3 py-2 text-left font-semibold text-slate-500">Kết quả</th>
                              <th className="px-3 py-2 text-left font-semibold text-slate-500">Thời gian</th>
                            </tr>
                          </thead>
                          <tbody className="divide-y divide-slate-50">
                            {detailUser.recent_attempts.map((a) => (
                              <tr key={a.id} className="hover:bg-slate-50/50">
                                <td className="px-3 py-2 font-bold text-slate-800">{a.score.toFixed(1)}</td>
                                <td className="px-3 py-2 text-slate-500">{a.n_correct}/{a.n_total} câu</td>
                                <td className="px-3 py-2 text-slate-400">{fmt(a.submitted_at)}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  )}

                  {/* Reset password — chỉ hiện cho non-admin */}
                  {detailUser.role !== "admin" && (
                    <div className="border-t border-slate-100 pt-5">
                      <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-3 flex items-center gap-1.5">
                        <KeyRound size={13} /> Đặt lại mật khẩu
                      </h3>
                      <div className="space-y-2.5">
                        <div className="relative">
                          <input
                            type={showPw ? "text" : "password"}
                            placeholder="Mật khẩu mới (ít nhất 6 ký tự)"
                            value={resetPw}
                            onChange={(e) => setResetPw(e.target.value)}
                            className="w-full h-9 px-3 pr-9 rounded-xl border border-slate-200 bg-slate-50 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400"
                          />
                          <button type="button" onClick={() => setShowPw((v) => !v)}
                            className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600">
                            {showPw ? <EyeOff size={14} /> : <Eye size={14} />}
                          </button>
                        </div>
                        <input
                          type={showPw ? "text" : "password"}
                          placeholder="Xác nhận mật khẩu mới"
                          value={resetPwConfirm}
                          onChange={(e) => setResetPwConfirm(e.target.value)}
                          className="w-full h-9 px-3 rounded-xl border border-slate-200 bg-slate-50 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400"
                        />
                        <Button
                          onClick={handleResetPassword}
                          disabled={resetLoading || resetPw.length < 6 || resetPw !== resetPwConfirm}
                          className="w-full h-9 text-sm bg-amber-500 hover:bg-amber-600 text-white gap-2"
                        >
                          <KeyRound size={13} />
                          {resetLoading ? "Đang đặt lại..." : "Xác nhận đặt lại mật khẩu"}
                        </Button>
                      </div>
                    </div>
                  )}
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
