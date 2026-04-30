"use client"
import { useState, useRef, useEffect } from "react"
import { useRouter } from "next/navigation"
import { useAuthStore } from "@/lib/store"
import { api, WS_URL } from "@/lib/api"
import { TopicConfig, MCQ, GenerationState } from "@/types"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Progress } from "@/components/ui/progress"
import { Badge } from "@/components/ui/badge"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { toast } from "sonner"

// ── Constants ────────────────────────────────────────────────────
const CHAPTERS: Record<string, string> = {
  ch02: "Ch02 — Popular Libraries (NumPy, Pandas)",
  ch03: "Ch03 — Pipeline & EDA",
  ch04: "Ch04 — Tiền xử lý dữ liệu",
  ch05: "Ch05 — Đánh giá mô hình",
  ch06: "Ch06 — Unsupervised Learning",
  ch07a: "Ch07a — Regression",
  ch07b: "Ch07b — Classification",
  ch08: "Ch08 — Deep Learning & CNN",
  ch09: "Ch09 — Parameter Tuning",
  ch10: "Ch10 — Ensemble Models",
  ch11: "Ch11 — Model Deployment",
}

const TOPIC_SUGGESTIONS: Record<string, string[]> = {
  ch04: ["SimpleImputer và KNNImputer trong sklearn", "dropna và fillna trong Pandas", "IQR method và Z-score để phát hiện outlier", "Isolation Forest outlier detection"],
  ch07b: ["Decision Trees", "Logistic Regression", "SVM"],
  ch08: ["CNN Neural Networks", "Convolution Layer", "Pooling Layer"],
  ch10: ["Random Forest", "Boosting", "Bagging"],
  ch02: ["NumPy array operations", "Pandas DataFrame"],
  ch05: ["Classification Metrics", "Cross-validation"],
  ch06: ["K-Means Clustering", "PCA"],
  ch07a: ["Linear Regression", "Regularization"],
  ch09: ["Grid Search", "Random Search"],
  ch11: ["Model Serving", "API Deployment"],
}

const PIPELINE_STEPS = [
  { label: "Retrieval", icon: "🔍" },
  { label: "Gen Stem", icon: "✍️" },
  { label: "Distractor", icon: "🎯" },
  { label: "Assemble", icon: "📝" },
  { label: "Evaluate", icon: "✅" },
]

