"use client"
import { useEffect, useState } from "react"
import { useParams, useRouter, useSearchParams } from "next/navigation"
import { api } from "@/lib/api"
import { MCQ, PracticeQuestion } from "@/types"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { MathText } from "@/components/math-text"
import { toast } from "sonner"
import { Eye, EyeOff, PlayCircle } from "lucide-react"

type ExamQuestion = PracticeQuestion | MCQ

export default function ExamDetailPage() {
  const { id } = useParams()
  const router = useRouter()
  const searchParams = useSearchParams()
  const [questions, setQuestions] = useState<ExamQuestion[]>([])
  const [examName, setExamName] = useState("Đề thi")
  const [hasAttempt, setHasAttempt] = useState(false)
  const [showAnswers, setShowAnswers] = useState(searchParams.get("answers") === "1")
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    async function loadExam() {
      setLoading(true)
      try {
        const [practiceRes, attemptsRes] = await Promise.all([
          api.get(`/practice/${id}`),
          api.get(`/practice/${id}/attempts`),
        ])
        const attempted = (attemptsRes.data.attempts || []).length > 0
        setHasAttempt(attempted)
        setExamName(practiceRes.data.exam_name || "Đề thi")
        if (showAnswers && attempted) {
          const resultRes = await api.get(`/results/${id}?include_answers=true`)
          setQuestions(resultRes.data.mcqs || [])
        } else {
          if (showAnswers && !attempted) {
            toast.error("Bạn cần nộp bài trước khi xem đáp án")
            setShowAnswers(false)
          }
          setQuestions(practiceRes.data.questions || [])
        }
      } catch {
        toast.error("Không tải được đề thi")
      } finally {
        setLoading(false)
      }
    }
    void loadExam()
  }, [id, showAnswers])

  const downloadPdf = async (withAnswers: boolean) => {
    try {
      const { data } = await api.get(
        `/export/pdf/${id}?include_answers=${withAnswers}`,
        { responseType: "blob" }
      )
      const a = document.createElement("a")
      a.href = URL.createObjectURL(data)
      a.download = `exam_${id}_${withAnswers ? "answers" : "exam"}.pdf`
      a.click()
    } catch {
      toast.error(withAnswers ? "Bạn cần nộp bài trước khi tải đáp án" : "Không tải được PDF")
    }
  }

  if (loading) return <div className="text-center py-20 text-slate-400">Đang tải...</div>

  return (
    <div className="space-y-4">
      <div className="sticky top-0 z-30 -mx-8 -mt-8 flex flex-wrap items-center justify-between gap-3 border-b border-slate-200/70 bg-[#F4F7FC]/95 px-8 py-4 backdrop-blur dark:border-slate-700 dark:bg-slate-900/95">
        <div className="min-w-0">
          <Button variant="ghost" size="sm" onClick={() => router.back()}>← Quay lại</Button>
          <h1 className="text-xl font-bold mt-1">📋 {examName} — {questions.length} câu</h1>
          <p className="mt-1 text-sm text-slate-500">
            {hasAttempt
              ? "Bạn có thể chuyển giữa đề thi và đáp án."
              : "Đáp án chỉ mở sau khi bạn nộp bài."}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            size="sm"
            variant={showAnswers ? "outline" : "default"}
            onClick={() => setShowAnswers(false)}
          >
            <EyeOff size={15} />Xem đề
          </Button>
          <Button
            size="sm"
            variant={showAnswers ? "default" : "outline"}
            disabled={!hasAttempt}
            onClick={() => setShowAnswers(true)}
          >
            <Eye size={15} />Xem đáp án
          </Button>
          <Button size="sm" onClick={() => router.push(`/dashboard/take/${id}`)}>
            <PlayCircle size={15} />Bắt đầu làm đề
          </Button>
          <Button size="sm" variant="outline" onClick={() => downloadPdf(false)}>📋 PDF Đề</Button>
          {hasAttempt && (
            <Button size="sm" variant="outline" onClick={() => downloadPdf(true)}>🔑 PDF Đáp án</Button>
          )}
        </div>
      </div>
      {questions.map((mcq, i) => {
        const correctAnswers = showAnswers && "correct_answers" in mcq ? mcq.correct_answers : []
        return (
        <Card key={i}>
          <CardContent className="p-4">
            <p className="font-medium text-sm mb-3">
              {i+1}. <MathText text={mcq.question_text} />
            </p>
            <div className="space-y-1">
              {Object.entries(mcq.options).map(([k, v]) => (
                <div key={k} className={`px-3 py-2 rounded text-sm ${
                  showAnswers && correctAnswers.includes(k)
                    ? "bg-green-50 border border-green-200 text-green-800 font-medium"
                    : "bg-slate-50 border border-slate-100 text-slate-600"
                }`}>
                  {showAnswers && correctAnswers.includes(k) ? "✓" : " "} {k}. <MathText text={v} />
                </div>
              ))}
            </div>
            {showAnswers && correctAnswers.length > 0 && (
              <div className="mt-3 rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm font-medium text-emerald-700">
                Đáp án: {correctAnswers.join(", ")}
              </div>
            )}
            <div className="flex gap-2 mt-2">
              {"chapter_label" in mcq && mcq.chapter_label ? <Badge variant="outline" className="text-xs">{mcq.chapter_label}</Badge> : null}
              <Badge variant="outline" className="text-xs">{mcq.topic}</Badge>
              <Badge variant="outline" className="text-xs">{mcq.difficulty_label}</Badge>
            </div>
          </CardContent>
        </Card>
        )
      })}
    </div>
  )
}
