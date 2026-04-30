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
}

export interface JobResponse {
  task_id: string
  status: string
  queue_position: number
  estimated_wait_min: number
  n_questions: number
  message: string
}

export type GenerationState =
  | { status: "idle" }
  | { status: "submitting" }
  | { status: "queued"; position: number; estimatedWait: number; taskId: string }
  | { status: "running"; progress: number; step: string; currentQ: number; totalQ: number; taskId: string }
  | { status: "success"; mcqs: MCQ[]; elapsed: number; taskId: string }
  | { status: "failed"; error: string }
