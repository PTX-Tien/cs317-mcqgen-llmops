export interface User {
  username: string
  role: "teacher" | "student"
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
  topic: string
  difficulty_label: string
  evaluation: Evaluation
  style_alignment_note?: string
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
  | { status: "success"; mcqs: MCQ[]; elapsed: number; taskId: string }
  | { status: "failed"; error: string }
