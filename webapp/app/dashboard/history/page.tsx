"use client"
import { useEffect, useState } from "react"
import { useRouter } from "next/navigation"
import { api } from "@/lib/api"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { toast } from "sonner"

interface Exam {
  id: string
  task_id: string
  exam_name: string
  n_questions: number
  status: string
  created_at: string
  completed_at: string | null
  quality_avg: number | null
  created_by: string
}

export default function HistoryPage() {
  const router = useRouter()
  const [exams, setExams] = useState<Exam[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!localStorage.getItem("access_token")) { router.push("/login"); return }
    loadHistory()
  }, [])

  const loadHistory = async () => {
    try {
      const { data } = await api.get("/history")
      setExams(data.exams || [])
    } catch { toast.error("Không tải được lịch sử") }
    finally { setLoading(false) }
  }

  const handleDownload = async (taskId: string, examName: string, withAnswers: boolean) => {
    try {
      const { data } = await api.get(
        `/export/pdf/${taskId}?include_answers=${withAnswers}`,
        { responseType: "blob" }
      )
      const a = document.createElement("a")
      a.href = URL.createObjectURL(data)
      a.download = `${examName}_${withAnswers ? "answers" : "exam"}.pdf`
      a.click()
    } catch { toast.error("Lỗi tải PDF") }
  }

  const handleViewResults = async (taskId: string) => {
    try {
      await api.get(`/results/${taskId}`)
      router.push(`/dashboard/exam/${taskId}`)
    } catch { toast.error("Không tải được kết quả — job có thể đã hết hạn") }
  }

  const formatDate = (s: string) =>
    new Date(s).toLocaleString("vi-VN", { dateStyle: "short", timeStyle: "short" })

  const statusColor = (s: string) =>
    s === "success" ? "default" : s === "pending" ? "secondary" : "destructive"

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-800">📋 Lịch sử đề thi</h1>
          <p className="text-slate-500 text-sm mt-1">Các đề thi đã sinh</p>
        </div>
        <Button onClick={loadHistory} variant="outline" size="sm">🔄 Làm mới</Button>
      </div>

      {loading ? (
        <div className="text-center py-20 text-slate-400">Đang tải...</div>
      ) : exams.length === 0 ? (
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
          {exams.map((exam) => (
            <Card key={exam.id} className="hover:shadow-md transition-shadow">
              <CardContent className="p-4">
                <div className="flex items-start justify-between gap-4">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <h3 className="font-semibold text-slate-800 truncate">{exam.exam_name}</h3>
                      <Badge variant={statusColor(exam.status)} className="text-xs shrink-0">
                        {exam.status === "success" ? "✅ Hoàn thành" :
                         exam.status === "pending" ? "⏳ Đang xử lý" : "❌ Thất bại"}
                      </Badge>
                    </div>
                    <div className="flex gap-4 mt-1 text-sm text-slate-500 flex-wrap">
                      <span>📝 {exam.n_questions} câu hỏi</span>
                      {exam.quality_avg && <span>⭐ Score: {exam.quality_avg.toFixed(2)}</span>}
                      <span>🕐 {formatDate(exam.created_at)}</span>
                    </div>
                  </div>
                  {exam.status === "success" && (
                    <div className="flex gap-2 shrink-0 flex-wrap justify-end">
                      <Button size="sm" variant="outline"
                        onClick={() => handleViewResults(exam.task_id)}>
                        👁 Xem
                      </Button>
                      <Button size="sm" variant="outline"
                        onClick={() => handleDownload(exam.task_id, exam.exam_name, false)}>
                        📋 Đề
                      </Button>
                      <Button size="sm" variant="outline"
                        onClick={() => handleDownload(exam.task_id, exam.exam_name, true)}>
                        🔑 Đáp án
                      </Button>
                    </div>
                  )}
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}
