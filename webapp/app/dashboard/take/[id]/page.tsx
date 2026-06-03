"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { PracticeDetail, PracticeQuestion } from "@/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { MathText } from "@/components/math-text";
import { toast } from "sonner";
import { ArrowLeft, CheckCircle2, FileText, Send, XCircle } from "lucide-react";

interface PracticeExam {
  task_id: string;
  exam_id: string;
  exam_name: string;
  n_questions: number;
  questions: PracticeQuestion[];
}

interface SubmitResult {
  score: number;
  n_correct: number;
  n_total: number;
  details: PracticeDetail[];
}

export default function TakeExamPage() {
  const { id } = useParams();
  const router = useRouter();
  const taskId = String(id);

  const [exam, setExam] = useState<PracticeExam | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<SubmitResult | null>(null);
  const [startedAt] = useState(() => Date.now());

  useEffect(() => {
    if (!localStorage.getItem("access_token")) {
      router.push("/login");
      return;
    }

    api
      .get(`/practice/${taskId}`)
      .then(({ data }) => setExam(data))
      .catch(() => toast.error("Không tải được đề thi"))
      .finally(() => setLoading(false));
  }, [router, taskId]);

  const answeredCount = useMemo(() => Object.keys(answers).length, [answers]);

  const progress = exam?.questions.length
    ? (answeredCount / exam.questions.length) * 100
    : 0;

  const selectAnswer = (questionId: string, optionKey: string) => {
    if (result) return;

    setAnswers((current) => ({
      ...current,
      [questionId]: optionKey,
    }));
  };

  const submit = async () => {
    if (!exam || submitting) return;

    const unanswered = exam.questions.length - answeredCount;

    if (
      unanswered > 0 &&
      !window.confirm(
        `Còn ${unanswered} câu chưa trả lời. Bạn vẫn muốn nộp bài?`,
      )
    ) {
      return;
    }

    setSubmitting(true);

    try {
      const durationSeconds = Math.round((Date.now() - startedAt) / 1000);

      const { data } = await api.post(`/practice/${taskId}/submit`, {
        answers,
        duration_seconds: durationSeconds,
      });

      setResult({
        score: data.score,
        n_correct: data.n_correct,
        n_total: data.n_total,
        details: data.details || [],
      });

      toast.success("Đã nộp bài và lưu lịch sử làm đề");
    } catch {
      toast.error("Không nộp được bài làm");
    } finally {
      setSubmitting(false);
    }
  };

  const downloadAnswerPdf = async () => {
    const { data } = await api.get(
      `/export/pdf/${taskId}?include_answers=true`,
      { responseType: "blob" },
    );

    const link = document.createElement("a");

    link.href = URL.createObjectURL(data);

    link.download = `${exam?.exam_name || "de_thi"}_answers.pdf`;

    link.click();
  };

  if (loading) {
    return (
      <div className="py-20 text-center text-slate-400">Đang tải đề thi...</div>
    );
  }

  if (!exam) {
    return (
      <div className="py-20 text-center text-slate-400">
        Không tìm thấy đề thi
      </div>
    );
  }

  const questionsToRender = result?.details || exam.questions;

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="-mx-8 -mt-8 flex items-center justify-between px-8 pt-4 pb-2">
        <Button variant="ghost" size="sm" onClick={() => router.back()}>
          <ArrowLeft size={15} />
          Quay lại
        </Button>

        <div className="flex gap-2">
          {result ? (
            <>
              <Button variant="outline" onClick={downloadAnswerPdf}>
                <FileText size={16} />
                PDF đáp án
              </Button>

              <Button onClick={() => router.push("/dashboard/history")}>
                Xem lịch sử
              </Button>
            </>
          ) : (
            <Button
              onClick={submit}
              disabled={submitting}
              className="bg-slate-900 text-white hover:bg-slate-700 dark:bg-white dark:text-slate-900 dark:hover:bg-slate-200"
            >
              <Send size={16} />
              {submitting ? "Đang nộp" : "Nộp bài"}
            </Button>
          )}
        </div>
      </div>

      {/* Title */}
      <div>
        <h1 className="text-2xl font-bold text-slate-900 dark:text-white">
          {exam.exam_name}
        </h1>

        <p className="mt-1 text-sm text-slate-500">
          {result
            ? "Kết quả làm bài"
            : "Chọn đáp án cho từng câu rồi nộp bài để xem đáp án đúng"}
        </p>
      </div>

      {/* Result / Progress */}
      {result ? (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          <Card>
            <CardContent className="p-4">
              <p className="text-xs uppercase text-slate-500">Điểm</p>

              <p className="mt-1 text-3xl font-bold text-slate-800 dark:text-white">
                {result.score.toFixed(1)}
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="p-4">
              <p className="text-xs uppercase text-slate-500">Số câu đúng</p>

              <p className="mt-1 text-3xl font-bold text-emerald-600">
                {result.n_correct}/{result.n_total}
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="p-4">
              <p className="text-xs uppercase text-slate-500">Tỷ lệ đúng</p>

              <p className="mt-1 text-3xl font-bold text-blue-600">
                {Math.round((result.n_correct / result.n_total) * 100)}%
              </p>
            </CardContent>
          </Card>
        </div>
      ) : (
        <Card>
          <CardContent className="flex items-center gap-4 p-4">
            <div className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-lg bg-slate-100 text-slate-400 dark:bg-slate-800">
              <svg
                width="18"
                height="18"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                strokeWidth={2}
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
                />
              </svg>
            </div>

            <div className="min-w-0 flex-1">
              <div className="mb-2 flex items-center justify-between">
                <span className="text-sm text-slate-600 dark:text-slate-400">
                  Tiến độ làm bài
                </span>

                <span className="text-sm text-slate-500">
                  {answeredCount}/{exam.questions.length} câu
                </span>
              </div>

              <div className="h-1.5 w-full rounded-full bg-slate-100 dark:bg-slate-700">
                <div
                  className="h-1.5 rounded-full bg-blue-500 transition-all duration-300"
                  style={{ width: `${progress}%` }}
                />
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Questions */}
      <div className="space-y-4">
        {questionsToRender.map((question, index) => {
          const selected = result
            ? (question as PracticeDetail).selected
            : answers[question.question_id];

          const correctAnswers = result
            ? (question as PracticeDetail).correct_answers
            : [];

          const isCorrect = result
            ? (question as PracticeDetail).is_correct
            : false;

          const explanation = result
            ? (question as PracticeDetail).explanation
            : "";

          return (
            <Card
              key={question.question_id || index}
              className="overflow-hidden"
            >
              <CardContent className="p-0">
                {/* Question header */}
                <div className="flex gap-4 p-5 pb-3">
                  <div className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-lg bg-slate-100 text-sm font-bold text-slate-700 dark:bg-slate-800 dark:text-slate-300">
                    {index + 1}
                  </div>

                  <div className="min-w-0 flex-1">
                    <div className="mb-2 flex items-center justify-between gap-2">
                      <Badge className="border-0 bg-blue-50 text-xs font-medium text-blue-600 hover:bg-blue-50 dark:bg-blue-900/30 dark:text-blue-400">
                        Câu hỏi trắc nghiệm
                      </Badge>

                      {result && (
                        <Badge
                          variant="outline"
                          className={
                            isCorrect
                              ? "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-700 dark:bg-emerald-900/20 dark:text-emerald-400"
                              : "border-red-200 bg-red-50 text-red-700 dark:border-red-700 dark:bg-red-900/20 dark:text-red-400"
                          }
                        >
                          {isCorrect ? (
                            <CheckCircle2 size={13} />
                          ) : (
                            <XCircle size={13} />
                          )}

                          {isCorrect ? "Đúng" : "Sai"}
                        </Badge>
                      )}
                    </div>

                    <p className="leading-relaxed text-sm font-medium text-slate-900 dark:text-slate-100">
                      <MathText text={question.question_text} />
                    </p>
                  </div>
                </div>

                {/* Options */}
                <div className="space-y-2 px-5 pb-4 pl-[4.25rem]">
                  {Object.entries(question.options).map(([key, value]) => {
                    const isSelected = selected === key;

                    const isAnswer = correctAnswers.includes(key);

                    let optionClass =
                      "flex items-center gap-3 w-full rounded-xl border px-4 py-3 text-left text-sm transition-colors ";

                    let radioClass =
                      "flex-shrink-0 w-4 h-4 rounded-full border-2 flex items-center justify-center ";

                    if (result) {
                      if (isAnswer) {
                        optionClass +=
                          "border-emerald-300 bg-emerald-50 text-emerald-800 dark:border-emerald-700 dark:bg-emerald-900/20 dark:text-emerald-300";

                        radioClass += "border-emerald-500 bg-emerald-500";
                      } else if (isSelected) {
                        optionClass +=
                          "border-red-300 bg-red-50 text-red-800 dark:border-red-700 dark:bg-red-900/20 dark:text-red-300";

                        radioClass += "border-red-400 bg-red-400";
                      } else {
                        optionClass +=
                          "border-slate-200 bg-slate-50 text-slate-600 dark:border-slate-700 dark:bg-slate-800/50 dark:text-slate-400";

                        radioClass += "border-slate-300 dark:border-slate-600";
                      }
                    } else {
                      if (isSelected) {
                        optionClass +=
                          "border-blue-300 bg-blue-50 text-blue-800 dark:border-blue-600 dark:bg-blue-900/20 dark:text-blue-300";

                        radioClass += "border-blue-500 bg-blue-500";
                      } else {
                        optionClass +=
                          "border-slate-200 bg-white text-slate-700 hover:border-blue-200 hover:bg-blue-50/50 dark:border-slate-700 dark:bg-slate-800/50 dark:text-slate-300 dark:hover:border-blue-700";

                        radioClass += "border-slate-300 dark:border-slate-600";
                      }
                    }

                    return (
                      <button
                        key={key}
                        type="button"
                        onClick={() => selectAnswer(question.question_id, key)}
                        className={optionClass}
                      >
                        <div className={radioClass}>
                          {(isSelected || (result && isAnswer)) && (
                            <svg
                              width="6"
                              height="6"
                              viewBox="0 0 6 6"
                              fill="white"
                            >
                              <circle cx="3" cy="3" r="3" />
                            </svg>
                          )}
                        </div>

                        <span>
                          <span className="font-semibold">{key}.</span>{" "}
                          <MathText text={value} />
                        </span>
                      </button>
                    );
                  })}
                </div>

                {/* Answer summary after submit */}
                {result && correctAnswers.length > 0 && (
                  <div className="mx-5 mb-4 ml-[4.25rem] rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-2.5 text-sm font-medium text-emerald-700 dark:border-emerald-700 dark:bg-emerald-900/20 dark:text-emerald-400">
                    ✓ Đáp án đúng: {correctAnswers.join(", ")}
                  </div>
                )}

                {/* Explanation */}
                {result && explanation && (
                  <div className="mx-5 mb-4 ml-[4.25rem] rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 dark:border-slate-700 dark:bg-slate-800/50">
                    <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
                      Explanation
                    </p>

                    <div className="text-sm leading-relaxed text-slate-700 dark:text-slate-300">
                      <MathText text={explanation} />
                    </div>
                  </div>
                )}

                {/* Tags */}
                <div className="flex flex-wrap gap-2 px-5 pb-4 pl-[4.25rem]">
                  <Badge variant="outline" className="gap-1 text-xs">
                    {question.chapter_label ||
                      question.chapter_id ||
                      "Chưa rõ chương"}
                  </Badge>

                  <Badge variant="outline" className="gap-1 text-xs">
                    {question.topic}
                  </Badge>
                </div>
              </CardContent>
            </Card>
          );
        })}
      </div>
    </div>
  );
}
