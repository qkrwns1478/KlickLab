export type Difficulty = 'lookup' | 'compare' | 'diagnose' | 'out_of_scope';
export type RunStatus = 'running' | 'succeeded' | 'budget_exhausted' | 'failed' | 'rejected';

export interface Finding {
  claim: string;
  evidence: number[];
}

export interface AnswerChart {
  type: 'bar' | 'line';
  stepId: number;
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
}

export interface ConversationSummary {
  id: string;
  title: string;
  runCount: number;
  status: RunStatus;
  updatedAt: string;
}