// ── Topic Row component ──────────────────────────────────────────
function TopicRow({ index, topic, onChange, onRemove }: {
  index: number
  topic: TopicConfig
  onChange: (t: TopicConfig) => void
  onRemove: () => void
}) {
  const suggestions = TOPIC_SUGGESTIONS[topic.chapter_id] || []
  return (
    <Card className="p-4 space-y-3 bg-slate-50">
      <div className="flex items-center justify-between">
        <span className="font-medium text-sm text-slate-600">Topic {index + 1}</span>
        <Button variant="ghost" size="sm" onClick={onRemove} className="text-red-400 hover:text-red-600 h-7 px-2">✕</Button>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <div>
          <Label className="text-xs">Chapter</Label>
          <Select value={topic.chapter_id} onValueChange={(v) => onChange({ ...topic, chapter_id: v ?? "", topic: "" })}>
            <SelectTrigger className="h-9 mt-1">
              <SelectValue placeholder="Chọn chapter" />
            </SelectTrigger>
            <SelectContent>
              {Object.entries(CHAPTERS).map(([k, v]) => (
                <SelectItem key={k} value={k}>{v}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div>
          <Label className="text-xs">Topic cụ thể</Label>
          <Select value={topic.topic} onValueChange={(v) => onChange({ ...topic, topic: v ?? "" })}>
            <SelectTrigger className="h-9 mt-1">
              <SelectValue placeholder="Chọn hoặc nhập topic" />
            </SelectTrigger>
            <SelectContent>
              {suggestions.map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)}
            </SelectContent>
          </Select>
          <Input
            className="h-9 mt-1 text-xs"
            placeholder="Hoặc nhập tên topic..."
            value={topic.topic}
            onChange={(e) => onChange({ ...topic, topic: e.target.value })}
          />
        </div>
        <div className="flex gap-2">
          <div className="flex-1">
            <Label className="text-xs">Độ khó</Label>
            <Select value={topic.difficulty} onValueChange={(v) => onChange({ ...topic, difficulty: v ?? "G2" })}>
              <SelectTrigger className="h-9 mt-1">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="G1">G1 — Nhớ/Biết</SelectItem>
                <SelectItem value="G2">G2 — Hiểu/Áp dụng</SelectItem>
                <SelectItem value="G3">G3 — Phân tích</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="w-20">
            <Label className="text-xs">Số câu</Label>
            <Input
              type="number" min={1} max={5}
              className="h-9 mt-1 text-center"
              value={topic.n}
              onChange={(e) => onChange({ ...topic, n: parseInt(e.target.value) || 1 })}
            />
          </div>
        </div>
      </div>
    </Card>
  )
}

// ── Main page ────────────────────────────────────────────────────
export default function GeneratePage() {
  const router = useRouter()
  const { user } = useAuthStore()
  const [examName, setExamName] = useState("exam_01")
  const [topics, setTopics] = useState<TopicConfig[]>([
    { topic_id: "t1", chapter_id: "ch07b", topic: "Decision Trees", difficulty: "G2", n: 3 }
  ])
  const [genState, setGenState] = useState<GenerationState>({ status: "idle" })
  const [mcqs, setMcqs] = useState<MCQ[]>([])
  const wsRef = useRef<WebSocket | null>(null)
  const taskIdRef = useRef<string | null>(null)

  useEffect(() => {
    if (!localStorage.getItem("access_token")) router.push("/login")
  }, [])

  const totalQ = topics.reduce((s, t) => s + t.n, 0)
  const validTopics = topics.filter((t) => t.chapter_id && t.topic.trim())

  const addTopic = () => {
    if (topics.length >= 5) return
    setTopics([...topics, { topic_id: `t${topics.length + 1}`, chapter_id: "ch07b", topic: "", difficulty: "G2", n: 2 }])
  }

  const handleGenerate = async () => {
    if (validTopics.length === 0) { toast.error("Vui lòng thêm ít nhất 1 topic"); return }
    setGenState({ status: "submitting" })
    setMcqs([])
    try {
      const { data } = await api.post("/generate", { topics: validTopics, output_name: examName })
      taskIdRef.current = data.task_id
      setGenState({ status: "queued", position: data.queue_position, estimatedWait: data.estimated_wait_min, taskId: data.task_id })
      toast.success(`Job submitted! Position #${data.queue_position}`)
      startWebSocket(data.task_id)
    } catch (e: any) {
      setGenState({ status: "failed", error: e.response?.data?.detail || "Lỗi kết nối API" })
      toast.error("Không thể submit job")
    }
  }

  const startWebSocket = (taskId: string) => {
    const token = localStorage.getItem("access_token")
    const ws = new WebSocket(`${WS_URL}/ws/${taskId}`)
    wsRef.current = ws
    const start = Date.now()

    ws.onmessage = async (e) => {
      const msg = JSON.parse(e.data)
      if (msg.state === "running") {
        setGenState({ status: "running", progress: msg.progress, step: msg.step || "Generating...", currentQ: msg.current_question || 0, totalQ: msg.total_questions || totalQ, taskId })
      } else if (msg.state === "success") {
        try {
          const { data } = await api.get(`/results/${taskId}`)
          setMcqs(data.mcqs || [])
          setGenState({ status: "success", mcqs: data.mcqs, elapsed: (Date.now() - start) / 1000, taskId })
          toast.success(`✅ ${data.accepted} câu hỏi đã sinh thành công!`)
        } catch { setGenState({ status: "failed", error: "Lỗi lấy kết quả" }) }
        ws.close()
      } else if (msg.state === "failed") {
        setGenState({ status: "failed", error: msg.error || "Pipeline thất bại" })
        toast.error("Pipeline thất bại")
        ws.close()
      }
    }
    ws.onerror = () => pollFallback(taskId, start)
    ws.onclose = () => {}
  }

  const pollFallback = (taskId: string, start: number) => {
    const interval = setInterval(async () => {
      try {
        const { data } = await api.get(`/status/${taskId}`)
        if (data.state === "running") {
          setGenState({ status: "running", progress: data.progress, step: data.step || "Processing...", currentQ: data.current_question || 0, totalQ: data.total_questions || totalQ, taskId })
        } else if (data.state === "success") {
          clearInterval(interval)
          const res = await api.get(`/results/${taskId}`)
          setMcqs(res.data.mcqs)
          setGenState({ status: "success", mcqs: res.data.mcqs, elapsed: (Date.now() - start) / 1000, taskId })
          toast.success(`✅ ${res.data.accepted} câu hỏi đã sinh thành công!`)
        } else if (data.state === "failed") {
          clearInterval(interval)
          setGenState({ status: "failed", error: "Pipeline thất bại" })
        }
      } catch { clearInterval(interval) }
    }, 3000)
  }

  const handleCancel = async () => {
    if (taskIdRef.current) { await api.delete(`/cancel/${taskIdRef.current}`).catch(() => {}) }
    wsRef.current?.close()
    setGenState({ status: "idle" })
    toast.info("Job đã hủy")
  }

  const downloadJson = () => {
    const blob = new Blob([JSON.stringify(mcqs, null, 2)], { type: "application/json" })
    const a = document.createElement("a"); a.href = URL.createObjectURL(blob)
    a.download = `${examName}_mcqs.json`; a.click()
  }

  const downloadPdf = async (withAnswers: boolean) => {
    if (genState.status !== "success") return
    const { data } = await api.get(`/export/pdf/${genState.taskId}?include_answers=${withAnswers}`, { responseType: "blob" })
    const a = document.createElement("a"); a.href = URL.createObjectURL(data)
    a.download = `${examName}_${withAnswers ? "answers" : "exam"}.pdf`; a.click()
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-800">⚡ Sinh câu hỏi trắc nghiệm</h1>
        <p className="text-slate-500 text-sm mt-1">Chọn topics và cấu hình để sinh MCQ tự động</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* LEFT: Config panel */}
        <div className="lg:col-span-1 space-y-4">
          <Card>
            <CardHeader><CardTitle className="text-base">📋 Cấu hình đề thi</CardTitle></CardHeader>
            <CardContent className="space-y-3">
              <div>
                <Label>Tên đề thi</Label>
                <Input value={examName} onChange={(e) => setExamName(e.target.value)} className="mt-1" placeholder="exam_01" />
              </div>
              <div className="text-sm text-slate-500">
                <span className="font-medium">{validTopics.length} topic</span> • <span className="font-medium">{totalQ} câu hỏi</span>
                <br /><span className="text-xs">Ước tính ~{Math.ceil(totalQ * 0.5)} phút</span>
              </div>
            </CardContent>
          </Card>

          {/* Action buttons */}
          {genState.status === "idle" || genState.status === "failed" ? (
            <Button onClick={handleGenerate} className="w-full h-12 text-base" disabled={validTopics.length === 0}>
              🚀 Sinh câu hỏi
            </Button>
          ) : genState.status === "success" ? (
            <div className="space-y-2">
              <Button onClick={downloadJson} variant="outline" className="w-full">📄 Download JSON</Button>
              <Button onClick={() => downloadPdf(false)} variant="outline" className="w-full">📋 PDF Đề thi</Button>
              <Button onClick={() => downloadPdf(true)} variant="outline" className="w-full">🔑 PDF Đáp án</Button>
              <Button onClick={() => { setGenState({ status: "idle" }); setMcqs([]) }} className="w-full">+ Sinh đề mới</Button>
            </div>
          ) : (
            <Button onClick={handleCancel} variant="destructive" className="w-full">✕ Hủy</Button>
          )}

          {genState.status === "failed" && (
            <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-600">
              ❌ {genState.error}
            </div>
          )}
        </div>

        {/* RIGHT: Topics + Progress + Results */}
        <div className="lg:col-span-2 space-y-4">
          {/* Topics */}
          {(genState.status === "idle" || genState.status === "failed") && (
            <div className="space-y-3">
              {topics.map((t, i) => (
                <TopicRow key={i} index={i} topic={t}
                  onChange={(updated) => setTopics(topics.map((x, j) => j === i ? updated : x))}
                  onRemove={() => setTopics(topics.filter((_, j) => j !== i))}
                />
              ))}
              {topics.length < 5 && (
                <Button variant="outline" onClick={addTopic} className="w-full border-dashed">+ Thêm topic</Button>
              )}
            </div>
          )}

          {/* Progress */}
          {(genState.status === "queued" || genState.status === "running" || genState.status === "submitting") && (
            <Card className="p-6 space-y-4">
              {genState.status === "queued" && (
                <div className="text-center space-y-2">
                  <div className="animate-spin w-10 h-10 border-4 border-slate-200 border-t-slate-700 rounded-full mx-auto" />
                  <p className="font-semibold">Đang chờ trong queue</p>
                  <p className="text-sm text-slate-500">Vị trí #{genState.position} • Ước tính ~{genState.estimatedWait} phút</p>
                </div>
              )}
              {genState.status === "running" && (
                <div className="space-y-4">
                  <div className="flex justify-between items-center">
                    <span className="font-semibold text-sm">{genState.step}</span>
                    <span className="text-sm text-slate-500">Câu {genState.currentQ}/{genState.totalQ}</span>
                  </div>
                  <Progress value={genState.progress} className="h-3" />
                  {/* Animated stepper */}
                  <div className="relative">
                    {/* Connector line */}
                    <div className="absolute top-5 left-[10%] right-[10%] h-0.5 bg-slate-200 z-0" />
                    <div className="absolute top-5 left-[10%] h-0.5 bg-green-500 z-0 transition-all duration-700"
                      style={{ width: `${Math.min(genState.progress, 80)}%` }} />
                    <div className="relative z-10 grid grid-cols-5 gap-1">
                      {PIPELINE_STEPS.map((step, i) => {
                        const cur = Math.floor(genState.progress / 20)
                        const done = i < cur
                        const active = i === cur
                        return (
                          <div key={i} className="flex flex-col items-center gap-1">
                            <div className={`w-10 h-10 rounded-full flex items-center justify-center text-lg
                              transition-all duration-500 shadow-sm
                              ${done ? "bg-green-500 scale-100" :
                                active ? "bg-blue-500 scale-110 ring-4 ring-blue-200" :
                                "bg-slate-200 scale-95"}`}>
                              {done ? "✓" : step.icon}
                            </div>
                            <span className={`text-xs font-medium text-center leading-tight
                              ${done ? "text-green-600" : active ? "text-blue-600" : "text-slate-400"}`}>
                              {step.label}
                            </span>
                            {active && (
                              <div className="flex gap-0.5">
                                {[0,1,2].map(d => (
                                  <div key={d} className="w-1 h-1 bg-blue-500 rounded-full animate-bounce"
                                    style={{ animationDelay: `${d*150}ms` }} />
                                ))}
                              </div>
                            )}
                          </div>
                        )
                      })}
                    </div>
                  </div>
                </div>
              )}
              {genState.status === "submitting" && (
                <div className="text-center py-4">
                  <div className="animate-pulse text-slate-500">Đang submit job...</div>
                </div>
              )}
            </Card>
          )}

          {/* Results */}
          {genState.status === "success" && mcqs.length > 0 && (
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <h2 className="font-semibold text-slate-700">
                  📋 {mcqs.length} câu hỏi • {(genState.elapsed / 60).toFixed(1)} phút
                </h2>
                <div className="flex gap-2">
                  {Array.from(new Set(mcqs.map((m) => m.topic))).map((t) => (
                    <Badge key={t} variant="secondary" className="text-xs">{t}</Badge>
                  ))}
                </div>
              </div>
              {mcqs.map((mcq, i) => (
                <Card key={i} className="p-4">
                  <p className="font-medium text-sm mb-3">{i + 1}. {mcq.question_text}</p>
                  <div className="grid grid-cols-1 gap-1">
                    {Object.entries(mcq.options).map(([k, v]) => (
                      <div key={k} className={`px-3 py-2 rounded-lg text-sm ${
                        mcq.correct_answers.includes(k)
                          ? "bg-green-50 border border-green-200 text-green-800 font-medium"
                          : "bg-slate-50 border border-slate-200 text-slate-600"
                      }`}>
                        {mcq.correct_answers.includes(k) ? "✓" : " "} {k}. {v}
                      </div>
                    ))}
                  </div>
                  <div className="flex items-center gap-2 mt-2">
                    <Badge variant="outline" className="text-xs">{mcq.topic}</Badge>
                    <Badge variant="outline" className="text-xs">{mcq.difficulty_label}</Badge>
                    <span className="text-xs text-slate-400 ml-auto">
                      Score: {mcq.evaluation?.quality_score?.toFixed(2) || "—"}
                    </span>
                  </div>
                </Card>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
