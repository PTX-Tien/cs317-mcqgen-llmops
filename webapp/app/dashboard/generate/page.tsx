"use client";
import { useState, useRef, useEffect } from "react";
import { useRouter } from "next/navigation";
import { api, WS_URL } from "@/lib/api";
import {
  COURSE_CHAPTERS,
  DIFFICULTY_LABELS,
  TOPIC_SUGGESTIONS,
  chapterLabel,
} from "@/lib/course";
import { formatExamDisplayName } from "@/lib/exam-name";
import {
  TopicConfig,
  MCQ,
  GenerationFailure,
  GenerationState,
  GenerationResourceInfo,
} from "@/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { MathText } from "@/components/math-text";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { toast } from "sonner";
import {
  BookOpen,
  FileText,
  GripVertical,
  Layers,
  LayoutList,
  Minus,
  PlayCircle,
  Plus,
  RotateCcw,
  Sparkles,
  Trash2,
  X,
} from "lucide-react";

// ── Constants ────────────────────────────────────────────────────
const PIPELINE_STEPS = [
  { label: "Tài liệu", icon: "🔍" },
  { label: "Câu hỏi", icon: "✍️" },
  { label: "Phương án", icon: "🎯" },
  { label: "Ghép đề", icon: "📝" },
  { label: "Đánh giá", icon: "✅" },
];
const PIPELINE_STEP_DESCRIPTIONS: Record<string, string> = {
  "Tài liệu": "Đang thu thập nội dung từ nguồn",
  "Câu hỏi": "Đang tạo câu hỏi theo cấu hình",
  "Phương án": "Đang tạo các phương án trả lời",
  "Ghép đề": "Đang sắp xếp và điều phối câu hỏi",
  "Đánh giá": "Đang kiểm tra chất lượng đề thi",
};
const DEFAULT_RETRIEVAL_MODE = "auto";
const ACTIVE_GENERATION_KEY = "mcqgen.active_generation";

interface ActiveGeneration extends GenerationResourceInfo {
  taskId: string;
  examName: string;
  totalQ: number;
  startedAt: number;
  queuePosition?: number;
  jobsAhead?: number;
  estimatedWait?: number;
  queueWait?: number;
  estimatedRuntime?: number;
  questionConcurrency?: number;
  llmConcurrency?: number;
  vllmMaxNumSeqs?: number;
}

function readNumber(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value)
    ? value
    : undefined;
}

function readString(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value : undefined;
}

function readBool(value: unknown): boolean | undefined {
  return typeof value === "boolean" ? value : undefined;
}

function resourceInfoFromApi(data: Record<string, unknown>): GenerationResourceInfo {
  return {
    resourceStatus: readString(data.resource_status),
    resourceQueueReason: readString(data.resource_queue_reason),
    resourceMessage: readString(data.resource_message),
    resourceCapacityJobs: readNumber(data.resource_capacity_jobs),
    runningGenerationJobsAtStart: readNumber(data.running_generation_jobs_at_start),
    queuedGenerationJobsAtStart: readNumber(data.queued_generation_jobs_at_start),
    willQueueDueToResources: readBool(data.will_queue_due_to_resources),
    allocatedQuestionSlotsAtStart: readNumber(data.allocated_question_slots_at_start),
    expectedQuestionSlotsWhenRunning: readNumber(data.expected_question_slots_when_running),
    resourceSlotsTotal: readNumber(data.resource_slots_total),
    dynamicConcurrency: readBool(data.dynamic_concurrency),
    runtimeConcurrentTraces: readNumber(data.runtime_concurrent_traces),
    runtimeConcurrentUsers: readNumber(data.runtime_concurrent_users),
    effectiveQuestionConcurrency: readNumber(data.effective_question_concurrency),
  };
}

function getApiErrorDetail(error: unknown): string | undefined {
  if (typeof error !== "object" || error === null || !("response" in error)) {
    return undefined;
  }
  const response = (error as { response?: { data?: { detail?: string } } })
    .response;
  return response?.data?.detail;
}

function nowMs(): number {
  return Date.now();
}

function elapsedSeconds(startMs: number): number {
  return (nowMs() - startMs) / 1000;
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
    .toLowerCase();
  return normalized || "de_thi";
}

function readActiveGeneration(): ActiveGeneration | null {
  try {
    const raw = localStorage.getItem(ACTIVE_GENERATION_KEY);
    return raw ? (JSON.parse(raw) as ActiveGeneration) : null;
  } catch {
    return null;
  }
}

function saveActiveGeneration(active: ActiveGeneration) {
  localStorage.setItem(ACTIVE_GENERATION_KEY, JSON.stringify(active));
}

function clearActiveGeneration(taskId?: string) {
  const active = readActiveGeneration();
  if (!taskId || active?.taskId === taskId) {
    localStorage.removeItem(ACTIVE_GENERATION_KEY);
  }
}

function successToastMessage(accepted: number, failed?: number) {
  return failed && failed > 0
    ? `${accepted} câu hỏi đã sinh thành công, ${failed} câu bị loại.`
    : `${accepted} câu hỏi đã sinh thành công!`;
}

function formatProgressStep(step?: string): string {
  const value = (step || "").trim();
  if (!value) return "Đang xử lý";
  if (value.startsWith("retrieving_context"))
    return "Đang tìm tài liệu liên quan";
  if (value.startsWith("generating")) return "Đang sinh câu hỏi";
  if (value === "saving") return "Đang lưu đề thi";
  if (value === "done") return "Hoàn thành";
  return value;
}

interface TopicDraft {
  id: string;
  topic: string;
  difficulty: string;
  n: string;
}

