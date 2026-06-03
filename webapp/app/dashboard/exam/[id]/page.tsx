"use client";
import { useEffect, useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { api } from "@/lib/api";
import { MCQ, PracticeQuestion } from "@/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { MathText } from "@/components/math-text";
import { toast } from "sonner";
import { Eye, EyeOff, PlayCircle, FileText, KeyRound } from "lucide-react";

type ExamQuestion = PracticeQuestion | MCQ;

export default function ExamDetailPage() {
  const { id } = useParams();
  const router = useRouter();
  const searchParams = useSearchParams();
  const [questions, setQuestions] = useState<ExamQuestion[]>([]);
  const [examName, setExamName] = useState("Đề thi");
  const [hasAttempt, setHasAttempt] = useState(false);
  const [showAnswers, setShowAnswers] = useState(
    searchParams.get("answers") === "1",
  );
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function loadExam() {
      setLoading(true);
      try {
        const [practiceRes, attemptsRes] = await Promise.all([
          api.get(`/practice/${id}`),
          api.get(`/practice/${id}/attempts`),
        ]);
        const attempted = (attemptsRes.data.attempts || []).length > 0;
        setHasAttempt(attempted);
        setExamName(practiceRes.data.exam_name || "Đề thi");
        if (showAnswers && attempted) {
          const resultRes = await api.get(
            `/results/${id}?include_answers=true`,
          );
          setQuestions(resultRes.data.mcqs || []);
        } else {
          if (showAnswers && !attempted) {
            toast.error("Bạn cần nộp bài trước khi xem đáp án");
            setShowAnswers(false);
          }
          setQuestions(practiceRes.data.questions || []);
        }
      } catch {
        toast.error("Không tải được đề thi");
      } finally {
        setLoading(false);
      }
    }
    void loadExam();
  }, [id, showAnswers]);

  const downloadPdf = async (withAnswers: boolean) => {
    try {
      const { data } = await api.get(
        `/export/pdf/${id}?include_answers=${withAnswers}`,
        { responseType: "blob" },
      );
      const a = document.createElement("a");
      a.href = URL.createObjectURL(data);
      a.download = `exam_${id}_${withAnswers ? "answers" : "exam"}.pdf`;
      a.click();
    } catch {
      toast.error(
        withAnswers
          ? "Bạn cần nộp bài trước khi tải đáp án"
          : "Không tải được PDF",
      );
    }
  };

  if (loading)
    return <div className="text-center py-20 text-slate-400">Đang tải...</div>;

  return (
    <div className="space-y-4">
      {/* ── Sticky header ── */}
      <div className="sticky -top-8 z-30 -mx-8 -mt-8 border-b border-slate-200/70 bg-[#F4F7FC]/95 px-8 py-4 backdrop-blur dark:border-slate-700 dark:bg-slate-900/95">
        <Button
          variant="ghost"
          size="sm"
          className="mb-1 text-slate-500 hover:text-slate-700 px-0"
          onClick={() => router.back()}
        >
          ← Quay lại
        </Button>

        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="min-w-0">
            <h1 className="text-xl font-bold text-slate-900 dark:text-white">
              📋 {examName} — {questions.length} câu
            </h1>
            <p className="mt-0.5 text-sm text-slate-500">
              {hasAttempt
                ? "Bạn có thể chuyển giữa đề thi và đáp án."
                : "Đáp án chỉ mở sau khi bạn nộp bài."}
            </p>
          </div>

          {/* Action buttons — matches screenshot */}
          <div className="flex flex-wrap items-center gap-2">
            {/* Xem đề */}
            <Button
              size="sm"
              onClick={() => setShowAnswers(false)}
              className={
                !showAnswers
                  ? "bg-[#1a2744] text-white hover:bg-[#1a2744]/90"
                  : "bg-white border border-slate-200 text-slate-700 hover:bg-slate-50"
              }
            >
              <EyeOff size={15} />
              Xem đề
            </Button>

            {/* Xem đáp án */}
            <Button
              size="sm"
              disabled={!hasAttempt}
              onClick={() => setShowAnswers(true)}
              className={
                showAnswers
                  ? "bg-[#1a2744] text-white hover:bg-[#1a2744]/90"
                  : "bg-white border border-slate-200 text-slate-700 hover:bg-slate-50"
              }
            >
              <Eye size={15} />
              Xem đáp án
            </Button>

            {/* Bắt đầu làm đề */}
            <Button
              size="sm"
              className="bg-[#1a2744] text-white hover:bg-[#1a2744]/90"
              onClick={() => router.push(`/dashboard/take/${id}`)}
            >
              <PlayCircle size={15} />
              Bắt đầu làm đề
            </Button>

            {/* PDF Đề */}
            <Button
              size="sm"
              variant="outline"
              className="border-slate-200 text-slate-700 hover:bg-slate-50 gap-1.5"
              onClick={() => downloadPdf(false)}
            >
              <FileText size={14} className="text-orange-400" />
              PDF Đề
            </Button>

            {/* PDF Đáp án — chỉ hiện khi đã có attempt */}
            {hasAttempt && (
              <Button
                size="sm"
                variant="outline"
                className="border-slate-200 text-slate-700 hover:bg-slate-50 gap-1.5"
                onClick={() => downloadPdf(true)}
              >
                <KeyRound size={14} className="text-yellow-400" />
                PDF Đáp án
              </Button>
            )}
          </div>
        </div>
      </div>

      {/* ── Question list ── */}
      {questions.map((mcq, i) => {
        const correctAnswers =
          showAnswers && "correct_answers" in mcq ? mcq.correct_answers : [];

        return (
          <div
            key={i}
            className="rounded-2xl border border-slate-200 bg-white shadow-sm dark:border-slate-700 dark:bg-slate-800"
          >
            <div className="p-5">
              {/* Question text */}
              <p className="font-semibold text-slate-900 dark:text-white mb-4 leading-relaxed">
                {i + 1}. <MathText text={mcq.question_text} />
              </p>

              {/* Options */}
              <div className="space-y-2">
                {Object.entries(mcq.options).map(([k, v]) => {
                  const isCorrect = showAnswers && correctAnswers.includes(k);
                  return (
                    <div
                      key={k}
                      className={`flex items-start gap-3 rounded-xl border px-4 py-3 text-sm transition-colors ${
                        isCorrect
                          ? "border-emerald-200 bg-emerald-50 text-emerald-800"
                          : "border-slate-100 bg-slate-50 text-slate-700 dark:border-slate-600 dark:bg-slate-700/40 dark:text-slate-300"
                      }`}
                    >
                      {/* Radio circle */}
                      <span
                        className={`mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full border-2 ${
                          isCorrect
                            ? "border-emerald-500 bg-emerald-500"
                            : "border-slate-300 dark:border-slate-500"
                        }`}
                      >
                        {isCorrect && (
                          <span className="h-1.5 w-1.5 rounded-full bg-white" />
                        )}
                      </span>

                      <span>
                        <span className="font-medium">{k}.</span>{" "}
                        <MathText text={v} />
                      </span>
                    </div>
                  );
                })}
              </div>

              {/* Answer summary */}
              {showAnswers && correctAnswers.length > 0 && (
                <div className="mt-3 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-2.5 text-sm font-semibold text-emerald-700">
                  Đáp án: {correctAnswers.join(", ")}
                </div>
              )}

              {/* Badges */}
              <div className="flex flex-wrap gap-2 mt-3">
                {"chapter_label" in mcq && mcq.chapter_label ? (
                  <Badge
                    variant="outline"
                    className="rounded-full text-xs text-slate-500 border-slate-200"
                  >
                    {mcq.chapter_label}
                  </Badge>
                ) : null}
                <Badge
                  variant="outline"
                  className="rounded-full text-xs text-slate-500 border-slate-200"
                >
                  {mcq.topic}
                </Badge>
                <Badge
                  variant="outline"
                  className="rounded-full text-xs text-slate-500 border-slate-200"
                >
                  {mcq.difficulty_label}
                </Badge>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
