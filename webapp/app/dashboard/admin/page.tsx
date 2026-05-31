"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { formatExamDisplayName } from "@/lib/exam-name";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { toast } from "sonner";
import {
  BarChart3,
  CheckCircle2,
  ClipboardList,
  HelpCircle,
  Star,
  Wrench,
} from "lucide-react";

interface QueueStatus {
  status: "idle" | "busy";
  pending_jobs: number;
  active_jobs?: number;
  queued_jobs?: number;
  estimated_wait_min: number;
}

interface ExamSummary {
  id: number;
  exam_name: string;
  created_by: string;
  n_questions?: number;
  status: string;
  quality_avg?: number | null;
  created_at: string;
}

interface AdminStats {
  total_exams: number;
  success_exams: number;
  total_questions: number;
  avg_quality: number;
  queue: QueueStatus;
}

interface WarmupState {
  status: "idle" | "running" | "success" | "failed";
  progress: number;
  step: string;
  error?: string;
}

interface WarmupStatusResponse {
  state: string;
  progress?: number;
  step?: string;
  error?: string;
  ready?: boolean;
}

const sleep = (ms: number) =>
  new Promise((resolve) => window.setTimeout(resolve, ms));

export default function AdminPage() {
  const router = useRouter();
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [exams, setExams] = useState<ExamSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [warmup, setWarmup] = useState<WarmupState>({
    status: "idle",
    progress: 0,
    step: "",
  });

  useEffect(() => {
    const token = localStorage.getItem("access_token");
    if (!token) {
      router.push("/login");
      return;
    }

    let cancelled = false;
    const loadData = async () => {
      try {
        const [histRes, queueRes] = await Promise.all([
          api.get("/history"),
          api.get("/queue/status"),
        ]);
        if (cancelled) return;
        const history: ExamSummary[] = histRes.data.exams || [];
        const qualityScores = history
          .map((e) => e.quality_avg)
          .filter((s): s is number => typeof s === "number");
        setExams(history);
        setStats({
          total_exams: history.length,
          success_exams: history.filter((e) => e.status === "success").length,
          total_questions: history.reduce(
            (sum, e) => sum + (e.n_questions || 0),
            0,
          ),
          avg_quality: qualityScores.length
            ? qualityScores.reduce((s, v) => s + v, 0) / qualityScores.length
            : 0,
          queue: queueRes.data,
        });
      } catch {
        if (!cancelled) toast.error("Lỗi tải dữ liệu");
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    loadData();
    return () => {
      cancelled = true;
    };
  }, [router]);

  const formatDate = (s: string) =>
    new Date(s).toLocaleString("vi-VN", {
      dateStyle: "short",
      timeStyle: "short",
    });

  const handleWarmup = async () => {
    setWarmup({ status: "running", progress: 0, step: "Đang gửi warmup job" });
    try {
      const { data } = await api.post("/admin/warmup");
      const taskId = data.task_id;
      const deadline = Date.now() + 15 * 60 * 1000;
      while (Date.now() < deadline) {
        await sleep(2000);
        const statusRes = await api.get<WarmupStatusResponse>(
          `/status/${taskId}`,
        );
        const s = statusRes.data;
        if (s.state === "running") {
          setWarmup({
            status: "running",
            progress: s.progress ?? 0,
            step: s.step || "Đang warm up",
          });
        } else if (s.state === "success") {
          setWarmup({
            status: "success",
            progress: 100,
            step: s.ready ? "Hệ thống đã sẵn sàng" : "Warmup hoàn tất",
          });
          toast.success("Warmup hoàn tất");
          return;
        } else if (s.state === "failed") {
          throw new Error(s.error || "Warmup thất bại");
        }
      }
      throw new Error("Warmup timeout");
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Warmup thất bại";
      setWarmup({ status: "failed", progress: 0, step: "", error: message });
      toast.error(message);
    }
  };

  const handleDelete = async (examId: number) => {
    try {
      await api.delete(`/history/${examId}`);
      setExams((prev) => prev.filter((e) => e.id !== examId));
      toast.success("Đã xoá đề thi");
    } catch {
      toast.error("Không xoá được đề thi");
    }
  };

  const statusBadge = (s: string) => {
    if (s === "success")
      return (
        <Badge className="bg-emerald-50 text-emerald-700 border border-emerald-200 hover:bg-emerald-50 font-medium text-xs">
          Success
        </Badge>
      );
    if (s === "pending" || s === "running")
      return (
        <Badge className="bg-amber-50 text-amber-700 border border-amber-200 hover:bg-amber-50 font-medium text-xs">
          Running
        </Badge>
      );
    if (s === "cancelled")
      return (
        <Badge className="bg-slate-100 text-slate-500 border border-slate-200 hover:bg-slate-100 font-medium text-xs">
          Cancelled
        </Badge>
      );
    return (
      <Badge className="bg-red-50 text-red-600 border border-red-200 hover:bg-red-50 font-medium text-xs">
        Failed
      </Badge>
    );
  };

  if (loading)
    return (
      <div className="flex items-center justify-center py-24 text-slate-400 text-sm">
        Đang tải...
      </div>
    );

  const statCards = [
    {
      label: "Tổng đề thi",
      value: stats?.total_exams ?? 0,
    },
    {
      label: "Hoàn thành",
      value: stats?.success_exams ?? 0,
    },
    {
      label: "Tổng câu hỏi",
      value: stats?.total_questions ?? 0,
    },
    {
      label: "Quality avg",
      value: stats?.avg_quality?.toFixed(2) ?? "—",
    },
  ];

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="sticky -top-8 z-30 -mx-8 -mt-8 flex items-center justify-between gap-3 border-b border-slate-200/70 bg-[#F4F7FC]/95 px-8 py-4 backdrop-blur dark:border-slate-700 dark:bg-slate-900/95">
        <div>
          <h1 className="text-3xl font-bold text-slate-800">Admin Dashboard</h1>
          <p className="text-sm text-slate-500 mt-0.5">
            Quản lý hệ thống và dữ liệu
          </p>
        </div>
      </div>

      {/* Stat Cards — compact */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {statCards.map((s) => (
          <Card key={s.label} className="border-slate-200 shadow-sm">
            <CardContent className="p-2 pb-1">
              <p className="text-2xl font-bold text-slate-800 leading-none">
                {s.value}
              </p>
              <p className="text-xs text-slate-500 mt-1">{s.label}</p>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Tabs */}
      <Tabs defaultValue="exams" className="space-y-0">
        {/* Tab bar */}
        <div className="flex items-center border-b border-slate-200">
          <TabsList className="h-10 bg-transparent p-0 gap-1 rounded-none">
            <TabsTrigger
              value="exams"
              className="
                flex items-center gap-1.5 h-9 px-3 rounded-md text-sm font-medium
                text-slate-500 border border-transparent
                data-[state=active]:bg-white data-[state=active]:border-slate-200
                data-[state=active]:text-slate-800 data-[state=active]:shadow-sm
                data-[state=active]:font-semibold
                hover:text-slate-700 transition-colors
              "
            >
              <ClipboardList size={14} className="text-blue-500" />
              Đề thi ({exams.length})
            </TabsTrigger>
            <TabsTrigger
              value="system"
              className="
                flex items-center gap-1.5 h-9 px-3 rounded-md text-sm font-medium
                text-slate-400 border border-transparent
                data-[state=active]:bg-white data-[state=active]:border-slate-200
                data-[state=active]:text-slate-800 data-[state=active]:shadow-sm
                data-[state=active]:font-semibold
                hover:text-slate-600 transition-colors
              "
            >
              <Wrench size={13} className="text-slate-400" />
              Hệ thống
            </TabsTrigger>
          </TabsList>
        </div>

        {/* Exams tab */}
        <TabsContent value="exams" className="mt-0">
          <Card className="border-slate-200 shadow-sm rounded-tl-none border-t-0">
            <CardContent className="p-0">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-100 bg-slate-50/50">
                    <th className="px-4 py-3 text-left text-xs font-semibold text-slate-700 uppercase tracking-wide">
                      Tên đề
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-semibold text-slate-700 uppercase tracking-wide">
                      Người tạo
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-semibold text-slate-700 uppercase tracking-wide">
                      Số câu
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-semibold text-slate-700 uppercase tracking-wide">
                      Trạng thái
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-semibold text-slate-700 uppercase tracking-wide">
                      Quality
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-semibold text-slate-700 uppercase tracking-wide">
                      Thời gian
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {exams.length === 0 ? (
                    <tr>
                      <td
                        colSpan={7}
                        className="py-12 text-center text-sm text-slate-400"
                      >
                        Không có đề thi nào
                      </td>
                    </tr>
                  ) : (
                    exams.map((exam) => (
                      <tr
                        key={exam.id}
                        className="hover:bg-slate-50/60 transition-colors"
                      >
                        <td className="px-4 py-3 font-medium text-slate-800">
                          {formatExamDisplayName(exam.exam_name)}
                        </td>
                        <td className="px-4 py-3 text-slate-500">
                          {exam.created_by}
                        </td>
                        <td className="px-4 py-3 text-slate-700">
                          {exam.n_questions ?? "—"}
                        </td>
                        <td className="px-4 py-3">
                          {statusBadge(exam.status)}
                        </td>
                        <td className="px-4 py-3 text-slate-700">
                          {exam.quality_avg?.toFixed(2) ?? "—"}
                        </td>
                        <td className="px-4 py-3 text-slate-400 text-xs">
                          {formatDate(exam.created_at)}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>

              {/* Total count */}
              {exams.length > 0 && (
                <div className="flex items-center justify-center border-t border-slate-100 py-3">
                  <span className="text-xs text-slate-500">
                    Hiển thị {exams.length} / {exams.length} đề thi
                  </span>
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* System tab */}
        <TabsContent value="system" className="mt-2">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <Card className="border-slate-200 shadow-sm">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-semibold text-slate-700">
                  Trang thái hệ thống
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-2 text-sm">
                {[
                  {
                    label: "Trạng thái",
                    value: (
                      <Badge
                        variant="outline"
                        className="bg-white border-slate-200 text-slate-700 font-medium"
                      >
                        {stats?.queue?.status === "idle"
                          ? "Idle"
                          : stats?.queue?.status}
                      </Badge>
                    ),
                  },
                  {
                    label: "Jobs trong hệ thống",
                    value: stats?.queue?.pending_jobs,
                  },
                  { label: "Đang chạy", value: stats?.queue?.active_jobs || 0 },
                  { label: "Đang chờ", value: stats?.queue?.queued_jobs || 0 },
                  {
                    label: "Ước tính thời gian",
                    value: `${stats?.queue?.estimated_wait_min} phút`,
                  },
                ].map((row) => (
                  <div
                    key={row.label}
                    className="flex justify-between items-center py-1 border-b border-slate-50 last:border-0"
                  >
                    <span className="text-slate-500">{row.label}</span>
                    <strong className="text-slate-700">{row.value}</strong>
                  </div>
                ))}
                <Button
                  onClick={handleWarmup}
                  disabled={warmup.status === "running"}
                  className="w-full mt-3 h-9 text-sm bg-blue-500 hover:bg-blue-600 text-white"
                >
                  ▶ Warm up hệ thống
                </Button>
                {warmup.status !== "idle" && (
                  <p className="text-xs text-slate-500 text-center">
                    {warmup.status === "running" &&
                      `${warmup.progress}% • ${warmup.step}`}
                    {warmup.status === "success" && warmup.step}
                    {warmup.status === "failed" && warmup.error}
                  </p>
                )}
              </CardContent>
            </Card>

            <Card className="border-slate-200 shadow-sm">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-semibold text-slate-700">
                  Liên kết nhanh
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-1">
                {[
                  { label: "API Docs", url: "http://localhost:7860/docs" },
                  { label: "Phoenix Monitor", url: "http://localhost:6006" },
                  { label: "Grafana", url: "http://localhost:3001" },
                  { label: "Flower Queue", url: "http://localhost:5555" },
                  { label: "Prometheus", url: "http://localhost:9090" },
                ].map((link) => (
                  <a
                    key={link.label}
                    href={link.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center justify-between rounded-lg px-3 py-2 hover:bg-slate-50 text-sm text-blue-500 hover:text-blue-600 transition-colors"
                  >
                    <span>{link.label}</span>
                    <span className="text-blue-400 text-xs">↗</span>
                  </a>
                ))}
              </CardContent>
            </Card>
          </div>
        </TabsContent>
      </Tabs>
    </div>
  );
}
