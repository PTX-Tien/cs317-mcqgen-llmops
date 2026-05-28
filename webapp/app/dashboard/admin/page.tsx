"use client"
import { useEffect, useState } from "react"
import { useRouter } from "next/navigation"
import { api } from "@/lib/api"
import { formatExamDisplayName } from "@/lib/exam-name"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { toast } from "sonner"

interface QueueStatus {
  status: "idle" | "busy"
  pending_jobs: number
  active_jobs?: number
  queued_jobs?: number
  estimated_wait_min: number
}

interface ExamSummary {
  id: number
  exam_name: string
  created_by: string
  n_questions?: number
  status: string
  quality_avg?: number | null
  created_at: string
}

interface AdminStats {
  total_exams: number
  success_exams: number
  total_questions: number
  avg_quality: number
  queue: QueueStatus
}

interface WarmupState {
  status: "idle" | "running" | "success" | "failed"
  progress: number
  step: string
  error?: string
}

interface WarmupStatusResponse {
  state: string
  progress?: number
  step?: string
  error?: string
  ready?: boolean
}

const sleep = (ms: number) => new Promise((resolve) => window.setTimeout(resolve, ms))

export default function AdminPage() {
  const router    = useRouter()
  const [stats, setStats]   = useState<AdminStats | null>(null)
  const [exams, setExams]   = useState<ExamSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [warmup, setWarmup] = useState<WarmupState>({
    status: "idle",
    progress: 0,
    step: "",
  })

  useEffect(() => {
    const token = localStorage.getItem("access_token")
    if (!token) { router.push("/login"); return }

    let cancelled = false
    const loadData = async () => {
      try {
        const [histRes, queueRes] = await Promise.all([
          api.get("/history"),
          api.get("/queue/status"),
        ])
        if (cancelled) return
        const history: ExamSummary[] = histRes.data.exams || []
        const qualityScores = history
          .map((exam) => exam.quality_avg)
          .filter((score): score is number => typeof score === "number")
        setExams(history)
        setStats({
          total_exams:     history.length,
          success_exams:   history.filter((exam) => exam.status === "success").length,
          total_questions: history.reduce((sum, exam) => sum + (exam.n_questions || 0), 0),
          avg_quality:     qualityScores.length
            ? qualityScores.reduce((sum, score) => sum + score, 0) / qualityScores.length
            : 0,
          queue:           queueRes.data,
        })
      } catch {
        if (!cancelled) toast.error("Lỗi tải dữ liệu")
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    loadData()
    return () => { cancelled = true }
  }, [router])

  const formatDate = (s: string) =>
    new Date(s).toLocaleString("vi-VN", { dateStyle: "short", timeStyle: "short" })

  const handleWarmup = async () => {
    setWarmup({ status: "running", progress: 0, step: "Đang gửi warmup job" })
    try {
      const { data } = await api.post("/admin/warmup")
      const taskId = data.task_id
      const deadline = Date.now() + 15 * 60 * 1000

      while (Date.now() < deadline) {
        await sleep(2000)
        const statusRes = await api.get<WarmupStatusResponse>(`/status/${taskId}`)
        const status = statusRes.data
        if (status.state === "running") {
          setWarmup({
            status: "running",
            progress: status.progress ?? 0,
            step: status.step || "Đang warm up",
          })
        } else if (status.state === "success") {
          setWarmup({
            status: "success",
            progress: 100,
            step: status.ready ? "Hệ thống đã sẵn sàng" : "Warmup hoàn tất",
          })
          toast.success("Warmup hoàn tất")
          return
        } else if (status.state === "failed") {
          throw new Error(status.error || "Warmup thất bại")
        }
      }
      throw new Error("Warmup timeout")
    } catch (error) {
      const message = error instanceof Error ? error.message : "Warmup thất bại"
      setWarmup({ status: "failed", progress: 0, step: "", error: message })
      toast.error(message)
    }
  }

  if (loading) return <div className="text-center py-20 text-slate-400">Đang tải...</div>

  return (
    <div className="space-y-6">
      <div className="sticky top-0 z-30 -mx-8 -mt-8 border-b border-slate-200/70 bg-[#F4F7FC]/95 px-8 py-4 backdrop-blur dark:border-slate-700 dark:bg-slate-900/95">
        <h1 className="text-2xl font-bold">⚙️ Admin Dashboard</h1>
        <p className="text-slate-500 text-sm">Quản lý hệ thống và dữ liệu</p>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {[
          { label: "Tổng đề thi", value: stats?.total_exams, icon: "📋" },
          { label: "Hoàn thành", value: stats?.success_exams, icon: "✅" },
          { label: "Tổng câu hỏi", value: stats?.total_questions, icon: "❓" },
          { label: "Quality avg", value: stats?.avg_quality?.toFixed(2) || "—", icon: "⭐" },
        ].map((s) => (
          <Card key={s.label}>
            <CardContent className="p-4 text-center">
              <div className="text-3xl mb-1">{s.icon}</div>
              <div className="text-2xl font-bold">{s.value}</div>
              <div className="text-xs text-slate-500">{s.label}</div>
            </CardContent>
          </Card>
        ))}
      </div>

      <Tabs defaultValue="exams">
        <TabsList>
          <TabsTrigger value="exams">📋 Đề thi ({exams.length})</TabsTrigger>
          <TabsTrigger value="system">🔧 Hệ thống</TabsTrigger>
        </TabsList>

        <TabsContent value="exams" className="space-y-2 mt-4">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left text-slate-500">
                  <th className="pb-2 pr-4">Tên đề</th>
                  <th className="pb-2 pr-4">Người tạo</th>
                  <th className="pb-2 pr-4">Số câu</th>
                  <th className="pb-2 pr-4">Trạng thái</th>
                  <th className="pb-2 pr-4">Quality</th>
                  <th className="pb-2">Thời gian</th>
                </tr>
              </thead>
              <tbody>
                {exams.map((exam) => (
                  <tr key={exam.id} className="border-b hover:bg-slate-50">
                    <td className="py-2 pr-4 font-medium">{formatExamDisplayName(exam.exam_name)}</td>
                    <td className="py-2 pr-4 text-slate-500">{exam.created_by}</td>
                    <td className="py-2 pr-4">{exam.n_questions}</td>
                    <td className="py-2 pr-4">
                      <Badge variant={exam.status === "success" ? "default" : "secondary"} className="text-xs">
                        {exam.status}
                      </Badge>
                    </td>
                    <td className="py-2 pr-4">{exam.quality_avg?.toFixed(2) || "—"}</td>
                    <td className="py-2 text-slate-500 text-xs">{formatDate(exam.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </TabsContent>

        <TabsContent value="system" className="mt-4">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <Card>
              <CardHeader><CardTitle className="text-sm">Queue Status</CardTitle></CardHeader>
              <CardContent className="space-y-2 text-sm">
                <div className="flex justify-between">
                  <span>Trạng thái</span>
                  <Badge variant={stats?.queue?.status === "idle" ? "default" : "secondary"}>
                    {stats?.queue?.status}
                  </Badge>
                </div>
                <div className="flex justify-between">
                  <span>Jobs trong hệ thống</span>
                  <strong>{stats?.queue?.pending_jobs}</strong>
                </div>
                <div className="flex justify-between">
                  <span>Đang chạy</span>
                  <strong>{stats?.queue?.active_jobs || 0}</strong>
                </div>
                <div className="flex justify-between">
                  <span>Đang chờ</span>
                  <strong>{stats?.queue?.queued_jobs || 0}</strong>
                </div>
                <div className="flex justify-between">
                  <span>Ước tính</span>
                  <strong>{stats?.queue?.estimated_wait_min} phút</strong>
                </div>
                <Button
                  onClick={handleWarmup}
                  disabled={warmup.status === "running"}
                  className="w-full mt-3"
                >
                  Warm up hệ thống
                </Button>
                {warmup.status !== "idle" && (
                  <div className="text-xs text-slate-500">
                    {warmup.status === "running" && `${warmup.progress}% • ${warmup.step}`}
                    {warmup.status === "success" && warmup.step}
                    {warmup.status === "failed" && warmup.error}
                  </div>
                )}
              </CardContent>
            </Card>
            <Card>
              <CardHeader><CardTitle className="text-sm">External Links</CardTitle></CardHeader>
              <CardContent className="space-y-2">
                {[
                  { label: "API Docs", url: "http://localhost:7860/docs" },
                  { label: "Phoenix Monitor", url: "http://localhost:6006" },
                  { label: "Grafana", url: "http://localhost:3001" },
                  { label: "Flower Queue", url: "http://localhost:5555" },
                  { label: "Prometheus", url: "http://localhost:9090" },
                ].map((link) => (
                  <a key={link.label} href={link.url} target="_blank"
                    className="flex items-center justify-between p-2 rounded hover:bg-slate-50 text-sm">
                    <span>{link.label}</span>
                    <span className="text-blue-500">↗</span>
                  </a>
                ))}
              </CardContent>
            </Card>
          </div>
        </TabsContent>
      </Tabs>
    </div>
  )
}
