import { getToken } from '../../utils/storage';
import type { Answer, ConversationSummary, Difficulty, RunStatus, RunView, Step } from './types';

const headers = (): Record<string, string> => ({
  'Content-Type': 'application/json',
  Authorization: `Bearer ${getToken() ?? ''}`,
});

/** 네트워크 오류(서버 꺼짐 등)의 브라우저 원문 대신 보여 줄 문구로 바꾼다. */
export function errorMessage(e: unknown, fallback = '요청에 실패했습니다.'): string {
  if (e instanceof TypeError) return '에이전트 서버에 연결할 수 없습니다.';
  return e instanceof Error && e.message ? e.message : fallback;
}

async function ensureOk(res: Response): Promise<Response> {
  if (res.ok) return res;
  if (res.status === 401) throw new Error('로그인이 만료되었습니다. 다시 로그인해 주세요.');
  let detail = '';
  try {
    detail = (await res.json())?.detail ?? '';
  } catch {
    // 본문이 JSON 이 아니면 상태 코드만 쓴다
  }
  throw new Error(typeof detail === 'string' && detail ? detail : `요청에 실패했습니다 (${res.status})`);
}

export async function listConversations(): Promise<ConversationSummary[]> {
  const res = await ensureOk(await fetch('/agent/conversations?limit=50', { headers: headers() }));
  return res.json();
}

interface RunDetail {
  id: string;
  question: string;
  difficulty: Difficulty | null;
  status: RunStatus;
  answer: Answer | null;
  errorMessage: string | null;
  feedback: 1 | -1 | null;
  steps: Step[];
}

export async function renameConversation(id: string, title: string): Promise<void> {
  await ensureOk(
    await fetch(`/agent/conversations/${id}`, {
      method: 'PATCH',
      headers: headers(),
      body: JSON.stringify({ title }),
    }),
  );
}

export async function deleteConversation(id: string): Promise<void> {
  await ensureOk(await fetch(`/agent/conversations/${id}`, { method: 'DELETE', headers: headers() }));
}

/** 대화에 속한 실행들을 오래된 순서로 돌려준다. */
export async function getConversation(id: string): Promise<RunView[]> {
  const res = await ensureOk(await fetch(`/agent/conversations/${id}`, { headers: headers() }));
  const data: { runs: RunDetail[] } = await res.json();
  return data.runs.map((d) => ({
    id: d.id,
    question: d.question,
    difficulty: d.difficulty,
    status: d.status,
    steps: d.steps,
    answer: d.answer,
    error: d.status === 'failed' ? (d.errorMessage ?? '실행이 완료되지 못했습니다.') : null,
    feedback: d.feedback,
  }));
}

export async function sendFeedback(id: string, feedback: 1 | -1): Promise<void> {
  await ensureOk(
    await fetch(`/agent/runs/${id}/feedback`, {
      method: 'POST',
      headers: headers(),
      body: JSON.stringify({ feedback }),
    }),
  );
}

export interface AgentEvent {
  type: string;
  data: Record<string, any>;
}

/** POST /agent/runs 의 SSE 스트림을 이벤트 단위로 읽는다. */
export async function streamRun(
  question: string,
  conversationId: string | null,
  onEvent: (event: AgentEvent) => void,
  signal: AbortSignal,
): Promise<void> {
  const res = await ensureOk(
    await fetch('/agent/runs', {
      method: 'POST',
      headers: headers(),
      body: JSON.stringify({ question, conversationId }),
      signal,
    }),
  );
  if (!res.body) throw new Error('응답 스트림을 열 수 없습니다.');

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n');
    let end: number;
    while ((end = buffer.indexOf('\n\n')) >= 0) {
      const block = buffer.slice(0, end);
      buffer = buffer.slice(end + 2);
      const event = parseBlock(block);
      if (event) onEvent(event);
    }
  }
}

function parseBlock(block: string): AgentEvent | null {
  let type = 'message';
  const data: string[] = [];
  for (const line of block.split('\n')) {
    if (line.startsWith('event:')) type = line.slice(6).trim();
    else if (line.startsWith('data:')) data.push(line.slice(5).trimStart());
  }
  if (data.length === 0) return null;
  try {
    return { type, data: JSON.parse(data.join('\n')) };
  } catch {
    return null;
  }
}
