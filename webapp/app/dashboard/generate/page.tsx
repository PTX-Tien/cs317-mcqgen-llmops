"use client"
import { useState, useRef, useEffect } from "react"
import { useRouter } from "next/navigation"
import { api, WS_URL } from "@/lib/api"
import { COURSE_CHAPTERS, DIFFICULTY_LABELS, TOPIC_SUGGESTIONS, chapterLabel } from "@/lib/course"
import { formatExamDisplayName } from "@/lib/exam-name"
import { TopicConfig, MCQ, GenerationFailure, GenerationState } from "@/types"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Progress } from "@/components/ui/progress"
import { Badge } from "@/components/ui/badge"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { toast } from "sonner"
import { FileText, PlayCircle, Plus, RotateCcw, Sparkles, Trash2, X } from "lucide-react"

// ── Constants ────────────────────────────────────────────────────
const PIPELINE_STEPS = [
  { label: "Tài liệu", icon: "🔍" },
  { label: "Câu hỏi", icon: "✍️" },
  { label: "Phương án", icon: "🎯" },
  { label: "Ghép đề", icon: "📝" },
  { label: "Đánh giá", icon: "✅" },
]
const DEFAULT_RETRIEVAL_MODE = "auto"
const ACTIVE_GENERATION_KEY = "mcqgen.active_generation"

interface ActiveGeneration {
  taskId: string
  examName: string
  totalQ: number
  startedAt: number
  queuePosition?: number
  jobsAhead?: number
  estimatedWait?: number
  queueWait?: number
  estimatedRuntime?: number
  questionConcurrency?: number
  llmConcurrency?: number
  vllmMaxNumSeqs?: number
}

function getApiErrorDetail(error: unknown): string | undefined {
  if (typeof error !== "object" || error === null || !("response" in error)) {
    return undefined
  }
  const response = (error as { response?: { data?: { detail?: string } } }).response
  return response?.data?.detail
}

