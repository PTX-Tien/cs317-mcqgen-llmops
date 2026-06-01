export interface User {
  username: string
  role: "admin" | "user"
  full_name: string
}

export interface AuthTokens {
  access_token: string
  refresh_token: string
  expires_in: number
  role: string
  full_name: string
}

export interface TopicConfig {
  topic_id: string
  chapter_id: string
  topic: string
  difficulty: string
  n: number
}

export type RetrievalMode = "fast" | "auto" | "quality"

export interface MCQOption {
  A: string
  B: string
  C: string
  D: string
}

export interface Evaluation {
  overall_valid: boolean
  quality_score: number
  fail_reasons: string[]
}

export interface MCQ {
  question_id: string
  question_text: string
  question_type: string
  options: MCQOption
  correct_answers: string[]
  correct_rationale?: string
  topic: string
  chapter_id?: string
  chapter_label?: string
  difficulty_label: string
  evaluation: Evaluation
  style_alignment_note?: string
}

export interface PracticeQuestion {
  question_id: string
  question_text: string
  question_type: string
  options: MCQOption
  topic: string
  difficulty_label: string
  chapter_id: string
  chapter_label: string
}

export interface PracticeDetail extends PracticeQuestion {
  position: number
  selected: string
  correct_answers: string[]
  is_correct: boolean
  correct_rationale: string
}

export interface GenerationFailure {
  question_id?: string
  topic_id?: string
  topic?: string
  chapter_id?: string
  difficulty?: string
  stage?: string
  reason?: string
  details?: unknown
}

export interface StudyRankedStat {
  key: string
  label: string
  wrong: number
  total: number
  wrong_rate: number
}

export interface StudyAttemptSummary {
  id: string
  exam_id: string
  exam_name: string
  task_id: string | null
  student_id: string
  score: number
  n_correct: number
  n_total: number
  duration_seconds: number
  submitted_at: string
  answers: Record<string, string>
  details: PracticeDetail[]
}

export interface StudySummary {
  total_attempts: number
  total_questions: number
  total_correct: number
  total_wrong: number
  average_score: number
  accuracy_rate: number
  wrong_rate: number
  top_wrong_chapters: StudyRankedStat[]
  top_wrong_topics: StudyRankedStat[]
  top_wrong_difficulties: StudyRankedStat[]
  recommendations: string[]
  recent_attempts: StudyAttemptSummary[]
}

export interface GenerateRequest {
  topics: TopicConfig[]
  output_name: string
  retrieval_mode: RetrievalMode
}

export interface JobResponse {
  task_id: string
  status: string
  queue_position: number
  jobs_ahead?: number
  active_jobs?: number
  queued_jobs?: number
  estimated_wait_min: number
  estimated_total_min?: number
  estimated_runtime_min?: number
  queue_wait_min?: number
  generation_concurrency?: number
  llm_concurrency?: number
  vllm_max_num_seqs?: number
  n_questions: number
  retrieval_mode?: RetrievalMode
  message: string
}

export type GenerationState =
  | { status: "idle" }
  | { status: "submitting" }
  | { status: "queued"; position: number; estimatedWait: number; queueWait: number; estimatedRuntime: number; jobsAhead: number; taskId: string; totalQ: number; questionConcurrency?: number; llmConcurrency?: number; vllmMaxNumSeqs?: number }
  | { status: "running"; progress: number; step: string; currentQ: number; totalQ: number; taskId: string; questionConcurrency?: number; llmConcurrency?: number; vllmMaxNumSeqs?: number }
  | { status: "success"; mcqs: MCQ[]; elapsed: number; taskId: string; failed?: number; failures?: GenerationFailure[] }
  | { status: "failed"; error: string }