interface ChapterDraft {
  id: string;
  chapter_id: string;
  topics: TopicDraft[];
}

function createEmptyTopicDraft(topicId: string): TopicDraft {
  return { id: topicId, topic: "", difficulty: "G2", n: "" };
}

function createEmptyChapterDraft(
  chapterId: string,
  topicId: string,
): ChapterDraft {
  return {
    id: chapterId,
    chapter_id: "",
    topics: [createEmptyTopicDraft(topicId)],
  };
}

function parseQuestionCount(value: string): number {
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) ? parsed : 0;
}

function TopicDraftRow({
  chapterId,
  topic,
  index,
  selectedTopics,
  onChange,
  onRemove,
  canRemove,
}: {
  chapterId: string;
  topic: TopicDraft;
  index: number;
  selectedTopics: string[];
  onChange: (topic: TopicDraft) => void;
  onRemove: () => void;
  canRemove: boolean;
}) {
  const suggestions = chapterId ? TOPIC_SUGGESTIONS[chapterId] || [] : [];
  const unavailableTopics = new Set(
    selectedTopics
      .filter((selectedTopic) => selectedTopic && selectedTopic !== topic.topic)
      .map((selectedTopic) => selectedTopic.toLowerCase()),
  );
  const availableSuggestions = suggestions.filter(
    (suggestion) =>
      !unavailableTopics.has(suggestion.toLowerCase()) ||
      suggestion === topic.topic,
  );

  const currentN = parseQuestionCount(topic.n);

  return (
    <div className="flex items-center gap-3 border border-slate-200 rounded-lg bg-white px-3 py-3">
      {/* Drag handle */}
      <GripVertical size={15} className="text-slate-300 shrink-0 cursor-grab" />

      {/* Topic name */}
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-slate-700 truncate">
          {topic.topic || (
            <span className="text-slate-400 italic">
              Topic {index + 1}: Chưa chọn
            </span>
          )}
        </p>
        <Select
          value={topic.topic}
          onValueChange={(value) => onChange({ ...topic, topic: value ?? "" })}
          disabled={!chapterId}
        >
          <SelectTrigger className="mt-1 h-8 w-full bg-slate-50 border-slate-200 text-xs">
            <SelectValue
              placeholder={chapterId ? "Chọn topic" : "Chọn chương trước"}
            />
          </SelectTrigger>
          <SelectContent align="start" className="z-[100] max-h-72">
            {availableSuggestions.map((suggestion) => (
              <SelectItem
                key={suggestion}
                value={suggestion}
                className="py-2 text-sm"
              >
                {suggestion}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {/* Difficulty */}
      <div className="w-28 shrink-0">
        <p className="text-xs text-slate-400 mb-1">Độ khó</p>
        <Select
          value={topic.difficulty}
          onValueChange={(value) =>
            onChange({ ...topic, difficulty: value ?? "G2" })
          }
        >
          <SelectTrigger className="h-8 w-full bg-slate-50 border-slate-200 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent align="start" className="z-[100] max-h-72">
            {Object.entries(DIFFICULTY_LABELS).map(([value, label]) => (
              <SelectItem key={value} value={value} className="py-2 text-sm">
                {label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {/* Question count +/- */}
      <div className="shrink-0">
        <p className="text-xs text-slate-400 mb-1">Số câu</p>
        <div className="flex items-center gap-1">
          <Button
            variant="outline"
            size="icon"
            className="h-8 w-8 rounded-md border-slate-200"
            onClick={() =>
              onChange({ ...topic, n: String(Math.max(1, currentN - 1)) })
            }
            disabled={currentN <= 1}
          >
            <Minus size={13} />
          </Button>
          <span className="w-8 text-center text-sm font-semibold text-slate-700">
            {topic.n || "0"}
          </span>
          <Button
            variant="outline"
            size="icon"
            className="h-8 w-8 rounded-md border-slate-200"
            onClick={() => onChange({ ...topic, n: String(currentN + 1) })}
          >
            <Plus size={13} />
          </Button>
        </div>
      </div>

      {/* Delete */}
      <Button
        variant="ghost"
        size="icon"
        onClick={onRemove}
        disabled={!canRemove}
        aria-label={`Xóa topic ${index + 1}`}
        className="h-8 w-8 text-slate-300 hover:bg-red-50 hover:text-red-500 shrink-0"
      >
        <Trash2 size={14} />
      </Button>
    </div>
  );
}

function ChapterBlock({
  chapter,
  index,
  selectedChapterIds,
  canRemove,
  canAddTopic,
  onChange,
  onRemove,
  onAddTopic,
}: {
  chapter: ChapterDraft;
  index: number;
  selectedChapterIds: string[];
  canRemove: boolean;
  canAddTopic: boolean;
  onChange: (chapter: ChapterDraft) => void;
  onRemove: () => void;
  onAddTopic: () => void;
}) {
  const unavailableChapterIds = new Set(
    selectedChapterIds.filter(
      (chapterId) => chapterId && chapterId !== chapter.chapter_id,
    ),
  );
  const chapterOptions = Object.entries(COURSE_CHAPTERS).filter(
    ([chapterId]) =>
      !unavailableChapterIds.has(chapterId) || chapterId === chapter.chapter_id,
  );
  const selectedTopics = chapter.topics
    .map((topic) => topic.topic)
    .filter(Boolean);
  const selectedTopicKeys = selectedTopics.map((topic) => topic.toLowerCase());
  const availableTopicCount = chapter.chapter_id
    ? (TOPIC_SUGGESTIONS[chapter.chapter_id] || []).filter(
        (topic) => !selectedTopicKeys.includes(topic.toLowerCase()),
      ).length
    : 0;

  const headerLabel = chapter.chapter_id
    ? chapterLabel(chapter.chapter_id)
    : `Chương ${index + 1}: Chưa chọn`;

  return (
    <div className="border border-slate-200 rounded-xl bg-white overflow-visible shadow-sm">
      {/* Chapter header */}
      <div className="flex items-center gap-3 px-4 py-3 border-b border-slate-100">
        <GripVertical
          size={15}
          className="text-slate-300 shrink-0 cursor-grab"
        />
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold text-slate-800 truncate">
            {headerLabel}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-48 shrink-0">
            <p className="text-xs font-semibold text-slate-800 mb-0.5">
              Chọn chương
            </p>
            <Select
              value={chapter.chapter_id}
              onValueChange={(value) =>
                onChange({
                  ...chapter,
                  chapter_id: value ?? "",
                  topics: chapter.topics.map((topic) => ({
                    ...topic,
                    topic: "",
                  })),
                })
              }
            >
              <SelectTrigger className="h-8 w-full bg-slate-50 border-slate-200 text-xs">
                <SelectValue placeholder="Chọn chương" />
              </SelectTrigger>
              <SelectContent align="start" className="z-[100] max-h-72">
                {chapterOptions.map(([value, label]) => (
                  <SelectItem
                    key={value}
                    value={value}
                    className="py-2 text-sm"
                  >
                    {label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <Button
            variant="ghost"
            size="icon"
            onClick={onRemove}
            disabled={!canRemove}
            aria-label={`Xóa chương ${index + 1}`}
            className="h-8 w-8 text-slate-300 hover:bg-red-50 hover:text-red-500 shrink-0 mt-4"
          >
            <Trash2 size={14} />
          </Button>
        </div>
      </div>

      {/* Topics */}
      <div className="p-4 space-y-2">
        {chapter.topics.map((topic, topicIndex) => (
          <TopicDraftRow
            key={topic.id}
            chapterId={chapter.chapter_id}
            topic={topic}
            index={topicIndex}
            selectedTopics={selectedTopics}
            canRemove={chapter.topics.length > 1}
            onChange={(updatedTopic) =>
              onChange({
                ...chapter,
                topics: chapter.topics.map((item) =>
                  item.id === topic.id ? updatedTopic : item,
                ),
              })
            }
            onRemove={() =>
              onChange({
                ...chapter,
                topics: chapter.topics.filter((item) => item.id !== topic.id),
              })
            }
          />
        ))}

        <Button
          variant="ghost"
          onClick={onAddTopic}
          disabled={!canAddTopic}
          className="w-full h-9 border border-dashed border-slate-200 text-slate-400 hover:text-slate-600 hover:bg-slate-50 text-sm mt-1"
        >
          <Plus size={14} className="mr-1" />
          {chapter.chapter_id && (!canAddTopic || availableTopicCount === 0)
            ? "Đã đủ topic"
            : "Thêm topic"}
        </Button>
      </div>
    </div>
  );
}

// ── Main page ────────────────────────────────────────────────────
export default function GeneratePage() {
  const router = useRouter();
  const [examName, setExamName] = useState("Đề số 1");
  const [examCode, setExamCode] = useState("");
  const [chapters, setChapters] = useState<ChapterDraft[]>([
    createEmptyChapterDraft("c1", "t1"),
  ]);
  const [genState, setGenState] = useState<GenerationState>({ status: "idle" });
  const [mcqs, setMcqs] = useState<MCQ[]>([]);
  const wsRef = useRef<WebSocket | null>(null);
  const taskIdRef = useRef<string | null>(null);
  const nextChapterIndexRef = useRef(2);
  const nextTopicIndexRef = useRef(2);

  const draftTopics = chapters.flatMap((chapter) =>
    chapter.topics.map((topic) => ({
      chapter,
      topic,
    })),
  );
  const validTopics = draftTopics
    .filter(
      ({ chapter, topic }) =>
        chapter.chapter_id &&
        topic.topic.trim() &&
        parseQuestionCount(topic.n) > 0,
    )
    .map(
      ({ chapter, topic }, index): TopicConfig => ({
        topic_id: `t${index + 1}`,
        chapter_id: chapter.chapter_id,
        topic: topic.topic.trim(),
        difficulty: topic.difficulty || "G2",
        n: parseQuestionCount(topic.n),
      }),
    );
  const totalQ = validTopics.reduce((sum, topic) => sum + topic.n, 0);
  const allTopicsCount = chapters.reduce(
    (sum, ch) => sum + ch.topics.length,
    0,
  );
  const displayExamName = formatExamDisplayName(examName);
  const systemExamName = examCode.trim()
    ? normalizeExamName(examCode)
    : normalizeExamName(examName);
  const selectedChapterIds = chapters
    .map((chapter) => chapter.chapter_id)
    .filter(Boolean);
  const chapterOptionCount = Object.keys(COURSE_CHAPTERS).length;
  const canAddChapter = chapters.length < chapterOptionCount;

  const canAddTopicForChapter = (chapter: ChapterDraft): boolean => {
    if (!chapter.chapter_id) return false;
    const suggestions = TOPIC_SUGGESTIONS[chapter.chapter_id] || [];
    if (suggestions.length === 0) return false;
    if (chapter.topics.length >= suggestions.length) return false;
    const selectedTopicKeys = new Set(
      chapter.topics
        .map((topic) => topic.topic.trim().toLowerCase())
        .filter(Boolean),
    );
    return suggestions.some(
      (suggestion) => !selectedTopicKeys.has(suggestion.toLowerCase()),
    );
  };

  const addChapter = () => {
    if (!canAddChapter) {
      toast.info("Bạn đã chọn hết các chương có sẵn");
      return;
    }
    const nextChapterId = `c${nextChapterIndexRef.current}`;
    const nextTopicId = `t${nextTopicIndexRef.current}`;
    nextChapterIndexRef.current += 1;
    nextTopicIndexRef.current += 1;
    setChapters([
      ...chapters,
      createEmptyChapterDraft(nextChapterId, nextTopicId),
    ]);
  };

  const addTopicToChapter = (chapterId: string) => {
    const chapter = chapters.find((item) => item.id === chapterId);
    if (!chapter) return;
    if (!chapter.chapter_id) {
      toast.error("Vui lòng chọn chương trước khi thêm topic");
      return;
    }
    if (!canAddTopicForChapter(chapter)) {
      toast.info("Bạn đã chọn hết topic trong chương này");
      return;
    }
    const nextTopicId = `t${nextTopicIndexRef.current}`;
    nextTopicIndexRef.current += 1;
    setChapters(
      chapters.map((chapter) =>
        chapter.id === chapterId
          ? {
              ...chapter,
              topics: [...chapter.topics, createEmptyTopicDraft(nextTopicId)],
            }
          : chapter,
      ),
    );
  };

  const updateChapter = (updatedChapter: ChapterDraft) => {
    setChapters(
      chapters.map((chapter) =>
        chapter.id === updatedChapter.id ? updatedChapter : chapter,
      ),
    );
  };

  const removeChapter = (chapterId: string) => {
    setChapters(chapters.filter((chapter) => chapter.id !== chapterId));
  };

  const clearAll = () => {
    setChapters([createEmptyChapterDraft("c1", "t1")]);
    nextChapterIndexRef.current = 2;
    nextTopicIndexRef.current = 2;
    setExamName("Đề số 1");
    setExamCode("");
    toast.info("Đã xóa toàn bộ cấu hình");
  };

  const validateDraft = (): TopicConfig[] | null => {
    if (!examName.trim()) {
      toast.error("Vui lòng nhập tên đề thi");
      return null;
    }
    if (chapters.length === 0) {
      toast.error("Vui lòng thêm ít nhất một chương");
      return null;
    }
    const flattened: TopicConfig[] = [];
    const seenChapters = new Set<string>();
    for (const [chapterIndex, chapter] of chapters.entries()) {
      if (!chapter.chapter_id) {
        toast.error(`Chương ${chapterIndex + 1} chưa được chọn`);
        return null;
      }
      if (seenChapters.has(chapter.chapter_id)) {
        toast.error(
          `${chapterLabel(chapter.chapter_id)} đã được chọn ở nhóm khác`,
        );
        return null;
      }
      seenChapters.add(chapter.chapter_id);
      const seenTopics = new Set<string>();
      for (const [topicIndex, topic] of chapter.topics.entries()) {
        const label = `Chương ${chapterIndex + 1}, topic ${topicIndex + 1}`;
        if (!topic.topic.trim()) {
          toast.error(`${label} chưa chọn topic cụ thể`);
          return null;
        }
        const duplicateKey = topic.topic.trim().toLowerCase();
        if (seenTopics.has(duplicateKey)) {
          toast.error(`${label} bị trùng topic trong cùng chương`);
          return null;
        }
        seenTopics.add(duplicateKey);
        const n = parseQuestionCount(topic.n);
        if (n < 1) {
          toast.error(`${label} chưa nhập số câu hợp lệ`);
          return null;
        }
        flattened.push({
          topic_id: `t${flattened.length + 1}`,
          chapter_id: chapter.chapter_id,
          topic: topic.topic.trim(),
          difficulty: topic.difficulty || "G2",
          n,
        });
      }
    }
    return flattened;
  };

  const completeGeneration = (
    taskId: string,
    data: {
      accepted?: number;
      failed?: number;
      failures?: GenerationFailure[];
      mcqs?: MCQ[];
    },
    start: number,
  ) => {
    const generated = data.mcqs || [];
    const failed = data.failed ?? data.failures?.length ?? 0;
    setMcqs(generated);
    setGenState({
      status: "success",
      mcqs: generated,
      elapsed: elapsedSeconds(start),
      taskId,
      failed,
      failures: data.failures || [],
    });
    clearActiveGeneration(taskId);
    toast.success(
      successToastMessage(data.accepted ?? generated.length, failed),
    );
  };

  function pollFallback(
    taskId: string,
    start: number,
    expectedTotalQ: number = totalQ,
  ) {
    const interval = setInterval(async () => {
      try {
        const { data } = await api.get(`/status/${taskId}`);
        if (data.state === "running") {
          const resourceInfo = resourceInfoFromApi(data);
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
            ...resourceInfo,
          });
        } else if (data.state === "success") {
          clearInterval(interval);
          const res = await api.get(`/results/${taskId}`);
          completeGeneration(taskId, res.data, start);
        } else if (data.state === "failed") {
          clearInterval(interval);
          clearActiveGeneration(taskId);
          setGenState({ status: "failed", error: "Pipeline thất bại" });
        }
      } catch {
        clearInterval(interval);
        clearActiveGeneration(taskId);
        setGenState({
          status: "failed",
          error: "Không lấy được trạng thái/kết quả từ API",
        });
      }
    }, 3000);
  }

  function startWebSocket(
    taskId: string,
    start: number = nowMs(),
    expectedTotalQ: number = totalQ,
  ) {
    const ws = new WebSocket(`${WS_URL}/ws/${taskId}`);
    wsRef.current = ws;
    let finished = false;
    let fallbackStarted = false;

    const startPollingFallback = () => {
      if (finished || fallbackStarted) return;
      fallbackStarted = true;
      pollFallback(taskId, start, expectedTotalQ);
    };

    ws.onmessage = async (e) => {
      const msg = JSON.parse(e.data);
      if (msg.state === "running") {
        const resourceInfo = resourceInfoFromApi(msg);
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
          ...resourceInfo,
        });
      } else if (msg.state === "success") {
        try {
          const { data } = await api.get(`/results/${taskId}`);
          completeGeneration(taskId, data, start);
        } catch {
          setGenState({ status: "failed", error: "Lỗi lấy kết quả" });
        }
        finished = true;
        ws.close();
      } else if (msg.state === "failed") {
        clearActiveGeneration(taskId);
        setGenState({
          status: "failed",
          error: msg.error || "Pipeline thất bại",
        });
        toast.error("Pipeline thất bại");
        finished = true;
        ws.close();
      }
    };
    ws.onerror = startPollingFallback;
    ws.onclose = startPollingFallback;
  }

  async function resumeActiveGeneration() {
    const active = readActiveGeneration();
    if (!active) return;

    taskIdRef.current = active.taskId;
    const start = active.startedAt || nowMs();
    try {
      const { data } = await api.get(`/status/${active.taskId}`);
      if (data.state === "pending") {
        setExamName(formatExamDisplayName(active.examName));
        setGenState({
          status: "queued",
          position: active.queuePosition || 1,
          estimatedWait: active.estimatedWait || 0,
          queueWait: active.queueWait || 0,
          estimatedRuntime: active.estimatedRuntime || 0,
          jobsAhead: active.jobsAhead || 0,
          taskId: active.taskId,
          totalQ: active.totalQ,
          questionConcurrency: active.questionConcurrency,
          llmConcurrency: active.llmConcurrency,
          vllmMaxNumSeqs: active.vllmMaxNumSeqs,
          resourceStatus: active.resourceStatus,
          resourceQueueReason: active.resourceQueueReason,
          resourceMessage: active.resourceMessage,
          resourceCapacityJobs: active.resourceCapacityJobs,
          runningGenerationJobsAtStart: active.runningGenerationJobsAtStart,
          queuedGenerationJobsAtStart: active.queuedGenerationJobsAtStart,
          willQueueDueToResources: active.willQueueDueToResources,
          allocatedQuestionSlotsAtStart: active.allocatedQuestionSlotsAtStart,
          expectedQuestionSlotsWhenRunning: active.expectedQuestionSlotsWhenRunning,
          resourceSlotsTotal: active.resourceSlotsTotal,
          dynamicConcurrency: active.dynamicConcurrency,
          runtimeConcurrentTraces: active.runtimeConcurrentTraces,
          runtimeConcurrentUsers: active.runtimeConcurrentUsers,
          effectiveQuestionConcurrency: active.effectiveQuestionConcurrency,
        });
        startWebSocket(active.taskId, start, active.totalQ);
        toast.info("Đã nối lại job đang sinh câu hỏi");
      } else if (data.state === "running") {
        const resourceInfo = resourceInfoFromApi(data);
        setExamName(formatExamDisplayName(active.examName));
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
          ...resourceInfo,
        });
        startWebSocket(active.taskId, start, active.totalQ);
        toast.info("Đã nối lại job đang sinh câu hỏi");
      } else if (data.state === "success") {
        const res = await api.get(`/results/${active.taskId}`);
        completeGeneration(active.taskId, res.data, start);
      } else if (data.state === "failed") {
        clearActiveGeneration(active.taskId);
        setGenState({
          status: "failed",
          error: data.error || "Pipeline thất bại",
        });
      }
    } catch {
      clearActiveGeneration(active.taskId);
      setGenState({
        status: "failed",
        error: "Không nối lại được job đang chạy",
      });
    }
  }

  useEffect(() => {
    if (!localStorage.getItem("access_token")) {
      router.push("/login");
      return;
    }
    const timer = window.setTimeout(() => {
      void resumeActiveGeneration();
    }, 0);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [router]);

  const handleGenerate = async () => {
    const topicsToSubmit = validateDraft();
    if (!topicsToSubmit) return;
    setGenState({ status: "submitting" });
    setMcqs([]);
    const startedAt = nowMs();
    try {
      const { data } = await api.post("/generate", {
        topics: topicsToSubmit,
        output_name: systemExamName,
        display_name: displayExamName,
        retrieval_mode: DEFAULT_RETRIEVAL_MODE,
      });
      taskIdRef.current = data.task_id;
      const finalDisplayName = formatExamDisplayName(
        data.display_name || displayExamName,
      );
      if (data.exam_name_was_deduplicated && finalDisplayName !== displayExamName) {
        toast.info(`Tên đề đã tồn tại nên hệ thống lưu thành "${finalDisplayName}"`);
      }
      setExamName(finalDisplayName);
      const resourceInfo = resourceInfoFromApi(data);
      saveActiveGeneration({
        taskId: data.task_id,
        examName: finalDisplayName,
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
        ...resourceInfo,
      });
      setGenState({
        status: "queued",
        position: data.queue_position,
        estimatedWait: data.estimated_total_min ?? data.estimated_wait_min,
        queueWait: data.queue_wait_min ?? 0,
        estimatedRuntime: data.estimated_runtime_min ?? 0,
        jobsAhead: data.jobs_ahead ?? Math.max(0, data.queue_position - 1),
        taskId: data.task_id,
        totalQ: topicsToSubmit.reduce((sum, topic) => sum + topic.n, 0),
        questionConcurrency: data.generation_concurrency,
        llmConcurrency: data.llm_concurrency,
        vllmMaxNumSeqs: data.vllm_max_num_seqs,
        ...resourceInfo,
      });
      const submitMessage =
        resourceInfo.resourceMessage ||
        `Đã gửi yêu cầu sinh câu hỏi. Vị trí #${data.queue_position}`;
      if (resourceInfo.willQueueDueToResources) {
        toast.info(submitMessage);
      } else {
        toast.success(submitMessage);
      }
      startWebSocket(
        data.task_id,
        startedAt,
        topicsToSubmit.reduce((sum, topic) => sum + topic.n, 0),
      );
    } catch (e: unknown) {
      const message = getApiErrorDetail(e) || "Lỗi kết nối API";
      setGenState({ status: "failed", error: message });
      toast.error(message);
    }
  };

  const handleCancel = async () => {
    if (taskIdRef.current) {
      await api.delete(`/cancel/${taskIdRef.current}`).catch(() => {});
    }
    wsRef.current?.close();
    clearActiveGeneration(taskIdRef.current || undefined);
    taskIdRef.current = null;
    setGenState({ status: "idle" });
    toast.info("Job đã hủy");
  };

  const downloadPdf = async (withAnswers: boolean) => {
    if (genState.status !== "success") return;
    const { data } = await api.get(
      `/export/pdf/${genState.taskId}?include_answers=${withAnswers}`,
      { responseType: "blob" },
    );
    const a = document.createElement("a");
    a.href = URL.createObjectURL(data);
    a.download = `${systemExamName}_${withAnswers ? "answers" : "exam"}.pdf`;
    a.click();
  };

  const isConfiguring =
    genState.status === "idle" || genState.status === "failed";
  const isProcessing =
    genState.status === "queued" ||
    genState.status === "running" ||
    genState.status === "submitting";
  const resourceState =
    genState.status === "queued" || genState.status === "running"
      ? genState
      : null;
  const resourceStatusLabel = resourceState
    ? resourceState.willQueueDueToResources
      ? "Đang chờ tài nguyên"
      : "Đã cấp tài nguyên"
    : "";

  return (
    <div className="space-y-6">
      {/* Page header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-slate-800">⚡ Tạo đề thi</h1>
          <p className="text-slate-500 text-sm mt-0.5">
            Cấu hình đề thi theo chương, mức độ khó và số câu
          </p>
        </div>
        {isConfiguring && (
          <Button
            variant="outline"
            onClick={clearAll}
            className="gap-2 text-slate-500 hover:text-red-600 hover:border-red-200"
          >
            <Trash2 size={15} />
            Xóa toàn bộ
          </Button>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 items-start">
        {/* LEFT: Thông tin đề thi */}
        <div className="lg:col-span-1 space-y-4 lg:sticky lg:top-6">
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base font-bold text-slate-900 flex items-center gap-2">
                <FileText size={15} className="text-blue-500" />
                Thông tin đề thi
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div>
                <Label className="text-xs font-bold text-black-600">
                  Tên đề thi
                </Label>
                <Input
                  value={examName}
                  onChange={(e) => setExamName(e.target.value)}
                  className="mt-1.5 h-10"
                  placeholder="Ví dụ: Đề số 1"
                  disabled={!isConfiguring}
                />
                <p className="mt-1 text-xs text-slate-400">
                  Ví dụ: Đề số 1 - Chương 3
                </p>
              </div>

              <div>
                <Label className="text-xs font-bold text-black-600">
                  Mã lưu (tuỳ chọn)
                </Label>
                <Input
                  value={examCode || systemExamName}
                  onChange={(e) => setExamCode(e.target.value)}
                  className="mt-1.5 h-10 font-mono text-sm"
                  placeholder={systemExamName}
                  disabled={!isConfiguring}
                />
                <p className="mt-1 text-xs text-slate-400">
                  Dùng để quản lý và tìm kiếm nhanh
                </p>
              </div>

              {/* Stats */}
              <div className="rounded-lg border border-slate-150 bg-gray-100 divide-y divide-slate-100">
                <div className="flex items-center justify-between px-3 py-2.5">
                  <div className="flex items-center gap-2 text-sm text-black-600">
                    <BookOpen size={14} className="text-blue-500" />
                    Số chương
                  </div>
                  <span className="text-sm font-semibold text-black-800">
                    {chapters.length}
                  </span>
                </div>
                <div className="flex items-center justify-between px-3 py-2.5">
                  <div className="flex items-center gap-2 text-sm text-black-600">
                    <Layers size={14} className="text-blue-500" />
                    Số topic
                  </div>
                  <span className="text-sm font-semibold text-slate-800">
                    {allTopicsCount}
                  </span>
                </div>
                <div className="flex items-center justify-between px-3 py-2.5">
                  <div className="flex items-center gap-2 text-sm text-black-600">
                    <LayoutList size={14} className="text-blue-500" />
                    Tổng số câu
                  </div>
                  <span className="text-sm font-semibold text-slate-800">
                    {totalQ}
                  </span>
                </div>
              </div>
            </CardContent>
          </Card>

          {genState.status === "failed" && (
            <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-600">
              ❌ {genState.error}
            </div>
          )}
        </div>

        {/* RIGHT: Cấu hình đề thi + Progress + Results */}
        <div className="lg:col-span-2 space-y-4">
          {/* Chapter config */}
          {isConfiguring && (
            <>
              <div className="flex items-center justify-between">
                <h2 className="text-base font-bold text-slate-900 flex items-center gap-2">
                  <Layers size={15} className="text-blue-500" />
                  Cấu hình đề thi
                </h2>
              </div>

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

                <Button
                  variant="outline"
                  onClick={addChapter}
                  disabled={!canAddChapter}
                  className="h-11 w-full border-dashed text-slate-500 hover:text-slate-700"
                >
                  <Plus size={16} className="mr-1" />
                  {canAddChapter ? "Thêm chương" : "Đã đủ chương"}
                </Button>
              </div>

              {/* Generate button */}
              <Button
                onClick={handleGenerate}
                className="w-full h-13 text-base font-bold bg-blue-600 hover:bg-blue-700 text-white rounded-xl py-3"
                disabled={chapters.length === 0}
              >
                <Sparkles size={18} className="mr-2" />
                Tạo đề thi
              </Button>
            </>
          )}

          {/* Progress */}
          {isProcessing && (
            <Card className="overflow-hidden">
              {/* Header */}
              <div className="flex items-center justify-between px-6 pt-5 pb-4 border-b border-slate-100">
                <h3 className="text-base font-semibold text-slate-800">
                  Đang tạo pipeline
                </h3>
                {(genState.status === "running" ||
                  genState.status === "queued") && (
                  <span className="inline-flex items-center rounded-full bg-blue-50 border border-blue-200 px-3 py-1 text-sm font-medium text-blue-700">
                    {genState.status === "running"
                      ? `${genState.currentQ} / ${genState.totalQ} câu`
                      : `0 / ${genState.totalQ ?? totalQ} câu`}
                  </span>
                )}
              </div>

              <div className="px-6 py-5 space-y-5">
                {/* ── Stepper ── */}
                {(genState.status === "running" ||
                  genState.status === "queued") &&
                  (() => {
                    const cur =
                      genState.status === "queued"
                        ? 0
                        : Math.min(
                            Math.floor((genState.progress ?? 0) / 20),
                            PIPELINE_STEPS.length - 1,
                          );

                    return (
                      <div className="relative">
                        {/* Track line */}
                        <div
                          className="absolute h-px bg-slate-200"
                          style={{
                            top: 20,
                            left: "calc(10% + 20px)",
                            right: "calc(10% + 20px)",
                          }}
                        />
                        {/* Progress line */}
                        <div
                          className="absolute h-px bg-blue-500 transition-all duration-700"
                          style={{
                            top: 20,
                            left: "calc(10% + 20px)",
                            width:
                              cur === 0
                                ? 0
                                : `calc(${(cur / (PIPELINE_STEPS.length - 1)) * 80}% - 20px)`,
                          }}
                        />

                        <div className="relative grid grid-cols-5">
                          {PIPELINE_STEPS.map((step, i) => {
                            const done = i < cur;
                            const active = i === cur;
                            return (
                              <div
                                key={i}
                                className="flex flex-col items-center gap-2"
                              >
                                {/* Circle */}
                                <div
                                  className={[
                                    "w-10 h-10 rounded-full flex items-center justify-center text-sm font-semibold transition-all duration-500 z-10",
                                    done
                                      ? "bg-blue-600 text-white"
                                      : active
                                        ? "bg-blue-600 text-white ring-4 ring-blue-100"
                                        : "bg-white border-2 border-slate-200 text-slate-400",
                                  ].join(" ")}
                                >
                                  {done ? (
                                    <svg
                                      width="16"
                                      height="16"
                                      viewBox="0 0 16 16"
                                      fill="none"
                                    >
                                      <path
                                        d="M3 8l3.5 3.5L13 4.5"
                                        stroke="white"
                                        strokeWidth="2"
                                        strokeLinecap="round"
                                        strokeLinejoin="round"
                                      />
                                    </svg>
                                  ) : (
                                    i + 1
                                  )}
                                </div>

                                {/* Label */}
                                <span
                                  className={[
                                    "text-xs font-semibold text-center leading-tight",
                                    active
                                      ? "text-blue-600"
                                      : done
                                        ? "text-blue-600"
                                        : "text-slate-400",
                                  ].join(" ")}
                                >
                                  {step.label}
                                </span>

                                {/* Description */}
                                <span className="text-xs text-slate-400 text-center leading-snug px-1">
                                  {PIPELINE_STEP_DESCRIPTIONS[step.label] ?? ""}
                                </span>
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    );
                  })()}

                {/* ── Status box ── */}
                <div className="flex items-center gap-3 rounded-xl bg-slate-50 border border-slate-100 px-4 py-3">
                  {genState.status === "submitting" ? (
                    <>
                      <div className="w-5 h-5 rounded-full border-2 border-slate-300 border-t-blue-500 animate-spin shrink-0" />
                      <span className="text-sm text-slate-500">
                        Đang submit job...
                      </span>
                    </>
                  ) : genState.status === "queued" ? (
                    <>
                      <div className="w-5 h-5 rounded-full border-2 border-slate-300 border-t-blue-500 animate-spin shrink-0" />
                      <span className="text-sm text-slate-600">
                        {genState.resourceMessage ||
                          `Đang chờ trong queue — Vị trí #${genState.position}${
                            genState.jobsAhead > 0
                              ? `, ${genState.jobsAhead} job phía trước`
                              : ""
                          }`}
                      </span>
                    </>
                  ) : (
                    <>
                      <div className="w-5 h-5 rounded-full border-2 border-slate-200 border-t-blue-500 animate-spin shrink-0" />
                      <span className="text-sm text-slate-600">
                        {genState.step ?? "Đang xử lý"}... Vui lòng chờ trong
                        giây lát.
                      </span>
                    </>
                  )}
                </div>

                {resourceState?.resourceMessage && (
                    <div className="rounded-xl border border-blue-100 bg-blue-50/60 px-4 py-3 text-sm text-slate-700">
                      <div className="font-semibold text-blue-700">
                        {resourceStatusLabel}
                      </div>
                      <p className="mt-1 leading-5 text-slate-600">
                        {resourceState.resourceMessage}
                      </p>
                    </div>
                  )}

                {/* ── Cancel button ── */}
                {genState.status !== "submitting" && (
                  <Button
                    onClick={handleCancel}
                    variant="outline"
                    className="w-full text-slate-500 border-slate-200 hover:bg-red-50 hover:text-red-500 hover:border-red-200"
                  >
                    <X size={14} className="mr-1.5" />
                    Hủy tạo
                  </Button>
                )}
              </div>
            </Card>
          )}

          {/* Success actions + Results */}
          {genState.status === "success" && (
            <div className="space-y-4">
              {/* ── Action buttons ── */}
              <div className="flex gap-3">
                <Button
                  onClick={() =>
                    router.push(`/dashboard/take/${genState.taskId}`)
                  }
                  className="flex-1 h-11 bg-blue-600 hover:bg-blue-700 text-white font-semibold rounded-xl"
                >
                  <PlayCircle size={16} className="mr-2" />
                  Bắt đầu làm đề
                </Button>
                <Button
                  onClick={() => downloadPdf(false)}
                  variant="outline"
                  className="flex-1 h-11 font-semibold rounded-xl border-slate-200"
                >
                  <FileText size={16} className="mr-2" />
                  PDF Đề thi
                </Button>
                <Button
                  onClick={() => {
                    setGenState({ status: "idle" });
                    setMcqs([]);
                  }}
                  variant="outline"
                  className="flex-1 h-11 font-semibold rounded-xl border-slate-200"
                >
                  <RotateCcw size={16} className="mr-2" />
                  Sinh đề mới
                </Button>
              </div>

              {/* ── Stats + topic badges ── */}
              {mcqs.length > 0 && (
                <div className="rounded-xl border border-slate-200 bg-white px-4 py-3 space-y-2.5">
                  <div className="flex items-center gap-5 text-sm text-slate-600">
                    <span className="flex items-center gap-1.5">
                      <LayoutList size={15} className="text-slate-400" />
                      <span className="font-medium">{mcqs.length} câu hỏi</span>
                    </span>
                    <span className="text-slate-200">|</span>
                    <span className="flex items-center gap-1.5">
                      <svg
                        width="15"
                        height="15"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="2"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        className="text-slate-400"
                      >
                        <circle cx="12" cy="12" r="10" />
                        <polyline points="12 6 12 12 16 14" />
                      </svg>
                      <span className="font-medium">
                        {(genState.elapsed / 60).toFixed(1)} phút
                      </span>
                    </span>
                    {genState.failed ? (
                      <>
                        <span className="text-slate-200">|</span>
                        <span className="flex items-center gap-1.5">
                          <RotateCcw size={14} className="text-slate-400" />
                          <span className="font-medium">
                            {genState.failed} câu bị loại
                          </span>
                        </span>
                      </>
                    ) : null}
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {Array.from(new Set(mcqs.map((m) => m.topic))).map((t) => (
                      <span
                        key={t}
                        className="inline-flex items-center rounded-md border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs text-slate-600"
                      >
                        {t}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* ── MCQ list ── */}
              {mcqs.length > 0 && (
                <div className="space-y-4">
                  {mcqs.map((mcq, i) => (
                    <div
                      key={i}
                      className="rounded-xl border border-slate-200 bg-white overflow-hidden"
                    >
                      {/* Question header */}
                      <div className="flex items-start gap-3 px-5 py-4 border-b border-slate-100">
                        <span className="shrink-0 inline-flex items-center rounded-md bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-700">
                          Câu {i + 1}
                        </span>
                        <p className="flex-1 text-sm font-medium text-slate-800 leading-relaxed pt-0.5">
                          <MathText text={mcq.question_text} />
                        </p>
                        <div className="flex items-center gap-2 shrink-0 pt-0.5">
                          <button className="text-slate-300 hover:text-slate-500 transition-colors">
                            <svg
                              width="16"
                              height="16"
                              viewBox="0 0 24 24"
                              fill="none"
                              stroke="currentColor"
                              strokeWidth="2"
                              strokeLinecap="round"
                              strokeLinejoin="round"
                            >
                              <path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z" />
                            </svg>
                          </button>
                          <span className="inline-flex items-center rounded-md border border-slate-200 px-2 py-0.5 text-xs font-semibold text-slate-600">
                            {mcq.difficulty_label}
                          </span>
                        </div>
                      </div>

                      {/* Options — 2-column grid */}
                      <div className="grid grid-cols-2 divide-x divide-y divide-slate-100">
                        {Object.entries(mcq.options).map(([k, v], optIdx) => (
                          <div
                            key={k}
                            className="flex items-start gap-3 px-5 py-3.5"
                          >
                            <span
                              className={[
                                "shrink-0 w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold",
                                optIdx === 0
                                  ? "bg-slate-800 text-white"
                                  : "border border-slate-300 text-slate-600 bg-white",
                              ].join(" ")}
                            >
                              {k}
                            </span>
                            <span className="text-sm text-slate-700 leading-relaxed pt-0.5">
                              <MathText text={v} />
                            </span>
                          </div>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
