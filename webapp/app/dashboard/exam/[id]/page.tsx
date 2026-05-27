"use client"
import { useEffect, useState } from "react"
import { useParams, useRouter } from "next/navigation"
import { api } from "@/lib/api"
import { MCQ } from "@/types"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { toast } from "sonner"

export default function ExamDetailPage() {
  const { id } = useParams()
  const router = useRouter()
  const [mcqs, setMcqs] = useState<MCQ[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.get(`/results/${id}`)
      .then(({ data }) => setMcqs(data.mcqs || []))
      .catch(() => toast.error("Không tải được kết quả"))
      .finally(() => setLoading(false))
  }, [id])

  const downloadPdf = async (withAnswers: boolean) => {
    const { data } = await api.get(
      `/export/pdf/${id}?include_answers=${withAnswers}`,
      { responseType: "blob" }
    )
    const a = document.createElement("a")
    a.href = URL.createObjectURL(data)
    a.download = `exam_${id}_${withAnswers ? "answers" : "exam"}.pdf`
    a.click()
  }

  if (loading) return <div className="text-center py-20 text-slate-400">Đang tải...</div>

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <Button variant="ghost" size="sm" onClick={() => router.back()}>← Quay lại</Button>
          <h1 className="text-xl font-bold mt-1">📋 Chi tiết đề thi — {mcqs.length} câu</h1>
        </div>
        <div className="flex gap-2">
          <Button size="sm" variant="outline" onClick={() => downloadPdf(false)}>📋 PDF Đề</Button>
          <Button size="sm" variant="outline" onClick={() => downloadPdf(true)}>🔑 PDF Đáp án</Button>
        </div>
      </div>
      {mcqs.map((mcq, i) => (
        <Card key={i}>
          <CardContent className="p-4">
            <p className="font-medium text-sm mb-3">{i+1}. {mcq.question_text}</p>
            <div className="space-y-1">
              {Object.entries(mcq.options).map(([k, v]) => (
                <div key={k} className={`px-3 py-2 rounded text-sm ${
                  mcq.correct_answers.includes(k)
                    ? "bg-green-50 border border-green-200 text-green-800 font-medium"
                    : "bg-slate-50 border border-slate-100 text-slate-600"
                }`}>
                  {mcq.correct_answers.includes(k) ? "✓" : " "} {k}. {v}
                </div>
              ))}
            </div>
            <div className="flex gap-2 mt-2">
              <Badge variant="outline" className="text-xs">{mcq.topic}</Badge>
              <Badge variant="outline" className="text-xs">{mcq.difficulty_label}</Badge>
              <span className="text-xs text-slate-400 ml-auto">Score: {mcq.evaluation?.quality_score?.toFixed(2)}</span>
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  )
}
