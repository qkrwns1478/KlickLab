export type Difficulty = 'lookup' | 'compare' | 'diagnose' | 'out_of_scope';
export type RunStatus = 'running' | 'succeeded' | 'budget_exhausted' | 'failed' | 'rejected';

export interface Finding {
  claim: string;
  evidence: number[];
}

export interface AnswerChart {
  type: 'bar' | 'line';
  step_id: number;
  x: string;
  y: string[];
  title?: string;
}

export interface Answer {
  summary: string;
  findings: Finding[];
  chart: AnswerChart | null;
  forced?: boolean;
  droppedFindings?: number;
}

export interface SqlOutput {
  sql?: string;
  columns?: string[];
  rows?: unknown[][];
  rowCount?: number;
  truncated?: boolean;
  elapsedMs?: number;
  cachedFrom?: number;
}

export interface Step {
  seq: number;
  tool: string;
  input: Record<string, unknown>;
  output: (SqlOutput & Record<string, unknown>) | null;
  error: string | null;
  durationMs: number | null;
  pending?: boolean;
}

export interface RunView {
  id: string | null;
  question: string;
  difficulty: Difficulty | null;
  status: RunStatus;
  steps: Step[];
  answer: Answer | null;
  error: string | null;
  feedback: 1 | -1 | null;
  /** 기본 LLM 공급자가 실패해 대체 공급자가 답했다 (스트림 응답 직후에만 안다) */
  fallback?: { provider: string; model: string } | null;
}

export interface ConversationSummary {
  id: string;
  title: string;
  runCount: number;
  status: RunStatus;
  updatedAt: string;
}
