"use client"
import { useEffect, useState } from "react"
import { useRouter } from "next/navigation"
import Link from "next/link"
import { useAuthStore } from "@/lib/store"
import { api } from "@/lib/api"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"

export default function DashboardPage() {
  const router = useRouter()
  const { user, setAuth } = useAuthStore()
  const [queueStatus, setQueueStatus] = useState<any>(null)

  useEffect(() => {
    const token = localStorage.getItem("access_token")
    if (!token) { router.push("/login"); return }
    // Restore user from token if page refreshed
    if (!user) {
      api.get("/auth/me").then(({ data }) => {
        setAuth({ username: data.username, role: data.role, full_name: data.full_name }, token)
      }).catch(() => router.push("/login"))
    }
    // Load queue status
    api.get("/queue/status").then(({ data }) => setQueueStatus(data)).catch(() => {})
  }, [])

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold text-slate-800">
          Xin chào, {user?.full_name || "..."} 👋
        </h1>
        <p className="text-slate-500 mt-1">
          Hệ thống sinh câu hỏi trắc nghiệm tự động — CS116
        </p>
      </div>

      {/* Stats cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-slate-500">Queue Status</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex items-center gap-2">
              <div className={`w-3 h-3 rounded-full ${queueStatus?.status === "idle" ? "bg-green-500" : "bg-yellow-500"}`} />
              <span className="text-2xl font-bold">
                {queueStatus?.status === "idle" ? "Sẵn sàng" : `${queueStatus?.pending_jobs} job đang chờ`}
              </span>
            </div>
            {queueStatus?.pending_jobs > 0 && (
              <p className="text-sm text-slate-500 mt-1">Ước tính ~{queueStatus.estimated_wait_min} phút</p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-slate-500">Model</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-xl font-bold">Qwen3-8B-AWQ</p>
            <p className="text-sm text-slate-500">RTX 2080 Ti 11GB</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-slate-500">RAG Strategy</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-xl font-bold">Adaptive RAG</p>
            <p className="text-sm text-slate-500">HyDE + SW + CrossEncoder</p>
          </CardContent>
        </Card>
      </div>

      {/* Quick actions */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Card className="border-2 border-dashed border-slate-200 hover:border-slate-400 transition-colors">
          <CardContent className="p-6 text-center space-y-3">
            <div className="text-5xl">⚡</div>
            <h3 className="text-xl font-semibold">Sinh câu hỏi mới</h3>
            <p className="text-slate-500 text-sm">
              Chọn topic, độ khó và số câu hỏi cần sinh
            </p>
            <Link href="/dashboard/generate">
              <Button className="w-full">Bắt đầu →</Button>
            </Link>
          </CardContent>
        </Card>

        <Card className="border-2 border-dashed border-slate-200 hover:border-slate-400 transition-colors">
          <CardContent className="p-6 text-center space-y-3">
            <div className="text-5xl">📋</div>
            <h3 className="text-xl font-semibold">Lịch sử đề thi</h3>
            <p className="text-slate-500 text-sm">
              Xem và tải lại các đề thi đã sinh trước đây
            </p>
            <Link href="/dashboard/history">
              <Button variant="outline" className="w-full">Xem lịch sử →</Button>
            </Link>
          </CardContent>
        </Card>
      </div>

      {/* System info */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-medium text-slate-500">Links hệ thống</CardTitle>
        </CardHeader>
        <CardContent className="flex gap-3 flex-wrap">
          <a href="http://localhost:7860/docs" target="_blank">
            <Button variant="outline" size="sm">🔧 API Docs</Button>
          </a>
          <a href="http://localhost:6006" target="_blank">
            <Button variant="outline" size="sm">📈 Phoenix Monitor</Button>
          </a>
          <a href="http://localhost:3001" target="_blank">
            <Button variant="outline" size="sm">📊 Grafana</Button>
          </a>
          <a href="http://localhost:5555" target="_blank">
            <Button variant="outline" size="sm">🌸 Flower Queue</Button>
          </a>
        </CardContent>
      </Card>
    </div>
  )
}
