"use client"
import { useState, useEffect } from "react"
import { useRouter } from "next/navigation"
import { MCQ } from "@/types"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Progress } from "@/components/ui/progress"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { toast } from "sonner"

type QuizPhase = "setup" | "taking" | "results"

interface QuizAnswer { [questionIndex: number]: string }

interface TopicStat { correct: number; total: number }

export default function QuizPage() {
  const router = useRouter()
  const [phase, setPhase] = useState<QuizPhase>("setup")
  const [mcqs, setMcqs] = useState<MCQ[]>([])
  const [studentName, setStudentName] = useState("")
  const [studentId, setStudentId] = useState("")
  const [answers, setAnswers] = useState<QuizAnswer>({})
  const [currentQ, setCurrentQ] = useState(0)
  const [timeLeft, setTimeLeft] = useState(0)
  const [startTime, setStartTime] = useState(0)

  // Timer countdown
  useEffect(() => {
    if (phase !== "taking" || timeLeft <= 0) return
    const t = setInterval(() => {
      setTimeLeft((prev) => {
        if (prev <= 1) { clearInterval(t); handleSubmit(); return 0 }
        return prev - 1
      })
    }, 1000)
    return () => clearInterval(t)
  }, [phase, timeLeft])

  const handleUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    const reader = new FileReader()
    reader.onload = (ev) => {
      try {
        const data = JSON.parse(ev.target?.result as string)
        setMcqs(Array.isArray(data) ? data : [])
        toast.success(`Loaded ${Array.isArray(data) ? data.length : 0} câu hỏi`)
      } catch { toast.error("File JSON không hợp lệ") }
    }
    reader.readAsText(file)
  }

  const startQuiz = () => {
    if (!studentName.trim()) { toast.error("Nhập họ tên trước"); return }
    if (mcqs.length === 0) { toast.error("Upload đề thi trước"); return }
    const totalSeconds = mcqs.length * 90 // 1.5 phút/câu
    setTimeLeft(totalSeconds)
    setStartTime(Date.now())
    setCurrentQ(0)
    setAnswers({})
    setPhase("taking")
  }

  const selectAnswer = (key: string) => {
    setAnswers((prev) => ({ ...prev, [currentQ]: key }))
  }

  const handleSubmit = () => {
    const unanswered = mcqs.map((_, i) => i).filter((i) => !answers[i])
    if (unanswered.length > 0 && timeLeft > 0) {
      toast.warning(`Còn ${unanswered.length} câu chưa trả lời. Xác nhận nộp?`, {
        action: { label: "Nộp bài", onClick: () => setPhase("results") },
      })
      return
    }
    setPhase("results")
  }

  // Results calculation
  const calcResults = () => {
    let correct = 0
    const topicStats: Record<string, TopicStat> = {}
    const details = mcqs.map((mcq, i) => {
      const selected = answers[i] || ""
      const isCorrect = mcq.correct_answers.includes(selected)
      if (isCorrect) correct++
      const t = mcq.topic
      if (!topicStats[t]) topicStats[t] = { correct: 0, total: 0 }
      topicStats[t].total++
      if (isCorrect) topicStats[t].correct++
      return { mcq, selected, isCorrect }
    })
    const elapsed = Math.round((Date.now() - startTime) / 1000)
    const score = (correct / mcqs.length) * 10
    return { correct, total: mcqs.length, score, elapsed, topicStats, details }
  }

  const formatTime = (s: number) =>
    `${Math.floor(s / 60).toString().padStart(2, "0")}:${(s % 60).toString().padStart(2, "0")}`

  const getGrade = (score: number) => {
    if (score >= 9) return { label: "Xuất sắc 🏆", color: "text-yellow-600" }
    if (score >= 7) return { label: "Tốt 👍", color: "text-green-600" }
    if (score >= 5) return { label: "Đạt ✅", color: "text-blue-600" }
    return { label: "Cần ôn lại 📚", color: "text-red-600" }
  }

  // ── SETUP PHASE ─────────────────────────────────────────────
  if (phase === "setup") return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 to-slate-700 flex items-center justify-center p-4">
      <Card className="w-full max-w-lg shadow-2xl">
        <CardHeader className="text-center">
          <div className="text-4xl mb-2">🎯</div>
          <CardTitle className="text-2xl">Quiz Mode — Sinh viên</CardTitle>
          <p className="text-slate-500 text-sm">Làm bài trắc nghiệm và nhận kết quả ngay</p>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label>Họ tên</Label>
              <Input className="mt-1" placeholder="Nguyễn Văn A"
                value={studentName} onChange={(e) => setStudentName(e.target.value)} />
            </div>
            <div>
              <Label>MSSV</Label>
              <Input className="mt-1" placeholder="22521234"
                value={studentId} onChange={(e) => setStudentId(e.target.value)} />
            </div>
          </div>
          <div>
            <Label>Upload đề thi JSON</Label>
            <div className="mt-1 border-2 border-dashed border-slate-200 rounded-lg p-4 text-center">
              <input type="file" accept=".json" onChange={handleUpload} className="hidden" id="file-upload" suppressHydrationWarning />
              <label htmlFor="file-upload" className="cursor-pointer">
                <div className="text-2xl mb-1">📁</div>
                <p className="text-sm text-slate-500">
                  {mcqs.length > 0 ? `✅ ${mcqs.length} câu hỏi đã load` : "Click để chọn file JSON"}
                </p>
              </label>
            </div>
          </div>
          {mcqs.length > 0 && (
            <div className="bg-slate-50 rounded-lg p-3 text-sm space-y-1">
              <div className="flex justify-between"><span>Số câu hỏi:</span><strong>{mcqs.length}</strong></div>
              <div className="flex justify-between"><span>Thời gian:</span><strong>{Math.ceil(mcqs.length * 1.5)} phút</strong></div>
              <div className="flex justify-between"><span>Topics:</span>
                <strong>{Array.from(new Set(mcqs.map(m => m.topic))).length} topic</strong>
              </div>
            </div>
          )}
          <Button onClick={startQuiz} className="w-full h-12 text-base" disabled={mcqs.length === 0}>
            🚀 Bắt đầu làm bài
          </Button>
          <p className="text-center text-xs text-slate-400">
            Không có đề thi? Nhờ giảng viên export JSON từ hệ thống
          </p>
        </CardContent>
      </Card>
    </div>
  )

  // ── TAKING PHASE ─────────────────────────────────────────────
  if (phase === "taking") {
    const mcq = mcqs[currentQ]
    const progress = ((currentQ + 1) / mcqs.length) * 100
    const timePercent = (timeLeft / (mcqs.length * 90)) * 100
    const timeWarning = timeLeft < 120

    return (
      <div className="min-h-screen bg-slate-50">
        {/* Header bar */}
        <div className="bg-white border-b px-4 py-3 flex items-center justify-between sticky top-0 z-10 shadow-sm">
          <div className="flex items-center gap-3">
            <span className="font-semibold text-sm">{studentName}</span>
            <Badge variant="outline" className="text-xs">
              Câu {currentQ + 1}/{mcqs.length}
            </Badge>
          </div>
          <div className={`flex items-center gap-2 font-mono font-bold ${timeWarning ? "text-red-500 animate-pulse" : "text-slate-700"}`}>
            ⏱ {formatTime(timeLeft)}
          </div>
          <Button size="sm" onClick={handleSubmit} variant="outline">Nộp bài</Button>
        </div>

        {/* Progress */}
        <div className="bg-white px-4 py-2 border-b">
          <Progress value={progress} className="h-1.5" />
          <div className={`h-1 mt-1 rounded-full transition-all ${timeWarning ? "bg-red-400" : "bg-blue-200"}`}
            style={{ width: `${timePercent}%` }} />
        </div>

        <div className="max-w-2xl mx-auto p-4 space-y-4">
          {/* Question */}
          <Card>
            <CardContent className="p-5">
              <div className="flex items-start gap-3">
                <span className="bg-slate-800 text-white text-sm font-bold w-8 h-8 rounded-full flex items-center justify-center shrink-0">
                  {currentQ + 1}
                </span>
                <p className="text-base font-medium leading-relaxed">{mcq.question_text}</p>
              </div>
            </CardContent>
          </Card>

          {/* Options */}
          <div className="space-y-2">
            {Object.entries(mcq.options).map(([key, value]) => (
              <button key={key} onClick={() => selectAnswer(key)} suppressHydrationWarning
                className={`w-full text-left px-4 py-3 rounded-xl border-2 transition-all text-sm font-medium ${
                  answers[currentQ] === key
                    ? "border-slate-800 bg-slate-800 text-white shadow-md"
                    : "border-slate-200 bg-white hover:border-slate-400 hover:bg-slate-50"
                }`}>
                <span className={`inline-flex items-center justify-center w-6 h-6 rounded-full mr-3 text-xs font-bold ${
                  answers[currentQ] === key ? "bg-white text-slate-800" : "bg-slate-100 text-slate-600"
                }`}>{key}</span>
                {value}
              </button>
            ))}
          </div>

          {/* Navigation */}
          <div className="flex justify-between pt-2">
            <Button variant="outline" onClick={() => setCurrentQ(Math.max(0, currentQ - 1))}
              disabled={currentQ === 0}>← Trước</Button>
            <div className="flex gap-1 overflow-x-auto max-w-xs">
              {mcqs.map((_, i) => (
                <button key={i} onClick={() => setCurrentQ(i)} suppressHydrationWarning
                  className={`w-8 h-8 rounded text-xs font-medium shrink-0 transition-all ${
                    i === currentQ ? "bg-slate-800 text-white" :
                    answers[i] ? "bg-green-100 text-green-700 border border-green-300" :
                    "bg-slate-100 text-slate-500 hover:bg-slate-200"
                  }`}>{i + 1}</button>
              ))}
            </div>
            {currentQ < mcqs.length - 1
              ? <Button onClick={() => setCurrentQ(currentQ + 1)}>Tiếp →</Button>
              : <Button onClick={handleSubmit} className="bg-green-600 hover:bg-green-700">Nộp bài ✓</Button>
            }
          </div>
        </div>
      </div>
    )
  }

  // ── RESULTS PHASE ─────────────────────────────────────────────
  const { correct, total, score, elapsed, topicStats, details } = calcResults()
  const grade = getGrade(score)

  return (
    <div className="min-h-screen bg-slate-50 p-4">
      <div className="max-w-2xl mx-auto space-y-4">
        {/* Score card */}
        <Card className="text-center overflow-hidden">
          <div className="bg-gradient-to-r from-slate-800 to-slate-600 p-8 text-white">
            <h2 className="text-lg font-medium opacity-80 mb-1">{studentName} — {studentId}</h2>
            <div className="text-7xl font-bold">{score.toFixed(1)}</div>
            <div className="text-xl opacity-80">/ 10.0</div>
            <div className={`text-xl font-semibold mt-2 ${grade.color.replace("text-", "text-").replace("-600", "-300")}`}>
              {grade.label}
            </div>
          </div>
          <CardContent className="p-4">
            <div className="grid grid-cols-3 gap-4 text-center">
              <div><div className="text-2xl font-bold text-green-600">{correct}</div>
                <div className="text-xs text-slate-500">Câu đúng</div></div>
              <div><div className="text-2xl font-bold text-red-500">{total - correct}</div>
                <div className="text-xs text-slate-500">Câu sai</div></div>
              <div><div className="text-2xl font-bold text-blue-600">{Math.floor(elapsed/60)}:{(elapsed%60).toString().padStart(2,"0")}</div>
                <div className="text-xs text-slate-500">Thời gian</div></div>
            </div>
          </CardContent>
        </Card>

        {/* Topic analysis */}
        <Card>
          <CardHeader><CardTitle className="text-base">📈 Phân tích theo topic</CardTitle></CardHeader>
          <CardContent className="space-y-3">
            {Object.entries(topicStats).map(([topic, stat]) => {
              const pct = (stat.correct / stat.total) * 100
              return (
                <div key={topic}>
                  <div className="flex justify-between text-sm mb-1">
                    <span className="font-medium truncate mr-2">{topic}</span>
                    <span className={pct >= 70 ? "text-green-600" : "text-red-500"}>
                      {stat.correct}/{stat.total} ({pct.toFixed(0)}%)
                    </span>
                  </div>
                  <div className="h-2 bg-slate-100 rounded-full overflow-hidden">
                    <div className={`h-full rounded-full transition-all ${pct >= 70 ? "bg-green-500" : "bg-red-400"}`}
                      style={{ width: `${pct}%` }} />
                  </div>
                </div>
              )
            })}
          </CardContent>
        </Card>

        {/* Detailed review */}
        <div className="space-y-2">
          <h3 className="font-semibold text-slate-700">🔍 Chi tiết từng câu</h3>
          {details.map(({ mcq, selected, isCorrect }, i) => (
            <Card key={i} className={`border-l-4 ${isCorrect ? "border-l-green-500" : "border-l-red-500"}`}>
              <CardContent className="p-4">
                <p className="text-sm font-medium mb-2">{i+1}. {mcq.question_text}</p>
                <div className="space-y-1">
                  {Object.entries(mcq.options).map(([k, v]) => {
                    const isSelected = k === selected
                    const isCorrectAns = mcq.correct_answers.includes(k)
                    return (
                      <div key={k} className={`px-3 py-1.5 rounded text-xs ${
                        isCorrectAns ? "bg-green-50 text-green-700 font-medium" :
                        isSelected && !isCorrectAns ? "bg-red-50 text-red-600 line-through" :
                        "text-slate-500"
                      }`}>
                        {isCorrectAns ? "✓" : isSelected ? "✗" : "○"} {k}. {v}
                      </div>
                    )
                  })}
                </div>
              </CardContent>
            </Card>
          ))}
        </div>

        <Button onClick={() => setPhase("setup")} className="w-full" variant="outline">
          🔄 Làm lại
        </Button>
      </div>
    </div>
  )
}