function nowMs(): number {
  return Date.now()
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

function readActiveGeneration(): ActiveGeneration | null {
  try {
    const raw = localStorage.getItem(ACTIVE_GENERATION_KEY)
    return raw ? JSON.parse(raw) as ActiveGeneration : null
  } catch {
    return null
  }
}

function saveActiveGeneration(active: ActiveGeneration) {
  localStorage.setItem(ACTIVE_GENERATION_KEY, JSON.stringify(active))
}

function clearActiveGeneration(taskId?: string) {
  const active = readActiveGeneration()
  if (!taskId || active?.taskId === taskId) {
    localStorage.removeItem(ACTIVE_GENERATION_KEY)
  }
}

function successToastMessage(accepted: number, failed?: number) {
  return failed && failed > 0
    ? `${accepted} câu hỏi đã sinh thành công, ${failed} câu bị loại.`
    : `${accepted} câu hỏi đã sinh thành công!`
}

function formatProgressStep(step?: string): string {
  const value = (step || "").trim()
  if (!value) return "Đang xử lý"
  if (value.startsWith("retrieving_context")) return "Đang tìm tài liệu liên quan"
  if (value.startsWith("generating")) return "Đang sinh câu hỏi"
  if (value === "saving") return "Đang lưu đề thi"
  if (value === "done") return "Hoàn thành"
  return value
}

interface TopicDraft {
  id: string
  topic: string
  difficulty: string
  n: string
}

interface ChapterDraft {
  id: string
  chapter_id: string
  topics: TopicDraft[]
}

function createEmptyTopicDraft(topicId: string): TopicDraft {
  return { id: topicId, topic: "", difficulty: "G2", n: "" }
}

function createEmptyChapterDraft(chapterId: string, topicId: string): ChapterDraft {
  return { id: chapterId, chapter_id: "", topics: [createEmptyTopicDraft(topicId)] }
}

function parseQuestionCount(value: string): number {
  const parsed = Number.parseInt(value, 10)
  return Number.isFinite(parsed) ? parsed : 0
}

function TopicDraftRow({ chapterId, topic, index, selectedTopics, onChange, onRemove, canRemove }: {
  chapterId: string
  topic: TopicDraft
  index: number
  selectedTopics: string[]
  onChange: (topic: TopicDraft) => void
  onRemove: () => void
  canRemove: boolean
}) {
  const suggestions = chapterId ? TOPIC_SUGGESTIONS[chapterId] || [] : []
  const unavailableTopics = new Set(
    selectedTopics
      .filter((selectedTopic) => selectedTopic && selectedTopic !== topic.topic)
      .map((selectedTopic) => selectedTopic.toLowerCase())
  )
  const availableSuggestions = suggestions.filter(
    (suggestion) => !unavailableTopics.has(suggestion.toLowerCase()) || suggestion === topic.topic
  )

  return (
    <div className="grid grid-cols-1 gap-3 border-t border-slate-100 pt-4 md:grid-cols-[minmax(0,1fr)_minmax(150px,0.45fr)_minmax(110px,0.25fr)_36px]">
      <div className="min-w-0">
        <Label className="text-xs font-medium uppercase text-slate-500">Topic cụ thể {index + 1}</Label>
        <Select value={topic.topic} onValueChange={(value) => onChange({ ...topic, topic: value ?? "" })} disabled={!chapterId}>
          <SelectTrigger className="mt-2 h-auto min-h-11 w-full min-w-0 bg-white px-3 py-2 text-left *:data-[slot=select-value]:line-clamp-none *:data-[slot=select-value]:whitespace-normal *:data-[slot=select-value]:leading-snug">
            <SelectValue placeholder={chapterId ? "Chọn topic" : "Chọn chương trước"} />
          </SelectTrigger>
          <SelectContent align="start" className="z-[100] max-h-72">
            {availableSuggestions.map((suggestion) => (
              <SelectItem key={suggestion} value={suggestion} className="py-2">
                {suggestion}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="min-w-0">
        <Label className="text-xs font-medium uppercase text-slate-500">Độ khó</Label>
        <Select value={topic.difficulty} onValueChange={(value) => onChange({ ...topic, difficulty: value ?? "G2" })}>
          <SelectTrigger className="mt-2 h-auto min-h-11 w-full min-w-0 bg-white px-3 py-2 text-left *:data-[slot=select-value]:line-clamp-none *:data-[slot=select-value]:whitespace-normal">
            <SelectValue />
          </SelectTrigger>
          <SelectContent align="start" className="z-[100] max-h-72">
            {Object.entries(DIFFICULTY_LABELS).map(([value, label]) => (
              <SelectItem key={value} value={value} className="py-2">{label}</SelectItem>
            ))}
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
          value={topic.n}
          placeholder="Nhập"
          onChange={(event) => onChange({ ...topic, n: event.target.value })}
        />
      </div>

      <div className="flex items-end justify-end">
        <Button
          variant="ghost"
          size="icon-sm"
          onClick={onRemove}
          disabled={!canRemove}
          aria-label={`Xóa topic ${index + 1}`}
          className="text-slate-400 hover:bg-red-50 hover:text-red-600"
        >
          <Trash2 size={15} />
        </Button>
      </div>
    </div>
  )
}

function ChapterBlock({ chapter, index, selectedChapterIds, canRemove, canAddTopic, onChange, onRemove, onAddTopic }: {
  chapter: ChapterDraft
  index: number
  selectedChapterIds: string[]
  canRemove: boolean
  canAddTopic: boolean
  onChange: (chapter: ChapterDraft) => void
  onRemove: () => void
  onAddTopic: () => void
}) {
  const unavailableChapterIds = new Set(
    selectedChapterIds.filter((chapterId) => chapterId && chapterId !== chapter.chapter_id)
  )
  const chapterOptions = Object.entries(COURSE_CHAPTERS).filter(
    ([chapterId]) => !unavailableChapterIds.has(chapterId) || chapterId === chapter.chapter_id
  )
  const selectedTopics = chapter.topics.map((topic) => topic.topic).filter(Boolean)
  const selectedTopicKeys = selectedTopics.map((topic) => topic.toLowerCase())
  const availableTopicCount = chapter.chapter_id
    ? (TOPIC_SUGGESTIONS[chapter.chapter_id] || []).filter(
        (topic) => !selectedTopicKeys.includes(topic.toLowerCase())
      ).length
    : 0

  return (
    <div className="overflow-visible rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3 pb-4">
        <div className="min-w-0">
          <p className="whitespace-normal text-sm font-semibold leading-snug text-slate-800">
            {chapter.chapter_id ? chapterLabel(chapter.chapter_id) : "Chọn chương"}
          </p>
          <p className="mt-0.5 text-xs text-slate-500">Nhóm chương {String(index + 1).padStart(2, "0")}</p>
        </div>
        <Button
          variant="ghost"
          size="icon-sm"
          onClick={onRemove}
          disabled={!canRemove}
          aria-label={`Xóa chương ${index + 1}`}
          className="text-slate-400 hover:bg-red-50 hover:text-red-600"
        >
          <Trash2 size={15} />
        </Button>
      </div>

      <div className="min-w-0">
        <Label className="text-xs font-medium uppercase text-slate-500">Chương</Label>
        <Select
          value={chapter.chapter_id}
          onValueChange={(value) => onChange({
            ...chapter,
            chapter_id: value ?? "",
            topics: chapter.topics.map((topic) => ({ ...topic, topic: "" })),
          })}
        >
          <SelectTrigger className="mt-2 h-auto min-h-11 w-full min-w-0 bg-white px-3 py-2 text-left *:data-[slot=select-value]:line-clamp-none *:data-[slot=select-value]:whitespace-normal *:data-[slot=select-value]:leading-snug">
            <SelectValue placeholder="Chọn chương" />
          </SelectTrigger>
          <SelectContent align="start" className="z-[100] max-h-72">
            {chapterOptions.map(([value, label]) => (
              <SelectItem key={value} value={value} className="py-2">{label}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="mt-4 space-y-4">
        {chapter.topics.map((topic, topicIndex) => (
          <TopicDraftRow
            key={topic.id}
            chapterId={chapter.chapter_id}
            topic={topic}
            index={topicIndex}
            selectedTopics={selectedTopics}
            canRemove={chapter.topics.length > 1}
            onChange={(updatedTopic) => onChange({
              ...chapter,
              topics: chapter.topics.map((item) => item.id === topic.id ? updatedTopic : item),
            })}
            onRemove={() => onChange({
              ...chapter,
              topics: chapter.topics.filter((item) => item.id !== topic.id),
            })}
          />
        ))}
      </div>

      <Button
        variant="outline"
        onClick={onAddTopic}
        disabled={!canAddTopic}
        className="mt-4 h-10 w-full border-dashed"
      >
        <Plus size={15} />
        {chapter.chapter_id && (!canAddTopic || availableTopicCount === 0) ? "Đã đủ topic" : "Thêm topic"}
      </Button>
    </div>
  )
}

// ── Main page ────────────────────────────────────────────────────
export default function GeneratePage() {
  const router = useRouter()
  const [examName, setExamName] = useState("Đề số 1")
  const [chapters, setChapters] = useState<ChapterDraft[]>([
    createEmptyChapterDraft("c1", "t1")
  ])
  const [genState, setGenState] = useState<GenerationState>({ status: "idle" })
  const [mcqs, setMcqs] = useState<MCQ[]>([])
  const wsRef = useRef<WebSocket | null>(null)
  const taskIdRef = useRef<string | null>(null)
  const nextChapterIndexRef = useRef(2)
  const nextTopicIndexRef = useRef(2)

  const draftTopics = chapters.flatMap((chapter) =>
    chapter.topics.map((topic) => ({
      chapter,
      topic,
    }))
  )
  const validTopics = draftTopics
    .filter(({ chapter, topic }) => chapter.chapter_id && topic.topic.trim() && parseQuestionCount(topic.n) > 0)
    .map(({ chapter, topic }, index): TopicConfig => ({
      topic_id: `t${index + 1}`,
      chapter_id: chapter.chapter_id,
      topic: topic.topic.trim(),
      difficulty: topic.difficulty || "G2",
      n: parseQuestionCount(topic.n),
    }))
  const totalQ = validTopics.reduce((sum, topic) => sum + topic.n, 0)
  const displayExamName = formatExamDisplayName(examName)
  const systemExamName = normalizeExamName(examName)
  const selectedChapterIds = chapters.map((chapter) => chapter.chapter_id).filter(Boolean)
  const chapterOptionCount = Object.keys(COURSE_CHAPTERS).length
  const canAddChapter = chapters.length < chapterOptionCount

  const canAddTopicForChapter = (chapter: ChapterDraft): boolean => {
    if (!chapter.chapter_id) return false
    const suggestions = TOPIC_SUGGESTIONS[chapter.chapter_id] || []
    if (suggestions.length === 0) return false
    if (chapter.topics.length >= suggestions.length) return false
    const selectedTopicKeys = new Set(
      chapter.topics
        .map((topic) => topic.topic.trim().toLowerCase())
        .filter(Boolean)
    )
    return suggestions.some((suggestion) => !selectedTopicKeys.has(suggestion.toLowerCase()))
  }

  const addChapter = () => {
    if (!canAddChapter) {
      toast.info("Bạn đã chọn hết các chương có sẵn")
      return
    }
    const nextChapterId = `c${nextChapterIndexRef.current}`
    const nextTopicId = `t${nextTopicIndexRef.current}`
    nextChapterIndexRef.current += 1
    nextTopicIndexRef.current += 1
    setChapters([...chapters, createEmptyChapterDraft(nextChapterId, nextTopicId)])
  }

  const addTopicToChapter = (chapterId: string) => {
    const chapter = chapters.find((item) => item.id === chapterId)
    if (!chapter) return
    if (!chapter.chapter_id) {
      toast.error("Vui lòng chọn chương trước khi thêm topic")
      return
    }
    if (!canAddTopicForChapter(chapter)) {
      toast.info("Bạn đã chọn hết topic trong chương này")
      return
    }
    const nextTopicId = `t${nextTopicIndexRef.current}`
    nextTopicIndexRef.current += 1
    setChapters(chapters.map((chapter) => (
      chapter.id === chapterId
        ? { ...chapter, topics: [...chapter.topics, createEmptyTopicDraft(nextTopicId)] }
        : chapter
    )))
  }

  const updateChapter = (updatedChapter: ChapterDraft) => {
    setChapters(chapters.map((chapter) => chapter.id === updatedChapter.id ? updatedChapter : chapter))
  }

  const removeChapter = (chapterId: string) => {
    setChapters(chapters.filter((chapter) => chapter.id !== chapterId))
  }

  const validateDraft = (): TopicConfig[] | null => {
    if (!examName.trim()) {
      toast.error("Vui lòng nhập tên đề thi")
      return null
    }
    if (chapters.length === 0) {
      toast.error("Vui lòng thêm ít nhất một chương")
      return null
    }
    const flattened: TopicConfig[] = []
    const seenChapters = new Set<string>()
    for (const [chapterIndex, chapter] of chapters.entries()) {
      if (!chapter.chapter_id) {
        toast.error(`Chương ${chapterIndex + 1} chưa được chọn`)
        return null
      }
      if (seenChapters.has(chapter.chapter_id)) {
        toast.error(`${chapterLabel(chapter.chapter_id)} đã được chọn ở nhóm khác`)
        return null
      }
      seenChapters.add(chapter.chapter_id)
      const seenTopics = new Set<string>()
      for (const [topicIndex, topic] of chapter.topics.entries()) {
        const label = `Chương ${chapterIndex + 1}, topic ${topicIndex + 1}`
        if (!topic.topic.trim()) {
          toast.error(`${label} chưa chọn topic cụ thể`)
          return null
        }
        const duplicateKey = topic.topic.trim().toLowerCase()
        if (seenTopics.has(duplicateKey)) {
          toast.error(`${label} bị trùng topic trong cùng chương`)
          return null
        }
        seenTopics.add(duplicateKey)
        const n = parseQuestionCount(topic.n)
        if (n < 1) {
          toast.error(`${label} chưa nhập số câu hợp lệ`)
          return null
        }
        flattened.push({
          topic_id: `t${flattened.length + 1}`,
          chapter_id: chapter.chapter_id,
          topic: topic.topic.trim(),
          difficulty: topic.difficulty || "G2",
          n,
        })
      }
    }
    return flattened
  }

  const completeGeneration = (
    taskId: string,
    data: { accepted?: number; failed?: number; failures?: GenerationFailure[]; mcqs?: MCQ[] },
    start: number,
  ) => {
    const generated = data.mcqs || []
    const failed = data.failed ?? data.failures?.length ?? 0
    setMcqs(generated)
    setGenState({
      status: "success",
      mcqs: generated,
      elapsed: elapsedSeconds(start),
      taskId,
      failed,
      failures: data.failures || [],
    })
    clearActiveGeneration(taskId)
    toast.success(successToastMessage(data.accepted ?? generated.length, failed))
  }

  function pollFallback(taskId: string, start: number, expectedTotalQ: number = totalQ) {
    const interval = setInterval(async () => {
      try {
        const { data } = await api.get(`/status/${taskId}`)
        if (data.state === "running") {
          setGenState({
            status: "running",
            progress: data.progress,
            step: formatProgressStep(data.step),
            currentQ: data.current_question || 0,
            totalQ: data.total_questions || expectedTotalQ,
            taskId,
            questionConcurrency: data.question_concurrency,
            llmConcurrency: data.llm_concurrency,
            vllmMaxNumSeqs: data.vllm_max_num_seqs,
          })
        } else if (data.state === "success") {
          clearInterval(interval)
          const res = await api.get(`/results/${taskId}`)
          completeGeneration(taskId, res.data, start)
        } else if (data.state === "failed") {
          clearInterval(interval)
          clearActiveGeneration(taskId)
          setGenState({ status: "failed", error: "Pipeline thất bại" })
        }
      } catch {
        clearInterval(interval)
        clearActiveGeneration(taskId)
        setGenState({ status: "failed", error: "Không lấy được trạng thái/kết quả từ API" })
      }
    }, 3000)
  }

  function startWebSocket(taskId: string, start: number = nowMs(), expectedTotalQ: number = totalQ) {
    const ws = new WebSocket(`${WS_URL}/ws/${taskId}`)
    wsRef.current = ws
    let finished = false
    let fallbackStarted = false

    const startPollingFallback = () => {
      if (finished || fallbackStarted) return
      fallbackStarted = true
      pollFallback(taskId, start, expectedTotalQ)
    }

    ws.onmessage = async (e) => {
      const msg = JSON.parse(e.data)
      if (msg.state === "running") {
        setGenState({
          status: "running",
          progress: msg.progress,
          step: formatProgressStep(msg.step),
          currentQ: msg.current_question || 0,
          totalQ: msg.total_questions || expectedTotalQ,
          taskId,
          questionConcurrency: msg.question_concurrency,
          llmConcurrency: msg.llm_concurrency,
          vllmMaxNumSeqs: msg.vllm_max_num_seqs,
        })
      } else if (msg.state === "success") {
        try {
          const { data } = await api.get(`/results/${taskId}`)
          completeGeneration(taskId, data, start)
        } catch { setGenState({ status: "failed", error: "Lỗi lấy kết quả" }) }
        finished = true
        ws.close()
      } else if (msg.state === "failed") {
        clearActiveGeneration(taskId)
        setGenState({ status: "failed", error: msg.error || "Pipeline thất bại" })
        toast.error("Pipeline thất bại")
        finished = true
        ws.close()
      }
    }
    ws.onerror = startPollingFallback
    ws.onclose = startPollingFallback
  }

  async function resumeActiveGeneration() {
    const active = readActiveGeneration()
    if (!active) return

    taskIdRef.current = active.taskId
    const start = active.startedAt || nowMs()
    try {
      const { data } = await api.get(`/status/${active.taskId}`)
      if (data.state === "pending") {
        setExamName(formatExamDisplayName(active.examName))
        setGenState({
          status: "queued",
          position: active.queuePosition || 1,
          estimatedWait: active.estimatedWait || 0,
          queueWait: active.queueWait || 0,
          estimatedRuntime: active.estimatedRuntime || 0,
          jobsAhead: active.jobsAhead || 0,
          taskId: active.taskId,
          questionConcurrency: active.questionConcurrency,
          llmConcurrency: active.llmConcurrency,
          vllmMaxNumSeqs: active.vllmMaxNumSeqs,
        })
        startWebSocket(active.taskId, start, active.totalQ)
        toast.info("Đã nối lại job đang sinh câu hỏi")
      } else if (data.state === "running") {
        setExamName(formatExamDisplayName(active.examName))
        setGenState({
          status: "running",
          progress: data.progress,
          step: formatProgressStep(data.step),
          currentQ: data.current_question || 0,
          totalQ: data.total_questions || active.totalQ,
          taskId: active.taskId,
          questionConcurrency: data.question_concurrency,
          llmConcurrency: data.llm_concurrency,
          vllmMaxNumSeqs: data.vllm_max_num_seqs,
        })
        startWebSocket(active.taskId, start, active.totalQ)
        toast.info("Đã nối lại job đang sinh câu hỏi")
      } else if (data.state === "success") {
        const res = await api.get(`/results/${active.taskId}`)
        completeGeneration(active.taskId, res.data, start)
      } else if (data.state === "failed") {
        clearActiveGeneration(active.taskId)
        setGenState({ status: "failed", error: data.error || "Pipeline thất bại" })
      }
    } catch {
      clearActiveGeneration(active.taskId)
      setGenState({ status: "failed", error: "Không nối lại được job đang chạy" })
    }
  }

  useEffect(() => {
    if (!localStorage.getItem("access_token")) {
      router.push("/login")
      return
    }
    const timer = window.setTimeout(() => {
      void resumeActiveGeneration()
    }, 0)
    return () => window.clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [router])

  const handleGenerate = async () => {
    const topicsToSubmit = validateDraft()
    if (!topicsToSubmit) return
    setGenState({ status: "submitting" })
    setMcqs([])
    const startedAt = nowMs()
    try {
      const { data } = await api.post("/generate", {
        topics: topicsToSubmit,
        output_name: systemExamName,
        display_name: displayExamName,
        retrieval_mode: DEFAULT_RETRIEVAL_MODE,
      })
      taskIdRef.current = data.task_id
      saveActiveGeneration({
        taskId: data.task_id,
        examName: displayExamName,
        totalQ: topicsToSubmit.reduce((sum, topic) => sum + topic.n, 0),
        startedAt,
        queuePosition: data.queue_position,
        jobsAhead: data.jobs_ahead ?? Math.max(0, data.queue_position - 1),
        estimatedWait: data.estimated_total_min ?? data.estimated_wait_min,
        queueWait: data.queue_wait_min ?? 0,
        estimatedRuntime: data.estimated_runtime_min ?? 0,
        questionConcurrency: data.generation_concurrency,
        llmConcurrency: data.llm_concurrency,
        vllmMaxNumSeqs: data.vllm_max_num_seqs,
      })
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
      startWebSocket(data.task_id, startedAt, topicsToSubmit.reduce((sum, topic) => sum + topic.n, 0))
    } catch (e: unknown) {
      const message = getApiErrorDetail(e) || "Lỗi kết nối API"
      setGenState({ status: "failed", error: message })
      toast.error(message)
    }
  }

  const handleCancel = async () => {
    if (taskIdRef.current) { await api.delete(`/cancel/${taskIdRef.current}`).catch(() => {}) }
    wsRef.current?.close()
    clearActiveGeneration(taskIdRef.current || undefined)
    taskIdRef.current = null
    setGenState({ status: "idle" })
    toast.info("Job đã hủy")
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
        <div className="space-y-4 lg:sticky lg:top-0 lg:z-30 lg:col-span-1 lg:max-h-[calc(100vh-7rem)] lg:self-start lg:overflow-y-auto lg:pr-1">
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
                <span className="font-medium">{chapters.length} chương</span> • <span className="font-medium">{validTopics.length} topic hợp lệ</span> • <span className="font-medium">{totalQ} câu hỏi</span>
              </div>
            </CardContent>
          </Card>

          {/* Action buttons */}
          {genState.status === "idle" || genState.status === "failed" ? (
            <Button onClick={handleGenerate} className="w-full h-12 text-base" disabled={chapters.length === 0}>
              <Sparkles size={17} />
              Sinh câu hỏi
            </Button>
          ) : genState.status === "success" ? (
            <div className="space-y-2">
              <Button onClick={() => router.push(`/dashboard/take/${genState.taskId}`)} className="w-full">
                <PlayCircle size={16} />
                Bắt đầu làm đề
              </Button>
              <Button onClick={() => downloadPdf(false)} variant="outline" className="w-full"><FileText size={16} />PDF Đề thi</Button>
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
              {chapters.map((chapter, index) => (
                <ChapterBlock
                  key={chapter.id}
                  chapter={chapter}
                  index={index}
                  selectedChapterIds={selectedChapterIds}
                  canRemove={chapters.length > 1}
                  canAddTopic={canAddTopicForChapter(chapter)}
                  onChange={updateChapter}
                  onRemove={() => removeChapter(chapter.id)}
                  onAddTopic={() => addTopicToChapter(chapter.id)}
                />
              ))}
              <Button variant="outline" onClick={addChapter} disabled={!canAddChapter} className="h-11 w-full border-dashed">
                <Plus size={16} />
                {canAddChapter ? "Thêm chương" : "Đã đủ chương"}
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
                  {genState.failed ? ` • ${genState.failed} câu bị loại` : ""}
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
                      <div key={k} className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700">
                        {k}. {v}
                      </div>
                    ))}
                  </div>
                  <div className="flex items-center gap-2 mt-2 flex-wrap">
                    <Badge variant="outline" className="text-xs">{mcq.topic}</Badge>
                    <Badge variant="outline" className="text-xs">{mcq.difficulty_label}</Badge>
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
