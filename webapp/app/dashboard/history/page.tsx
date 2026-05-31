"use client";
import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { formatExamDisplayName } from "@/lib/exam-name";
import { StudySummary } from "@/types";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { toast } from "sonner";
import {
  BarChart3,
  BookOpen,
  Eye,
  FileText,
  Layers,
  PlayCircle,
  RefreshCw,
  Target,
  Trash2,
  XCircle,
  Clock,
  CheckCircle2,
  ClipboardList,
} from "lucide-react";

interface Exam {
  id: string;
  task_id: string;
  exam_name: string;
  n_questions: number;
  requested_questions?: number;
  accepted_questions?: number;
  failed_questions?: number;
  status: string;
  created_at: string;
  completed_at: string | null;
  quality_avg: number | null;
  created_by: string;
  failures?: unknown[];
}

const INITIAL_VISIBLE = 3;

export default function HistoryPage() {
  const router = useRouter();
  const [exams, setExams] = useState<Exam[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<Exam | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [summary, setSummary] = useState<StudySummary | null>(null);
  const [showAll, setShowAll] = useState(false);

  const loadHistory = useCallback(
    async (options: { showSuccess?: boolean; setBusy?: boolean } = {}) => {
      if (options.setBusy) setRefreshing(true);
      try {
        const [historyRes, summaryRes] = await Promise.all([
          api.get("/history"),
          api.get("/analytics/study-summary"),
        ]);
        setExams(historyRes.data.exams || []);
        setSummary(summaryRes.data);
        if (options.showSuccess) toast.success("Đã làm mới lịch sử");
      } catch {
        toast.error("Không tải được lịch sử");
      } finally {
        setLoading(false);
        if (options.setBusy) setRefreshing(false);
      }
    },
    [],
  );

  useEffect(() => {
    if (!localStorage.getItem("access_token")) {
      router.push("/login");
      return;
    }
    const timer = window.setTimeout(() => {
      void loadHistory();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [loadHistory, router]);

  useEffect(() => {
    if (!exams.some((exam) => exam.status === "pending")) return;
    const interval = window.setInterval(() => {
      void loadHistory();
    }, 5000);
    return () => window.clearInterval(interval);
  }, [exams, loadHistory]);

  const handleRefresh = () => {
    void loadHistory({ showSuccess: true, setBusy: true });
  };

  const handleDownload = async (taskId: string, examName: string) => {
    try {
      const { data } = await api.get(
        `/export/pdf/${taskId}?include_answers=false`,
        { responseType: "blob" },
      );
      const a = document.createElement("a");
      a.href = URL.createObjectURL(data);
      a.download = `${examName}_exam.pdf`;
      a.click();
    } catch {
      toast.error("Lỗi tải PDF");
    }
  };

  const handleViewResults = async (taskId: string) => {
    try {
      await api.get(`/results/${taskId}`);
      router.push(`/dashboard/exam/${taskId}`);
    } catch {
      toast.error("Không tải được kết quả đề thi");
    }
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    setDeletingId(deleteTarget.task_id);
    try {
      await api.delete(`/history/${deleteTarget.task_id}`);
      setExams((items) =>
        items.filter((exam) => exam.task_id !== deleteTarget.task_id),
      );
      setDeleteTarget(null);
      toast.success("Đã xoá lịch sử đề thi");
    } catch {
      toast.error("Không xoá được lịch sử đề thi");
    } finally {
      setDeletingId(null);
    }
  };

  const formatDate = (s: string) =>
    new Date(s).toLocaleString("vi-VN", {
      dateStyle: "short",
      timeStyle: "short",
    });

  const statusConfig = (s: string) => {
    if (s === "success")
      return {
        label: "Hoàn thành",
        className: "bg-emerald-50 text-emerald-700 border-emerald-200",
        icon: <CheckCircle2 size={11} />,
      };
    if (s === "pending" || s === "running")
      return {
        label: "Đang xử lý",
        className: "bg-amber-50 text-amber-700 border-amber-200",
        icon: <Clock size={11} />,
      };
    if (s === "cancelled")
      return {
        label: "Đã huỷ",
        className: "bg-slate-100 text-slate-500 border-slate-200",
        icon: <XCircle size={11} />,
      };
    return {
      label: "Thất bại",
      className: "bg-red-50 text-red-600 border-red-200",
      icon: <XCircle size={11} />,
    };
  };

  const topChapter = summary?.top_wrong_chapters?.[0];
  const topTopic = summary?.top_wrong_topics?.[0];

  const visibleExams = showAll ? exams : exams.slice(0, INITIAL_VISIBLE);
  const hiddenCount = exams.length - INITIAL_VISIBLE;

  return (
    <div className="space-y-5 -mt-8">
      {/* Header */}
      <div className="sticky -top-8 -mx-8 flex flex-wrap items-center justify-between gap-3 border-b border-slate-200/70 bg-[#F4F7FC]/95 px-8 py-4 backdrop-blur dark:border-slate-700 dark:bg-slate-900/95">
        <div>
          <h1 className="text-3xl font-bold text-slate-800">Lịch sử đề thi</h1>
          <p className="text-sm text-slate-500 mt-0.5">Các đề thi đã sinh</p>
        </div>
        <Button
          type="button"
          onClick={handleRefresh}
          variant="outline"
          size="sm"
          disabled={refreshing}
          className="h-8 gap-1.5 text-xs border-slate-200"
        >
          <RefreshCw size={13} className={refreshing ? "animate-spin" : ""} />
          {refreshing ? "Đang làm mới" : ""}
        </Button>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-24 text-slate-400 text-sm">
          Đang tải...
        </div>
      ) : (
        <>
          {/* Stats Cards */}
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            {/* Lượt làm */}
            <Card className="border-slate-200 shadow-sm">
              <CardContent className="p-4">
                <div className="flex items-center gap-2 text-xs font-medium text-slate-500 mb-2">
                  <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-blue-100">
                    <BarChart3 size={14} className="text-blue-600" />
                  </div>
                  Lượt làm
                </div>
                <p className="text-3xl font-bold text-slate-800">
                  {summary?.total_attempts || 0}
                </p>
              </CardContent>
            </Card>

            {/* Điểm TB */}
            <Card className="border-slate-200 shadow-sm">
              <CardContent className="p-4">
                <div className="flex items-center gap-2 text-xs font-medium text-slate-500 mb-2">
                  <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-cyan-100">
                    <Target size={14} className="text-cyan-600" />
                  </div>
                  Điểm TB
                </div>
                <p className="text-3xl font-bold text-blue-600">
                  {summary?.average_score?.toFixed(1) || "0.0"}
                </p>
              </CardContent>
            </Card>

            {/* Chương cần ôn */}
            <Card className="border-slate-200 shadow-sm">
              <CardContent className="p-4">
                <div className="flex items-center gap-2 text-xs font-medium text-slate-500 mb-2">
                  <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-indigo-100">
                    <BookOpen size={14} className="text-indigo-600" />
                  </div>
                  Chương cần ôn
                </div>
                <p className="text-sm font-semibold leading-snug text-slate-800">
                  {topChapter?.label || "Chưa có dữ liệu"}
                </p>
                {topChapter && (
                  <p className="mt-1 text-xs text-red-500 font-medium">
                    {topChapter.wrong} câu sai • {topChapter.wrong_rate}%
                  </p>
                )}
              </CardContent>
            </Card>

            {/* Topic cần cải thiện */}
            <Card className="border-slate-200 shadow-sm">
              <CardContent className="p-4">
                <div className="flex items-center gap-2 text-xs font-medium text-slate-500 mb-2">
                  <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-purple-100">
                    <Layers size={14} className="text-purple-600" />
                  </div>
                  Topic cần cải thiện
                </div>
                <p className="text-sm font-semibold leading-snug text-slate-800">
                  {topTopic?.label || "Chưa có dữ liệu"}
                </p>
                {topTopic && (
                  <p className="mt-1 text-xs text-red-500 font-medium">
                    {topTopic.wrong} câu sai • {topTopic.wrong_rate}%
                  </p>
                )}
              </CardContent>
            </Card>
          </div>

          {/* Gợi ý cải thiện */}
          {summary && summary.total_attempts > 0 && (
            <Card className="border-slate-200 shadow-sm">
              <CardContent className="p-4">
                <div className="flex items-center gap-2 mb-3">
                  <span className="text-base">💡</span>
                  <p className="text-sm font-semibold text-slate-800">
                    Gợi ý cải thiện
                  </p>
                </div>
                <div className="grid grid-cols-1 gap-2 md:grid-cols-3">
                  {summary.recommendations.map((item) => (
                    <div
                      key={item}
                      className="rounded-xl border border-slate-200 bg-slate-50/80 px-3.5 py-2.5 text-sm leading-snug text-slate-600"
                    >
                      {item}
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}

          {/* Exam list */}
          {exams.length === 0 ? (
            <Card className="border-slate-200 shadow-sm">
              <CardContent className="flex flex-col items-center justify-center gap-3 py-16">
                <div className="text-5xl">📭</div>
                <p className="text-slate-500">Chưa có đề thi nào</p>
                <Button onClick={() => router.push("/dashboard/generate")}>
                  ⚡ Sinh đề thi đầu tiên
                </Button>
              </CardContent>
            </Card>
          ) : (
            <Card className="border-slate-200 shadow-sm overflow-hidden">
              <CardContent className="p-0">
                {/* List header */}
                <div className="px-5 py-3.5 border-b border-slate-100">
                  <p className="text-sm font-semibold text-slate-700">
                    Danh sách đề thi
                  </p>
                </div>

                {/* Exam rows */}
                <div className="divide-y divide-slate-100">
                  {visibleExams.map((exam) => {
                    const displayName = formatExamDisplayName(exam.exam_name);
                    const status = statusConfig(exam.status);
                    return (
                      <div
                        key={exam.id}
                        className="flex items-center gap-3 px-5 py-3.5 hover:bg-slate-50/70 transition-colors"
                      >
                        {/* Icon */}
                        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-blue-50 border border-blue-100">
                          <ClipboardList size={16} className="text-blue-500" />
                        </div>

                        {/* Info */}
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 flex-wrap">
                            <span className="text-sm font-semibold text-slate-800">
                              {displayName}
                            </span>
                            <Badge
                              variant="outline"
                              className={`flex items-center gap-1 text-[11px] px-1.5 py-0 h-5 font-medium shrink-0 ${status.className}`}
                            >
                              {status.icon}
                              {status.label}
                            </Badge>
                          </div>
                          <div className="flex gap-3 mt-0.5 text-xs text-slate-400 flex-wrap items-center">
                            <span className="flex items-center gap-1">
                              <span>📋</span>
                              {exam.n_questions} câu hỏi
                            </span>
                            {exam.failed_questions ? (
                              <span className="flex items-center gap-1">
                                <span>⊘</span>
                                {exam.failed_questions} câu sai
                              </span>
                            ) : null}
                            <span className="flex items-center gap-1">
                              <Clock size={11} />
                              {formatDate(exam.created_at)}
                            </span>
                          </div>
                        </div>

                        {/* Actions */}
                        <div className="flex items-center gap-1.5 shrink-0">
                          {exam.status === "success" && (
                            <>
                              <Button
                                size="sm"
                                variant="outline"
                                className="h-8 gap-1.5 text-xs border-slate-200 hover:border-slate-300"
                                onClick={() => handleViewResults(exam.task_id)}
                              >
                                <Eye size={13} />
                                Xem
                              </Button>
                              <Button
                                size="sm"
                                className="h-8 gap-1.5 text-xs bg-blue-600 hover:bg-blue-700"
                                onClick={() =>
                                  router.push(`/dashboard/take/${exam.task_id}`)
                                }
                              >
                                <PlayCircle size={13} />
                                Làm đề
                              </Button>
                              <Button
                                size="sm"
                                variant="outline"
                                className="h-8 gap-1.5 text-xs border-slate-200 hover:border-slate-300"
                                onClick={() =>
                                  handleDownload(exam.task_id, displayName)
                                }
                              >
                                <FileText size={13} />
                                Đề
                              </Button>
                            </>
                          )}
                          <Button
                            size="sm"
                            variant="outline"
                            aria-label={`Xoá lịch sử ${displayName}`}
                            className="h-8 w-8 p-0 border-slate-200 text-slate-400 hover:text-red-500 hover:border-red-200 hover:bg-red-50"
                            onClick={() => setDeleteTarget(exam)}
                          >
                            <Trash2 size={13} />
                          </Button>
                        </div>
                      </div>
                    );
                  })}
                </div>

                {/* Show more / less */}
                {exams.length > INITIAL_VISIBLE && (
                  <button
                    onClick={() => setShowAll((v) => !v)}
                    className="w-full py-3 text-xs text-slate-500 hover:text-slate-700 hover:bg-slate-50 transition-colors border-t border-slate-100 font-medium"
                  >
                    {showAll
                      ? "Thu gọn"
                      : `Hiển thị ${Math.min(INITIAL_VISIBLE, exams.length)} đề thi · Xem thêm ${hiddenCount} đề`}
                  </button>
                )}
              </CardContent>
            </Card>
          )}
        </>
      )}

      {/* Delete confirmation dialog */}
      <Dialog
        open={!!deleteTarget}
        onOpenChange={(open) => !open && setDeleteTarget(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Xoá lịch sử đề thi</DialogTitle>
            <DialogDescription>
              Thao tác này sẽ xoá đề, câu hỏi đã lưu và các lượt làm bài liên
              quan khỏi lịch sử.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setDeleteTarget(null)}
              disabled={!!deletingId}
            >
              Huỷ
            </Button>
            <Button
              variant="destructive"
              onClick={handleDelete}
              disabled={!!deletingId}
            >
              <Trash2 size={14} />
              {deletingId ? "Đang xoá..." : "Xoá"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
