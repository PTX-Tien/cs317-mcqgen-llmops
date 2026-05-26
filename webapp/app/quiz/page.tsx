"use client";
import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { MCQ } from "@/types";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { Badge } from "@/components/ui/badge";
import { toast } from "sonner";
import { User, CreditCard, Upload, Info, Rocket, IdCard } from "lucide-react";

type QuizPhase = "setup" | "taking" | "results";
interface QuizAnswer {
  [questionIndex: number]: string;
}
interface TopicStat {
  correct: number;
  total: number;
}

export default function QuizPage() {
  const router = useRouter();
  const [phase, setPhase] = useState<QuizPhase>("setup");
  const [mcqs, setMcqs] = useState<MCQ[]>([]);
  const [studentName, setStudentName] = useState("");
  const [studentId, setStudentId] = useState("");
  const [answers, setAnswers] = useState<QuizAnswer>({});
  const [currentQ, setCurrentQ] = useState(0);
  const [timeLeft, setTimeLeft] = useState(0);
  const [startTime, setStartTime] = useState(0);
  const [isDragging, setIsDragging] = useState(false);

  useEffect(() => {
    if (phase !== "taking" || timeLeft <= 0) return;
    const t = setInterval(() => {
      setTimeLeft((prev) => {
        if (prev <= 1) {
          clearInterval(t);
          handleSubmit();
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
    return () => clearInterval(t);
  }, [phase, timeLeft]);

  const parseFile = (file: File) => {
    const reader = new FileReader();
    reader.onload = (ev) => {
      try {
        const data = JSON.parse(ev.target?.result as string);
        setMcqs(Array.isArray(data) ? data : []);
        toast.success(
          `Loaded ${Array.isArray(data) ? data.length : 0} câu hỏi`,
        );
      } catch {
        toast.error("File JSON không hợp lệ");
      }
    };
    reader.readAsText(file);
  };

  const handleUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) parseFile(file);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    const file = e.dataTransfer.files?.[0];
    if (file) parseFile(file);
  };

  const startQuiz = () => {
    if (!studentName.trim()) {
      toast.error("Nhập họ tên trước");
      return;
    }
    if (mcqs.length === 0) {
      toast.error("Upload đề thi trước");
      return;
    }
    setTimeLeft(mcqs.length * 90);
    setStartTime(Date.now());
    setCurrentQ(0);
    setAnswers({});
    setPhase("taking");
  };

  const selectAnswer = (key: string) =>
    setAnswers((prev) => ({ ...prev, [currentQ]: key }));

  const handleSubmit = () => {
    const unanswered = mcqs.map((_, i) => i).filter((i) => !answers[i]);
    if (unanswered.length > 0 && timeLeft > 0) {
      toast.warning(
        `Còn ${unanswered.length} câu chưa trả lời. Xác nhận nộp?`,
        {
          action: { label: "Nộp bài", onClick: () => setPhase("results") },
        },
      );
      return;
    }
    setPhase("results");
  };

  const calcResults = () => {
    let correct = 0;
    const topicStats: Record<string, TopicStat> = {};
    const details = mcqs.map((mcq, i) => {
      const selected = answers[i] || "";
      const isCorrect = (mcq?.correct_answers || []).includes(selected);
      if (isCorrect) correct++;
      const t = mcq.topic;
      if (!topicStats[t]) topicStats[t] = { correct: 0, total: 0 };
      topicStats[t].total++;
      if (isCorrect) topicStats[t].correct++;
      return { mcq, selected, isCorrect };
    });
    const elapsed = Math.round((Date.now() - startTime) / 1000);
    const score = (correct / mcqs.length) * 10;
    return { correct, total: mcqs.length, score, elapsed, topicStats, details };
  };

  const formatTime = (s: number) =>
    `${Math.floor(s / 60)
      .toString()
      .padStart(2, "0")}:${(s % 60).toString().padStart(2, "0")}`;

  const getGrade = (score: number) => {
    if (score >= 9) return { label: "Xuất sắc 🏆", color: "text-yellow-600" };
    if (score >= 7) return { label: "Tốt 👍", color: "text-green-600" };
    if (score >= 5) return { label: "Đạt ✅", color: "text-blue-600" };
    return { label: "Cần ôn lại 📚", color: "text-red-600" };
  };

  // ── SETUP PHASE ─────────────────────────────────────────────
  if (phase === "setup")
    return (
      <div
        className="min-h-screen flex items-center justify-center p-4 relative overflow-hidden"
        style={{
          background:
            "radial-gradient(ellipse 80% 60% at 50% 40%, #1a1060 0%, #0d0730 40%, #06041a 100%)",
        }}
      >
        {/* Deep background glow blobs */}
        <div className="pointer-events-none absolute inset-0">
          {/* Left cyan-blue glow */}
          <div
            style={{
              position: "absolute",
              top: "15%",
              left: "-5%",
              width: 420,
              height: 420,
              borderRadius: "50%",
              background:
                "radial-gradient(circle, rgba(30,120,255,0.45) 0%, transparent 70%)",
              filter: "blur(40px)",
            }}
          />
          {/* Right purple glow */}
          <div
            style={{
              position: "absolute",
              bottom: "10%",
              right: "-5%",
              width: 460,
              height: 460,
              borderRadius: "50%",
              background:
                "radial-gradient(circle, rgba(140,60,255,0.40) 0%, transparent 70%)",
              filter: "blur(40px)",
            }}
          />
          {/* Center subtle glow behind card */}
          <div
            style={{
              position: "absolute",
              top: "30%",
              left: "25%",
              width: 600,
              height: 400,
              borderRadius: "50%",
              background:
                "radial-gradient(circle, rgba(80,50,200,0.25) 0%, transparent 70%)",
              filter: "blur(60px)",
            }}
          />
          {/* Dot grid */}
          <svg
            className="absolute inset-0 w-full h-full opacity-[0.07]"
            xmlns="http://www.w3.org/2000/svg"
          >
            <defs>
              <pattern
                id="dots"
                x="0"
                y="0"
                width="28"
                height="28"
                patternUnits="userSpaceOnUse"
              >
                <circle cx="1.5" cy="1.5" r="1.5" fill="white" />
              </pattern>
            </defs>
            <rect width="100%" height="100%" fill="url(#dots)" />
          </svg>
        </div>

        {/* Card — gradient from lavender-white top to pure white bottom */}
        <div
          className="relative z-10 w-full max-w-[560px] rounded-[28px] p-8 shadow-[0_40px_100px_rgba(0,0,0,0.6),inset_0_1px_0_rgba(255,255,255,0.8)]"
          style={{
            background:
              "linear-gradient(160deg, #eef0ff 0%, #f5f3ff 30%, #ffffff 65%)",
            border: "1px solid rgba(180,170,255,0.3)",
          }}
        >
          {/* Subtle inner top shimmer */}
          <div
            className="absolute top-0 left-0 right-0 h-px rounded-t-[28px]"
            style={{
              background:
                "linear-gradient(90deg, transparent, rgba(160,140,255,0.6), transparent)",
            }}
          />

          {/* Header */}
          <div className="text-center mb-4">
            {/* Icon with gradient glow */}
            <div className="inline-flex relative mb-2">
              <div
                className="w-16 h-16 rounded-2xl flex items-center justify-center text-3xl shadow-lg"
                style={{
                  background:
                    "linear-gradient(135deg, #ffffff 0%, #f0eeff 100%)",
                  boxShadow:
                    "0 8px 32px rgba(100,80,255,0.25), 0 2px 8px rgba(0,0,0,0.1)",
                  border: "1px solid rgba(180,160,255,0.4)",
                }}
              >
                🎯
              </div>
            </div>
            <h1 className="text-[1.6rem] font-extrabold text-slate-800 tracking-tight">
              Quiz Mode —{" "}
              <span
                style={{
                  background: "linear-gradient(90deg, #5b6ef5, #9b59f5)",
                  WebkitBackgroundClip: "text",
                  WebkitTextFillColor: "transparent",
                }}
              >
                Sinh viên
              </span>
            </h1>
            <p className="text-sm text-slate-500 mt-1.5">
              Làm bài trắc nghiệm và nhận kết quả ngay
            </p>
          </div>

          {/* Name + MSSV */}
          <div className="grid grid-cols-2 gap-3 mb-2">
            {[
              {
                label: "Họ tên",
                placeholder: "Nguyễn Văn A",
                icon: <User size={18} strokeWidth={2.5} />,
                val: studentName,
                set: setStudentName,
              },
              {
                label: "MSSV",
                placeholder: "22521234",
                icon: <IdCard size={20} strokeWidth={2.5} />,
                val: studentId,
                set: setStudentId,
              },
            ].map(({ label, placeholder, icon, val, set }) => (
              <div key={label}>
                <label className="text-sm font-bold text-slate-800 mb-1 block">
                  {label}
                </label>
                <div className="relative">
                  <span className="absolute left-3 top-1/2 -translate-y-1/2 text-indigo-400">
                    {icon}
                  </span>
                  <input
                    type="text"
                    placeholder={placeholder}
                    value={val}
                    onChange={(e) => set(e.target.value)}
                    suppressHydrationWarning
                    className="w-full h-11 pl-10 pr-3 rounded-xl text-sm font-medium text-slate-900 placeholder:text-slate-400 transition focus:outline-none"
                    style={{
                      background: "rgba(255,255,255,0.85)",
                      border: "1.5px solid rgba(180,160,255,0.35)",
                      boxShadow: "0 2px 8px rgba(100,80,200,0.07)",
                    }}
                    onFocus={(e) => {
                      e.target.style.borderColor = "rgba(100,90,255,0.6)";
                      e.target.style.boxShadow =
                        "0 0 0 3px rgba(100,90,255,0.12)";
                    }}
                    onBlur={(e) => {
                      e.target.style.borderColor = "rgba(180,160,255,0.35)";
                      e.target.style.boxShadow =
                        "0 2px 8px rgba(100,80,200,0.07)";
                    }}
                  />
                </div>
              </div>
            ))}
          </div>

          {/* Upload zone */}
          <div className="mb-3">
            <label className="text-sm font-bold text-slate-800 mb-1 block">
              Upload đề thi JSON
            </label>
            <input
              type="file"
              accept=".json"
              onChange={handleUpload}
              className="hidden"
              id="file-upload"
              suppressHydrationWarning
            />
            <label
              htmlFor="file-upload"
              onDragOver={(e) => {
                e.preventDefault();
                setIsDragging(true);
              }}
              onDragLeave={() => setIsDragging(false)}
              onDrop={handleDrop}
              className="flex flex-col items-center justify-center gap-2.5 w-full rounded-2xl cursor-pointer transition-all py-4"
              style={{
                background: isDragging
                  ? "rgba(90,100,255,0.08)"
                  : mcqs.length > 0
                    ? "rgba(50,200,100,0.06)"
                    : "rgba(255,255,255,0.6)",
                border: `2px dashed ${isDragging ? "rgba(90,100,255,0.7)" : mcqs.length > 0 ? "rgba(50,180,100,0.5)" : "rgba(170,160,230,0.5)"}`,
                boxShadow: isDragging
                  ? "0 0 0 4px rgba(90,100,255,0.08)"
                  : "none",
              }}
            >
              {mcqs.length > 0 ? (
                <>
                  <div className="w-12 h-12 rounded-2xl bg-green-100 flex items-center justify-center text-2xl shadow-sm">
                    ✅
                  </div>
                  <div className="text-center">
                    <p className="text-sm font-bold text-green-700">
                      {mcqs.length} câu hỏi đã load
                    </p>
                    <p className="text-xs text-green-600/70 mt-0.5">
                      Click để thay file khác
                    </p>
                  </div>
                </>
              ) : (
                <>
                  {/* Upload icon with gradient background + glow */}
                  <div
                    className="w-14 h-14 rounded-2xl flex items-center justify-center shadow-lg"
                    style={{
                      background:
                        "linear-gradient(135deg, #5b8ef5 0%, #7b5bf5 100%)",
                      boxShadow: "0 8px 24px rgba(100,100,255,0.40)",
                    }}
                  >
                    <Upload size={24} className="text-white" />
                  </div>
                  <div className="text-center">
                    <p className="text-sm font-bold text-slate-700">
                      Kéo & thả file JSON vào đây
                    </p>
                    <p className="text-xs text-slate-400 mt-0.5">
                      Hoặc click để chọn file
                    </p>
                  </div>
                  <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-slate-100/80 text-[11px] text-slate-500">
                    <Info size={11} />
                    Hỗ trợ file .json, dung lượng tối đa 10MB
                  </div>
                </>
              )}
            </label>
          </div>

          {/* Info strip when loaded */}
          {mcqs.length > 0 && (
            <div className="grid grid-cols-3 gap-2 mb-5">
              {[
                { label: "Số câu", value: String(mcqs.length) },
                {
                  label: "Thời gian",
                  value: `${Math.ceil(mcqs.length * 1.5)} phút`,
                },
                {
                  label: "Topics",
                  value: `${Array.from(new Set(mcqs.map((m) => m.topic))).length} topic`,
                },
              ].map(({ label, value }) => (
                <div
                  key={label}
                  className="rounded-xl py-2.5 px-3 text-center"
                  style={{
                    background: "rgba(255,255,255,0.7)",
                    border: "1px solid rgba(170,160,230,0.3)",
                  }}
                >
                  <p className="text-base font-bold text-slate-800">{value}</p>
                  <p className="text-[10px] text-slate-400 mt-0.5">{label}</p>
                </div>
              ))}
            </div>
          )}

          {/* Start button — gradient blue-purple, full glow */}
          <button
            onClick={startQuiz}
            disabled={mcqs.length === 0}
            className="w-full h-12 rounded-2xl text-white text-sm font-bold flex items-center justify-center gap-2 transition-all disabled:opacity-50 disabled:cursor-not-allowed mb-5"
            style={{
              background:
                mcqs.length === 0
                  ? "linear-gradient(90deg, #8888aa, #9988bb)"
                  : "linear-gradient(90deg, #4a6cf7 0%, #7a3cf7 50%, #9b3af5 100%)",
              boxShadow:
                mcqs.length === 0
                  ? "none"
                  : "0 8px 32px rgba(100,60,240,0.45), 0 2px 8px rgba(100,60,240,0.3)",
            }}
            onMouseEnter={(e) => {
              if (mcqs.length > 0) {
                (e.currentTarget as HTMLButtonElement).style.transform =
                  "translateY(-1px)";
                (e.currentTarget as HTMLButtonElement).style.boxShadow =
                  "0 12px 40px rgba(100,60,240,0.55), 0 2px 8px rgba(100,60,240,0.35)";
              }
            }}
            onMouseLeave={(e) => {
              (e.currentTarget as HTMLButtonElement).style.transform =
                "translateY(0)";
              if (mcqs.length > 0)
                (e.currentTarget as HTMLButtonElement).style.boxShadow =
                  "0 8px 32px rgba(100,60,240,0.45), 0 2px 8px rgba(100,60,240,0.3)";
            }}
          >
            <Rocket size={16} />
            Bắt đầu làm bài
          </button>

          {/* Footer hint */}
          <p className="text-center text-xs text-slate-500 flex items-center justify-center gap-1">
            💡 Không có đề thi? Nhờ giảng viên{" "}
            <span
              className="font-semibold"
              style={{
                background: "linear-gradient(90deg, #4a6cf7, #9b3af5)",
                WebkitBackgroundClip: "text",
                WebkitTextFillColor: "transparent",
              }}
            >
              export JSON
            </span>{" "}
            từ hệ thống
          </p>
        </div>
      </div>
    );

  // ── TAKING PHASE ─────────────────────────────────────────────
  if (phase === "taking") {
    const mcq = mcqs[currentQ];
    const progress = ((currentQ + 1) / mcqs.length) * 100;
    const timePercent = (timeLeft / (mcqs.length * 90)) * 100;
    const timeWarning = timeLeft < 120;

    return (
      <div className="min-h-screen bg-slate-50">
        <div className="bg-white border-b px-4 py-3 flex items-center justify-between sticky top-0 z-10 shadow-sm">
          <div className="flex items-center gap-3">
            <span className="font-semibold text-sm">{studentName}</span>
            <Badge variant="outline" className="text-xs">
              Câu {currentQ + 1}/{mcqs.length}
            </Badge>
          </div>
          <div
            className={`flex items-center gap-2 font-mono font-bold ${timeWarning ? "text-red-500 animate-pulse" : "text-slate-700"}`}
          >
            ⏱ {formatTime(timeLeft)}
          </div>
          <Button size="sm" onClick={handleSubmit} variant="outline">
            Nộp bài
          </Button>
        </div>

        <div className="bg-white px-4 py-2 border-b">
          <Progress value={progress} className="h-1.5" />
          <div
            className={`h-1 mt-1 rounded-full transition-all ${timeWarning ? "bg-red-400" : "bg-blue-200"}`}
            style={{ width: `${timePercent}%` }}
          />
        </div>

        <div className="max-w-2xl mx-auto p-4 space-y-4">
          <Card>
            <CardContent className="p-5">
              <div className="flex items-start gap-3">
                <span className="bg-slate-800 text-white text-sm font-bold w-8 h-8 rounded-full flex items-center justify-center shrink-0">
                  {currentQ + 1}
                </span>
                <p className="text-base font-medium leading-relaxed">
                  {mcq.question_text}
                </p>
              </div>
            </CardContent>
          </Card>

          <div className="space-y-2">
            {Object.entries(mcq?.options || {}).map(([key, value]) => (
              <button
                key={key}
                onClick={() => selectAnswer(key)}
                suppressHydrationWarning
                className={`w-full text-left px-4 py-3 rounded-xl border-2 transition-all text-sm font-medium ${
                  answers[currentQ] === key
                    ? "border-slate-800 bg-slate-800 text-white shadow-md"
                    : "border-slate-200 bg-white hover:border-slate-400 hover:bg-slate-50"
                }`}
              >
                <span
                  className={`inline-flex items-center justify-center w-6 h-6 rounded-full mr-3 text-xs font-bold ${
                    answers[currentQ] === key
                      ? "bg-white text-slate-800"
                      : "bg-slate-100 text-slate-600"
                  }`}
                >
                  {key}
                </span>
                {String(value)}
              </button>
            ))}
          </div>

          <div className="flex justify-between pt-2">
            <Button
              variant="outline"
              onClick={() => setCurrentQ(Math.max(0, currentQ - 1))}
              disabled={currentQ === 0}
            >
              ← Trước
            </Button>
            <div className="flex gap-1 overflow-x-auto max-w-xs">
              {mcqs.map((_, i) => (
                <button
                  key={i}
                  onClick={() => setCurrentQ(i)}
                  suppressHydrationWarning
                  className={`w-8 h-8 rounded text-xs font-medium shrink-0 transition-all ${
                    i === currentQ
                      ? "bg-slate-800 text-white"
                      : answers[i]
                        ? "bg-green-100 text-green-700 border border-green-300"
                        : "bg-slate-100 text-slate-500 hover:bg-slate-200"
                  }`}
                >
                  {i + 1}
                </button>
              ))}
            </div>
            {currentQ < mcqs.length - 1 ? (
              <Button onClick={() => setCurrentQ(currentQ + 1)}>Tiếp →</Button>
            ) : (
              <Button
                onClick={handleSubmit}
                className="bg-green-600 hover:bg-green-700"
              >
                Nộp bài ✓
              </Button>
            )}
          </div>
        </div>
      </div>
    );
  }

  // ── RESULTS PHASE ─────────────────────────────────────────────
  const { correct, total, score, elapsed, topicStats, details } = calcResults();
  const grade = getGrade(score);

  return (
    <div className="min-h-screen bg-slate-50 p-4">
      <div className="max-w-2xl mx-auto space-y-4">
        <Card className="text-center overflow-hidden">
          <div className="bg-gradient-to-r from-slate-800 to-slate-600 p-8 text-white">
            <h2 className="text-lg font-medium opacity-80 mb-1">
              {studentName} — {studentId}
            </h2>
            <div className="text-7xl font-bold">{score.toFixed(1)}</div>
            <div className="text-xl opacity-80">/ 10.0</div>
            <div
              className={`text-xl font-semibold mt-2 ${grade.color.replace("-600", "-300")}`}
            >
              {grade.label}
            </div>
          </div>
          <CardContent className="p-4">
            <div className="grid grid-cols-3 gap-4 text-center">
              <div>
                <div className="text-2xl font-bold text-green-600">
                  {correct}
                </div>
                <div className="text-xs text-slate-500">Câu đúng</div>
              </div>
              <div>
                <div className="text-2xl font-bold text-red-500">
                  {total - correct}
                </div>
                <div className="text-xs text-slate-500">Câu sai</div>
              </div>
              <div>
                <div className="text-2xl font-bold text-blue-600">
                  {Math.floor(elapsed / 60)}:
                  {(elapsed % 60).toString().padStart(2, "0")}
                </div>
                <div className="text-xs text-slate-500">Thời gian</div>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">📈 Phân tích theo topic</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {Object.entries(topicStats).map(([topic, stat]) => {
              const pct = (stat.correct / stat.total) * 100;
              return (
                <div key={topic}>
                  <div className="flex justify-between text-sm mb-1">
                    <span className="font-medium truncate mr-2">{topic}</span>
                    <span
                      className={pct >= 70 ? "text-green-600" : "text-red-500"}
                    >
                      {stat.correct}/{stat.total} ({pct.toFixed(0)}%)
                    </span>
                  </div>
                  <div className="h-2 bg-slate-100 rounded-full overflow-hidden">
                    <div
                      className={`h-full rounded-full transition-all ${pct >= 70 ? "bg-green-500" : "bg-red-400"}`}
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                </div>
              );
            })}
          </CardContent>
        </Card>

        <div className="space-y-2">
          <h3 className="font-semibold text-slate-700">🔍 Chi tiết từng câu</h3>
          {details.map(({ mcq, selected, isCorrect }, i) => (
            <Card
              key={i}
              className={`border-l-4 ${isCorrect ? "border-l-green-500" : "border-l-red-500"}`}
            >
              <CardContent className="p-4">
                <p className="text-sm font-medium mb-2">
                  {i + 1}. {mcq.question_text}
                </p>
                <div className="space-y-1">
                  {Object.entries(mcq.options).map(([k, v]) => {
                    const isSelected = k === selected;
                    const isCorrectAns = mcq.correct_answers.includes(k);
                    return (
                      <div
                        key={k}
                        className={`px-3 py-1.5 rounded text-xs ${
                          isCorrectAns
                            ? "bg-green-50 text-green-700 font-medium"
                            : isSelected && !isCorrectAns
                              ? "bg-red-50 text-red-600 line-through"
                              : "text-slate-500"
                        }`}
                      >
                        {isCorrectAns ? "✓" : isSelected ? "✗" : "○"} {k}.{" "}
                        {String(v)}
                      </div>
                    );
                  })}
                </div>
              </CardContent>
            </Card>
          ))}
        </div>

        <Button
          onClick={() => setPhase("setup")}
          className="w-full"
          variant="outline"
        >
          🔄 Làm lại
        </Button>
      </div>
    </div>
  );
}
