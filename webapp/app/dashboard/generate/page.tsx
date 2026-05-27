"use client"
import { useState, useRef, useEffect } from "react"
import { useRouter } from "next/navigation"
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
import { FileJson, FileText, KeyRound, Plus, RotateCcw, Sparkles, Trash2, X } from "lucide-react"

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
  ch03: ["Data pipeline workflow", "Exploratory Data Analysis", "Data visualization"],
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
const DEFAULT_RETRIEVAL_MODE = "auto"

function getApiErrorDetail(error: unknown): string | undefined {
  if (typeof error !== "object" || error === null || !("response" in error)) {
    return undefined
  }
  const response = (error as { response?: { data?: { detail?: string } } }).response
  return response?.data?.detail
}

function nowMs(): number {
  return performance.now()
}

function elapsedSeconds(startMs: number): number {
  return (nowMs() - startMs) / 1000
}

function normalizeExamName(value: string): string {
  const normalized = value
    .trim()
    .replace(/đ/g, "d")
    .replace(/Đ/g, "D")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-zA-Z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .replace(/_+/g, "_")
    .toLowerCase()
  return normalized || "de_thi"
}

function createEmptyTopic(topicId: string): TopicConfig {
  return { topic_id: topicId, chapter_id: "ch07b", topic: "", difficulty: "G2", n: 2 }
}

