"use client"
import { useCallback, useEffect, useState } from "react"
import { useRouter } from "next/navigation"
import { api } from "@/lib/api"
import { formatExamDisplayName } from "@/lib/exam-name"
import { StudySummary } from "@/types"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { toast } from "sonner"
import { BarChart3, Eye, FileText, PlayCircle, RefreshCw, Target, Trash2 } from "lucide-react"

interface Exam {
  id: string
  task_id: string
  exam_name: string
  n_questions: number
  requested_questions?: number
  accepted_questions?: number
  failed_questions?: number
  status: string
  created_at: string
  completed_at: string | null
  quality_avg: number | null
  created_by: string
  failures?: unknown[]
}

export default function HistoryPage() {
  const router = useRouter()
  const [exams, setExams] = useState<Exam[]>([])
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<Exam | null>(null)
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [summary, setSummary] = useState<StudySummary | null>(null)

  const loadHistory = useCallback(async (options: { showSuccess?: boolean; setBusy?: boolean } = {}) => {
    if (options.setBusy) setRefreshing(true)
    try {
      const [historyRes, summaryRes] = await Promise.all([
        api.get("/history"),
        api.get("/analytics/study-summary"),
      ])
      setExams(historyRes.data.exams || [])
      setSummary(summaryRes.data)
      if (options.showSuccess) toast.success("Đã làm mới lịch sử")
    } catch { toast.error("Không tải được lịch sử") }
    finally {
      setLoading(false)
      if (options.setBusy) setRefreshing(false)
    }
  }, [])

  useEffect(() => {
    if (!localStorage.getItem("access_token")) { router.push("/login"); return }
    const timer = window.setTimeout(() => {
      void loadHistory()
    }, 0)
    return () => window.clearTimeout(timer)
  }, [loadHistory, router])

  useEffect(() => {
    if (!exams.some((exam) => exam.status === "pending")) return
    const interval = window.setInterval(() => {
      void loadHistory()
    }, 5000)
    return () => window.clearInterval(interval)
  }, [exams, loadHistory])

  const handleRefresh = () => {
    void loadHistory({ showSuccess: true, setBusy: true })
  }

  const handleDownload = async (taskId: string, examName: string) => {
    try {
      const { data } = await api.get(
        `/export/pdf/${taskId}?include_answers=false`,
        { responseType: "blob" }
      )
      const a = document.createElement("a")
      a.href = URL.createObjectURL(data)
      a.download = `${examName}_exam.pdf`
      a.click()
    } catch { toast.error("Lỗi tải PDF") }
  }

  const handleViewResults = async (taskId: string) => {
    try {
      await api.get(`/results/${taskId}`)
      router.push(`/dashboard/exam/${taskId}`)
    } catch { toast.error("Không tải được kết quả đề thi") }
  }

  const handleDelete = async () => {
    if (!deleteTarget) return
    setDeletingId(deleteTarget.task_id)
    try {
      await api.delete(`/history/${deleteTarget.task_id}`)
      setExams((items) => items.filter((exam) => exam.task_id !== deleteTarget.task_id))
      setDeleteTarget(null)
      toast.success("Đã xoá lịch sử đề thi")
    } catch { toast.error("Không xoá được lịch sử đề thi") }
    finally { setDeletingId(null) }
  }

  const formatDate = (s: string) =>
    new Date(s).toLocaleString("vi-VN", { dateStyle: "short", timeStyle: "short" })

  const statusBadgeClass = (s: string) =>
    s === "success" ? "border-emerald-200 bg-emerald-50 text-emerald-700" :
    s === "pending" || s === "running" ? "border-amber-200 bg-amber-50 text-amber-700" :
    s === "cancelled" ? "border-slate-200 bg-slate-100 text-slate-600" :
    "border-red-200 bg-red-50 text-red-700"

  const statusLabel = (s: string) =>
    s === "success" ? "Hoàn thành" :
    s === "pending" || s === "running" ? "Đang xử lý" :
    s === "cancelled" ? "Đã huỷ" : "Thất bại"

  const topChapter = summary?.top_wrong_chapters?.[0]
  const topTopic = summary?.top_wrong_topics?.[0]

  return (
    <div className="space-y-6">
      <div className="sticky top-0 z-30 -mx-8 -mt-8 flex flex-wrap items-center justify-between gap-3 border-b border-slate-200/70 bg-[#F4F7FC]/95 px-8 py-4 backdrop-blur dark:border-slate-700 dark:bg-slate-900/95">
        <div>
          <h1 className="text-2xl font-bold text-slate-800">📋 Lịch sử đề thi</h1>
          <p className="text-slate-500 text-sm mt-1">Các đề thi đã sinh</p>
        </div>
        <Button type="button" onClick={handleRefresh} variant="outline" size="sm" disabled={refreshing}>
          <RefreshCw size={14} className={refreshing ? "animate-spin" : ""} />
          {refreshing ? "Đang làm mới" : "Làm mới"}
        </Button>
      </div>

      {loading ? (
        <div className="text-center py-20 text-slate-400">Đang tải...</div>
      ) : (
        <>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
          <Card>
            <CardContent className="p-4">
              <div className="flex items-center gap-2 text-xs uppercase text-slate-500"><BarChart3 size={14} />Lượt làm</div>
              <p className="mt-2 text-2xl font-bold text-slate-800">{summary?.total_attempts || 0}</p>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="p-4">
              <div className="flex items-center gap-2 text-xs uppercase text-slate-500"><Target size={14} />Điểm TB</div>
              <p className="mt-2 text-2xl font-bold text-blue-600">{summary?.average_score?.toFixed(1) || "0.0"}</p>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="p-4">
              <p className="text-xs uppercase text-slate-500">Chương cần ôn</p>
              <p className="mt-2 text-sm font-semibold leading-snug text-slate-800">{topChapter?.label || "Chưa có dữ liệu"}</p>
              {topChapter ? <p className="mt-1 text-xs text-red-600">{topChapter.wrong} câu sai • {topChapter.wrong_rate}%</p> : null}
            </CardContent>
          </Card>
          <Card>
            <CardContent className="p-4">
              <p className="text-xs uppercase text-slate-500">Topic cần cải thiện</p>
              <p className="mt-2 text-sm font-semibold leading-snug text-slate-800">{topTopic?.label || "Chưa có dữ liệu"}</p>
              {topTopic ? <p className="mt-1 text-xs text-red-600">{topTopic.wrong} câu sai • {topTopic.wrong_rate}%</p> : null}
            </CardContent>
          </Card>
        </div>

        {summary && summary.total_attempts > 0 ? (
          <Card>
            <CardContent className="p-4">
              <p className="text-sm font-semibold text-slate-800">Gợi ý cải thiện</p>
              <div className="mt-3 grid grid-cols-1 gap-2 md:grid-cols-3">
                {summary.recommendations.map((item) => (
                  <div key={item} className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm leading-snug text-slate-600">
                    {item}
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        ) : null}

        {exams.length === 0 ? (
        <Card>
          <CardContent className="text-center py-16 space-y-3">
            <div className="text-5xl">📭</div>
            <p className="text-slate-500">Chưa có đề thi nào</p>
            <Button onClick={() => router.push("/dashboard/generate")}>
              ⚡ Sinh đề thi đầu tiên
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-3">
          {exams.map((exam) => {
            const displayName = formatExamDisplayName(exam.exam_name)
            return (
              <Card key={exam.id} className="hover:shadow-md transition-shadow">
                <CardContent className="p-4">
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <h3 className="font-semibold text-slate-800 truncate">{displayName}</h3>
                        <Badge variant="outline" className={`text-xs shrink-0 ${statusBadgeClass(exam.status)}`}>
                          {statusLabel(exam.status)}
                        </Badge>
                      </div>
                      <div className="flex gap-4 mt-1 text-sm text-slate-500 flex-wrap">
                        <span>{exam.n_questions} câu hỏi</span>
                        {exam.failed_questions ? <span>{exam.failed_questions} câu bị loại</span> : null}
                        {exam.quality_avg && <span>⭐ Score: {exam.quality_avg.toFixed(2)}</span>}
                        <span>🕐 {formatDate(exam.created_at)}</span>
                      </div>
                    </div>
                    <div className="flex gap-2 shrink-0 flex-wrap justify-end">
                      {exam.status === "success" && (
                        <>
                        <Button size="sm" variant="outline"
                        onClick={() => handleViewResults(exam.task_id)}>
                        <Eye size={14} />Xem
                      </Button>
                      <Button size="sm"
                        onClick={() => router.push(`/dashboard/take/${exam.task_id}`)}>
                        <PlayCircle size={14} />Làm đề
                      </Button>
                      <Button size="sm" variant="outline"
                        onClick={() => handleDownload(exam.task_id, displayName)}>
                        <FileText size={14} />Đề
                      </Button>
                      </>
                    )}
                      <Button size="icon-sm" variant="destructive"
                        aria-label={`Xoá lịch sử ${displayName}`}
                        onClick={() => setDeleteTarget(exam)}>
                        <Trash2 size={14} />
                      </Button>
                    </div>
                  </div>
                </CardContent>
              </Card>
            )
          })}
        </div>
      )}
        </>
      )}

      <Dialog open={!!deleteTarget} onOpenChange={(open) => !open && setDeleteTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Xoá lịch sử đề thi</DialogTitle>
            <DialogDescription>
              Thao tác này sẽ xoá đề, câu hỏi đã lưu và các lượt làm bài liên quan khỏi lịch sử.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteTarget(null)} disabled={!!deletingId}>
              Huỷ
            </Button>
            <Button variant="destructive" onClick={handleDelete} disabled={!!deletingId}>
              <Trash2 size={14} />
              {deletingId ? "Đang xoá" : "Xoá"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
