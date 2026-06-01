"use client"

import { useEffect, useMemo, useState } from "react"
import { useParams, useRouter } from "next/navigation"
import { api } from "@/lib/api"
import { PracticeDetail, PracticeQuestion } from "@/types"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Progress } from "@/components/ui/progress"
import { MathText } from "@/components/math-text"
import { toast } from "sonner"
import { ArrowLeft, CheckCircle2, FileText, Send, XCircle } from "lucide-react"

interface PracticeExam {
  task_id: string
  exam_id: string
  exam_name: string
  n_questions: number
  questions: PracticeQuestion[]
}

interface SubmitResult {
  score: number
  n_correct: number
  n_total: number
  details: PracticeDetail[]
}

export default function TakeExamPage() {
  const { id } = useParams()
  const router = useRouter()
  const taskId = String(id)
  const [exam, setExam] = useState<PracticeExam | null>(null)
  const [answers, setAnswers] = useState<Record<string, string>>({})
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [result, setResult] = useState<SubmitResult | null>(null)
  const [startedAt] = useState(() => Date.now())

  useEffect(() => {
    if (!localStorage.getItem("access_token")) {
      router.push("/login")
      return
    }
    api.get(`/practice/${taskId}`)
      .then(({ data }) => setExam(data))
      .catch(() => toast.error("Không tải được đề thi"))
      .finally(() => setLoading(false))
  }, [router, taskId])

  const answeredCount = useMemo(() => Object.keys(answers).length, [answers])
  const progress = exam?.questions.length ? (answeredCount / exam.questions.length) * 100 : 0

  const selectAnswer = (questionId: string, optionKey: string) => {
    if (result) return
    setAnswers((current) => ({ ...current, [questionId]: optionKey }))
  }

  const submit = async () => {
    if (!exam || submitting) return
    const unanswered = exam.questions.length - answeredCount
    if (unanswered > 0 && !window.confirm(`Còn ${unanswered} câu chưa trả lời. Bạn vẫn muốn nộp bài?`)) {
      return
    }
    setSubmitting(true)
    try {
      const durationSeconds = Math.round((Date.now() - startedAt) / 1000)
      const { data } = await api.post(`/practice/${taskId}/submit`, {
        answers,
        duration_seconds: durationSeconds,
      })
      setResult({
        score: data.score,
        n_correct: data.n_correct,
        n_total: data.n_total,
        details: data.details || [],
      })
      toast.success("Đã nộp bài và lưu lịch sử làm đề")
    } catch {
      toast.error("Không nộp được bài làm")
    } finally {
      setSubmitting(false)
    }
  }

  const downloadAnswerPdf = async () => {
    const { data } = await api.get(`/export/pdf/${taskId}?include_answers=true`, { responseType: "blob" })
    const link = document.createElement("a")
    link.href = URL.createObjectURL(data)
    link.download = `${exam?.exam_name || "de_thi"}_answers.pdf`
    link.click()
  }

  if (loading) return <div className="text-center py-20 text-slate-400">Đang tải đề thi...</div>
  if (!exam) return <div className="text-center py-20 text-slate-400">Không tìm thấy đề thi</div>

  const questionsToRender = result?.details || exam.questions

  return (
    <div className="space-y-5">
      <div className="sticky top-0 z-30 -mx-8 -mt-8 flex flex-wrap items-start justify-between gap-3 border-b border-slate-200/70 bg-[#F4F7FC]/95 px-8 py-4 backdrop-blur dark:border-slate-700 dark:bg-slate-900/95">
        <div className="min-w-0">
          <Button variant="ghost" size="sm" onClick={() => router.back()}>
            <ArrowLeft size={15} />
            Quay lại
          </Button>
          <h1 className="mt-2 text-2xl font-bold text-slate-800">{exam.exam_name}</h1>
          <p className="mt-1 text-sm text-slate-500">
            {result ? "Kết quả làm bài" : "Chọn đáp án cho từng câu rồi nộp bài để xem đáp án đúng"}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {result ? (
            <>
              <Button variant="outline" onClick={downloadAnswerPdf}>
                <FileText size={16} />
                PDF đáp án
              </Button>
              <Button onClick={() => router.push("/dashboard/history")}>Xem lịch sử</Button>
            </>
          ) : (
            <Button onClick={submit} disabled={submitting}>
              <Send size={16} />
              {submitting ? "Đang nộp" : "Nộp bài"}
            </Button>
          )}
        </div>
      </div>

      {result ? (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          <Card><CardContent className="p-4"><p className="text-xs uppercase text-slate-500">Điểm</p><p className="mt-1 text-3xl font-bold text-slate-800">{result.score.toFixed(1)}</p></CardContent></Card>
          <Card><CardContent className="p-4"><p className="text-xs uppercase text-slate-500">Số câu đúng</p><p className="mt-1 text-3xl font-bold text-emerald-600">{result.n_correct}/{result.n_total}</p></CardContent></Card>
          <Card><CardContent className="p-4"><p className="text-xs uppercase text-slate-500">Tỷ lệ đúng</p><p className="mt-1 text-3xl font-bold text-blue-600">{Math.round((result.n_correct / result.n_total) * 100)}%</p></CardContent></Card>
        </div>
      ) : (
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between text-sm text-slate-600">
              <span>Tiến độ làm bài</span>
              <span>{answeredCount}/{exam.questions.length} câu</span>
            </div>
            <Progress value={progress} className="mt-3 h-3" />
          </CardContent>
        </Card>
      )}

      <div className="space-y-3">
        {questionsToRender.map((question, index) => {
          const selected = result
            ? (question as PracticeDetail).selected
            : answers[question.question_id]
          const correctAnswers = result ? (question as PracticeDetail).correct_answers : []
          const isCorrect = result ? (question as PracticeDetail).is_correct : false
          return (
            <Card key={question.question_id || index}>
              <CardContent className="p-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <p className="min-w-0 flex-1 text-sm font-medium text-slate-800">
                    {index + 1}. <MathText text={question.question_text} />
                  </p>
                  {result && (
                    <Badge variant="outline" className={isCorrect ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "border-red-200 bg-red-50 text-red-700"}>
                      {isCorrect ? <CheckCircle2 size={13} /> : <XCircle size={13} />}
                      {isCorrect ? "Đúng" : "Sai"}
                    </Badge>
                  )}
                </div>
                <div className="mt-3 grid grid-cols-1 gap-2">
                  {Object.entries(question.options).map(([key, value]) => {
                    const isSelected = selected === key
                    const isAnswer = correctAnswers.includes(key)
                    const className = result
                      ? isAnswer
                        ? "border-emerald-300 bg-emerald-50 text-emerald-800"
                        : isSelected
                          ? "border-red-300 bg-red-50 text-red-800"
                          : "border-slate-200 bg-slate-50 text-slate-600"
                      : isSelected
                        ? "border-blue-300 bg-blue-50 text-blue-800"
                        : "border-slate-200 bg-white text-slate-700 hover:border-blue-200 hover:bg-blue-50"
                    return (
                      <button
                        key={key}
                        type="button"
                        onClick={() => selectAnswer(question.question_id, key)}
                        className={`rounded-lg border px-3 py-2 text-left text-sm transition-colors ${className}`}
                      >
                        <span className="font-semibold">{key}.</span>{" "}
                        <MathText text={value} />
                      </button>
                    )
                  })}
                </div>
                <div className="mt-3 flex flex-wrap gap-2">
                  <Badge variant="outline" className="text-xs">{question.chapter_label || question.chapter_id}</Badge>
                  <Badge variant="outline" className="text-xs">{question.topic}</Badge>
                  <Badge variant="outline" className="text-xs">{question.difficulty_label}</Badge>
                </div>
              </CardContent>
            </Card>
          )
        })}
      </div>
    </div>
  )
}