// ── Topic Row component ──────────────────────────────────────────
function TopicRow({ index, topic, onChange, onRemove }: {
  index: number
  topic: TopicConfig
  onChange: (t: TopicConfig) => void
  onRemove: () => void
}) {
  const suggestions = TOPIC_SUGGESTIONS[topic.chapter_id] || []
  const selectedChapter = CHAPTERS[topic.chapter_id] || "Chưa chọn chapter"
  const questionCount = Number.isFinite(topic.n) ? Math.max(1, topic.n) : 1

  return (
    <Card className="overflow-visible border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-100 pb-3">
        <div className="min-w-0">
          <p className="text-sm font-semibold text-slate-800">Chủ đề {String(index + 1).padStart(2, "0")}</p>
          <p className="mt-0.5 truncate text-xs text-slate-500">{selectedChapter}</p>
        </div>
        <Button
          variant="ghost"
          size="icon-sm"
          onClick={onRemove}
          aria-label={`Xóa chủ đề ${index + 1}`}
          className="text-slate-400 hover:bg-red-50 hover:text-red-600"
        >
          <Trash2 size={15} />
        </Button>
      </div>

      <div className="grid w-full max-w-full grid-cols-1 gap-4 md:grid-cols-2 2xl:grid-cols-[minmax(0,1fr)_minmax(0,1.35fr)_minmax(0,0.7fr)_minmax(96px,0.35fr)]">
        <div className="min-w-0 max-w-full">
          <Label className="text-xs font-medium uppercase text-slate-500">Chapter</Label>
          <Select value={topic.chapter_id} onValueChange={(v) => onChange({ ...topic, chapter_id: v ?? "", topic: "" })}>
            <SelectTrigger className="mt-2 h-11 w-full min-w-0 bg-white px-3 text-left">
              <SelectValue placeholder="Chọn chapter" />
            </SelectTrigger>
            <SelectContent align="start" className="z-[100] max-h-72">
              {Object.entries(CHAPTERS).map(([k, v]) => (
                <SelectItem key={k} value={k} className="py-2">{v}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="min-w-0">
          <Label className="text-xs font-medium uppercase text-slate-500">Topic cụ thể</Label>
          <Select value={topic.topic} onValueChange={(v) => onChange({ ...topic, topic: v ?? "" })}>
            <SelectTrigger className="mt-2 h-11 w-full min-w-0 bg-white px-3 text-left">
              <SelectValue placeholder="Chọn topic" />
            </SelectTrigger>
            <SelectContent align="start" className="z-[100] max-h-72">
              {suggestions.map((suggestion) => (
                <SelectItem key={suggestion} value={suggestion} className="py-2">
                  {suggestion}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="min-w-0">
          <Label className="text-xs font-medium uppercase text-slate-500">Độ khó</Label>
          <Select value={topic.difficulty} onValueChange={(v) => onChange({ ...topic, difficulty: v ?? "G2" })}>
            <SelectTrigger className="mt-2 h-11 w-full min-w-0 bg-white px-3 text-left">
              <SelectValue />
            </SelectTrigger>
            <SelectContent align="start" className="z-[100] max-h-72">
              <SelectItem value="G1" className="py-2">G1 - Nhớ/Biết</SelectItem>
              <SelectItem value="G2" className="py-2">G2 - Hiểu/Áp dụng</SelectItem>
              <SelectItem value="G3" className="py-2">G3 - Phân tích</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div className="min-w-0">
          <Label className="text-xs font-medium uppercase text-slate-500">Số câu</Label>
          <Input
            type="number"
            min={1}
            inputMode="numeric"
            className="mt-2 h-11 w-full max-w-full bg-white text-center text-sm font-semibold"
            value={questionCount}
            onChange={(e) => onChange({ ...topic, n: Math.max(1, parseInt(e.target.value) || 1) })}
          />
        </div>
      </div>
    </Card>
  )
}

// ── Main page ────────────────────────────────────────────────────
export default function GeneratePage() {
  const router = useRouter()
  const [examName, setExamName] = useState("Đề số 1")
  const [topics, setTopics] = useState<TopicConfig[]>([
    { topic_id: "t1", chapter_id: "ch07b", topic: "Decision Trees", difficulty: "G2", n: 3 }
  ])
  const [genState, setGenState] = useState<GenerationState>({ status: "idle" })
  const [mcqs, setMcqs] = useState<MCQ[]>([])
  const wsRef = useRef<WebSocket | null>(null)
  const taskIdRef = useRef<string | null>(null)
  const nextTopicIndexRef = useRef(2)

  useEffect(() => {
    if (!localStorage.getItem("access_token")) router.push("/login")
  }, [router])

  const totalQ = topics.reduce((s, t) => s + Math.max(1, t.n || 1), 0)
  const validTopics = topics.filter((t) => t.chapter_id && t.topic.trim())
  const systemExamName = normalizeExamName(examName)

  const addTopic = () => {
    const nextTopicId = `t${nextTopicIndexRef.current}`
    nextTopicIndexRef.current += 1
    setTopics([...topics, createEmptyTopic(nextTopicId)])
  }

  const handleGenerate = async () => {
    if (validTopics.length === 0) { toast.error("Vui lòng thêm ít nhất 1 topic"); return }
    if (!examName.trim()) { toast.error("Vui lòng nhập tên đề thi"); return }
    setGenState({ status: "submitting" })
    setMcqs([])
    try {
      const { data } = await api.post("/generate", {
        topics: validTopics.map((topic) => ({
          ...topic,
          topic: topic.topic.trim(),
          n: Math.max(1, topic.n || 1),
        })),
        output_name: systemExamName,
        retrieval_mode: DEFAULT_RETRIEVAL_MODE,
      })
      taskIdRef.current = data.task_id
      setGenState({
        status: "queued",
        position: data.queue_position,
        estimatedWait: data.estimated_total_min ?? data.estimated_wait_min,
        queueWait: data.queue_wait_min ?? 0,
        estimatedRuntime: data.estimated_runtime_min ?? 0,
        jobsAhead: data.jobs_ahead ?? Math.max(0, data.queue_position - 1),
        taskId: data.task_id,
        questionConcurrency: data.generation_concurrency,
        llmConcurrency: data.llm_concurrency,
        vllmMaxNumSeqs: data.vllm_max_num_seqs,
      })
      toast.success(`Đã gửi yêu cầu sinh câu hỏi. Vị trí #${data.queue_position}`)
      startWebSocket(data.task_id)
    } catch (e: unknown) {
      setGenState({ status: "failed", error: getApiErrorDetail(e) || "Lỗi kết nối API" })
      toast.error("Không thể submit job")
    }
  }

  const startWebSocket = (taskId: string) => {
    const ws = new WebSocket(`${WS_URL}/ws/${taskId}`)
    wsRef.current = ws
    const start = nowMs()
    let finished = false
    let fallbackStarted = false

    const startPollingFallback = () => {
      if (finished || fallbackStarted) return
      fallbackStarted = true
      pollFallback(taskId, start)
    }

    ws.onmessage = async (e) => {
      const msg = JSON.parse(e.data)
      if (msg.state === "running") {
        setGenState({
          status: "running",
          progress: msg.progress,
          step: msg.step || "Generating...",
          currentQ: msg.current_question || 0,
          totalQ: msg.total_questions || totalQ,
          taskId,
          questionConcurrency: msg.question_concurrency,
          llmConcurrency: msg.llm_concurrency,
          vllmMaxNumSeqs: msg.vllm_max_num_seqs,
        })
      } else if (msg.state === "success") {
        try {
          const { data } = await api.get(`/results/${taskId}`)
          setMcqs(data.mcqs || [])
          setGenState({ status: "success", mcqs: data.mcqs, elapsed: elapsedSeconds(start), taskId })
          toast.success(`✅ ${data.accepted} câu hỏi đã sinh thành công!`)
        } catch { setGenState({ status: "failed", error: "Lỗi lấy kết quả" }) }
        finished = true
        ws.close()
      } else if (msg.state === "failed") {
        setGenState({ status: "failed", error: msg.error || "Pipeline thất bại" })
        toast.error("Pipeline thất bại")
        finished = true
        ws.close()
      }
    }
    ws.onerror = startPollingFallback
    ws.onclose = startPollingFallback
  }

  const pollFallback = (taskId: string, start: number) => {
    const interval = setInterval(async () => {
      try {
        const { data } = await api.get(`/status/${taskId}`)
        if (data.state === "running") {
          setGenState({
            status: "running",
            progress: data.progress,
            step: data.step || "Processing...",
            currentQ: data.current_question || 0,
            totalQ: data.total_questions || totalQ,
            taskId,
            questionConcurrency: data.question_concurrency,
            llmConcurrency: data.llm_concurrency,
            vllmMaxNumSeqs: data.vllm_max_num_seqs,
          })
        } else if (data.state === "success") {
          clearInterval(interval)
          const res = await api.get(`/results/${taskId}`)
          setMcqs(res.data.mcqs)
          setGenState({ status: "success", mcqs: res.data.mcqs, elapsed: elapsedSeconds(start), taskId })
          toast.success(`✅ ${res.data.accepted} câu hỏi đã sinh thành công!`)
        } else if (data.state === "failed") {
          clearInterval(interval)
          setGenState({ status: "failed", error: "Pipeline thất bại" })
        }
      } catch {
        clearInterval(interval)
        setGenState({ status: "failed", error: "Không lấy được trạng thái/kết quả từ API" })
      }
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
    a.download = `${systemExamName}_mcqs.json`; a.click()
  }

  const downloadPdf = async (withAnswers: boolean) => {
    if (genState.status !== "success") return
    const { data } = await api.get(`/export/pdf/${genState.taskId}?include_answers=${withAnswers}`, { responseType: "blob" })
    const a = document.createElement("a"); a.href = URL.createObjectURL(data)
    a.download = `${systemExamName}_${withAnswers ? "answers" : "exam"}.pdf`; a.click()
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-800">⚡ Sinh câu hỏi trắc nghiệm</h1>
        <p className="text-slate-500 text-sm mt-1">Chọn chủ đề và cấu hình đề thi</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* LEFT: Config panel */}
        <div className="lg:col-span-1 space-y-4">
          <Card>
            <CardHeader><CardTitle className="text-base">📋 Cấu hình đề thi</CardTitle></CardHeader>
            <CardContent className="space-y-3">
              <div>
                <Label>Tên đề thi</Label>
                <Input
                  value={examName}
                  onChange={(e) => setExamName(e.target.value)}
                  className="mt-1 h-10"
                  placeholder="Ví dụ: Đề số 1"
                />
                <div className="mt-2 rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-500">
                  Mã lưu: <span className="font-medium text-slate-700">{systemExamName}</span>
                </div>
              </div>
              <div className="text-sm text-slate-500">
                <span className="font-medium">{validTopics.length} topic</span> • <span className="font-medium">{totalQ} câu hỏi</span>
              </div>
            </CardContent>
          </Card>

          {/* Action buttons */}
          {genState.status === "idle" || genState.status === "failed" ? (
            <Button onClick={handleGenerate} className="w-full h-12 text-base" disabled={validTopics.length === 0}>
              <Sparkles size={17} />
              Sinh câu hỏi
            </Button>
          ) : genState.status === "success" ? (
            <div className="space-y-2">
              <Button onClick={downloadJson} variant="outline" className="w-full"><FileJson size={16} />Download JSON</Button>
              <Button onClick={() => downloadPdf(false)} variant="outline" className="w-full"><FileText size={16} />PDF Đề thi</Button>
              <Button onClick={() => downloadPdf(true)} variant="outline" className="w-full"><KeyRound size={16} />PDF Đáp án</Button>
              <Button onClick={() => { setGenState({ status: "idle" }); setMcqs([]) }} className="w-full"><RotateCcw size={16} />Sinh đề mới</Button>
            </div>
          ) : (
            <Button onClick={handleCancel} variant="destructive" className="w-full"><X size={16} />Hủy</Button>
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
                <TopicRow key={t.topic_id} index={i} topic={t}
                  onChange={(updated) => setTopics(topics.map((x, j) => j === i ? updated : x))}
                  onRemove={() => setTopics(topics.filter((_, j) => j !== i))}
                />
              ))}
              <Button variant="outline" onClick={addTopic} className="h-11 w-full border-dashed">
                <Plus size={16} />
                Thêm topic
              </Button>
            </div>
          )}

          {/* Progress */}
          {(genState.status === "queued" || genState.status === "running" || genState.status === "submitting") && (
            <Card className="p-6 space-y-4">
              {genState.status === "queued" && (
                <div className="text-center space-y-2">
                  <div className="animate-spin w-10 h-10 border-4 border-slate-200 border-t-slate-700 rounded-full mx-auto" />
                  <p className="font-semibold">Đang chờ trong queue</p>
                  <p className="text-sm text-slate-500">
                    Vị trí #{genState.position} • {genState.jobsAhead > 0 ? `${genState.jobsAhead} job phía trước` : "đang chờ worker nhận job"}
                  </p>
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
