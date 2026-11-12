import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ArrowUp, Square } from 'lucide-react';
import {
  deleteConversation,
  errorMessage,
  getConversation,
  listConversations,
  renameConversation,
  sendFeedback,
  streamRun,
} from './api';
import type { AgentEvent } from './api';
import Toast from '../ui/Toast';
import { RunHistory } from './RunHistory';
import { TurnView } from './TurnView';
import type { ConversationSummary, RunStatus, RunView } from './types';

const MAX_QUESTION = 500;

const emptyRun = (question: string): RunView => ({
  id: null,
  question,
  difficulty: null,
  status: 'running',
  steps: [],
  answer: null,
  error: null,
  feedback: null,
});

/** SSE 이벤트 하나를 화면 상태에 반영한다. */
function applyEvent(run: RunView, { type, data }: AgentEvent): RunView {
  switch (type) {
    case 'started':
      return { ...run, id: data.runId };
    case 'classified':
      return { ...run, difficulty: data.difficulty };
    case 'fallback':
      return { ...run, fallback: { provider: data.provider, model: data.model } };
    case 'tool_call':
      return {
        ...run,
        steps: [
          ...run.steps,
          { seq: data.seq, tool: data.tool, input: data.input ?? {}, output: null, error: null, durationMs: null, pending: true },
        ],
      };
    case 'tool_result':
      return {
        ...run,
        steps: run.steps.map((s) =>
          s.seq === data.seq
            ? { ...s, output: data.output ?? null, error: data.error ?? null, durationMs: data.durationMs ?? null, pending: false }
            : s,
        ),
      };
    case 'answer':
      return { ...run, answer: data as RunView['answer'] };
    case 'error':
      return { ...run, error: data.message ?? '에이전트 실행 중 오류가 발생했습니다.', status: 'failed' };
    case 'done':
      return { ...run, status: data.status as RunStatus };
    default:
      return run;
  }
}

export const AgentDashboard: React.FC = () => {
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  // 선택한 대화. 같은 대화에서 질문하면 서버가 이전 턴을 맥락으로 쓴다
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [turns, setTurns] = useState<RunView[]>([]);
  const [liveIndex, setLiveIndex] = useState<number | null>(null);
  const [question, setQuestion] = useState('');
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const closeToast = useCallback(() => setToast(null), []);
  const abortRef = useRef<AbortController | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  const refreshConversations = useCallback(async () => {
    try {
      setConversations(await listConversations());
    } catch {
      // 목록을 못 불러와도 질문은 할 수 있다
    }
  }, []);

  useEffect(() => {
    refreshConversations();
    return () => abortRef.current?.abort();
  }, [refreshConversations]);

  const last = turns[turns.length - 1];
  useEffect(() => {
    if (busy) bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [busy, last?.steps.length, last?.answer]);

  const updateLive = (index: number, fn: (run: RunView) => RunView) =>
    setTurns((prev) => prev.map((t, i) => (i === index ? fn(t) : t)));

  const ask = async () => {
    const text = question.trim();
    if (!text || busy) return;
    const controller = new AbortController();
    abortRef.current = controller;
    const index = turns.length;
    setQuestion('');
    setTurns((prev) => [...prev, emptyRun(text)]);
    setLiveIndex(index);
    setBusy(true);
    try {
      await streamRun(
        text,
        conversationId,
        (event) => {
          if (event.type === 'started') setConversationId(event.data.conversationId ?? null);
          updateLive(index, (run) => applyEvent(run, event));
        },
        controller.signal,
      );
    } catch (e) {
      if (!controller.signal.aborted) {
        updateLive(index, (run) => ({ ...run, error: errorMessage(e), status: 'failed' }));
      }
    } finally {
      setBusy(false);
      updateLive(index, (run) =>
        run.status === 'running' ? { ...run, status: 'failed', error: run.error ?? '실행이 중단되었습니다.' } : run,
      );
      refreshConversations();
    }
  };

  const stop = () => abortRef.current?.abort();

  const select = async (id: string) => {
    if (busy) return;
    try {
      const runs = await getConversation(id);
      setConversationId(id);
      setTurns(runs);
      setLiveIndex(null);
    } catch (e) {
      setConversationId(null);
      setTurns([{ ...emptyRun(''), status: 'failed', error: errorMessage(e, '불러오지 못했습니다.') }]);
      setLiveIndex(null);
    }
  };

  const newConversation = () => {
    if (busy) return;
    setConversationId(null);
    setTurns([]);
    setLiveIndex(null);
  };

  const rename = async (id: string, title: string) => {
    const previous = conversations;
    setConversations((prev) => prev.map((c) => (c.id === id ? { ...c, title } : c)));
    try {
      await renameConversation(id, title);
    } catch (e) {
      setConversations(previous);
      setToast(errorMessage(e, '이름을 바꾸지 못했습니다.'));
    }
  };

  const remove = async (id: string) => {
    if (busy) return;
    try {
      await deleteConversation(id);
    } catch (e) {
      setToast(errorMessage(e, '삭제하지 못했습니다.'));
      return;
    }
    setConversations((prev) => prev.filter((c) => c.id !== id));
    if (id === conversationId) newConversation();
  };

  const rate = async (index: number, value: 1 | -1) => {
    const turn = turns[index];
    if (!turn?.id || turn.feedback === value) return; // 서버에 취소 API가 없으므로 같은 값은 무시한다
    const previous = turn.feedback;
    updateLive(index, (run) => ({ ...run, feedback: value }));
    try {
      await sendFeedback(turn.id, value);
    } catch {
      updateLive(index, (run) => ({ ...run, feedback: previous }));
    }
  };

  return (
    <div className="flex h-[calc(100vh-148px)] bg-gray-50">
      {toast && <Toast message={toast} onClose={closeToast} />}
      <RunHistory
        conversations={conversations}
        selectedId={conversationId}
        busy={busy}
        onSelect={select}
        onNew={newConversation}
        onRename={rename}
        onDelete={remove}
      />

      <section className="flex-1 min-w-0 flex flex-col">
        <div className="flex-1 overflow-y-auto">
          <div className="max-w-3xl mx-auto px-6 py-6 flex flex-col gap-10">
            {turns.length === 0 && <div className="pt-24 text-center text-gray-400 text-lg">질문을 입력하세요</div>}
            {turns.map((turn, i) => (
              <TurnView
                key={i}
                turn={turn}
                busy={busy}
                live={i === liveIndex}
                onRate={(value) => rate(i, value)}
              />
            ))}
            <div ref={bottomRef} />
          </div>
        </div>

        <div className="border-t border-gray-200 bg-white p-4">
          <form
            className="max-w-3xl mx-auto flex items-end gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              ask();
            }}
          >
            <textarea
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
                  e.preventDefault();
                  ask();
                }
              }}
              maxLength={MAX_QUESTION}
              rows={1}
              disabled={busy}
              className="flex-1 resize-none border border-gray-300 rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-gray-50"
            />
            {busy ? (
              <button
                type="button"
                onClick={stop}
                className="w-10 h-10 rounded-full bg-gray-800 text-white flex items-center justify-center hover:bg-gray-700"
              >
                <Square className="w-4 h-4" fill="currentColor" />
              </button>
            ) : (
              <button
                type="submit"
                disabled={!question.trim()}
                className="w-10 h-10 rounded-full bg-blue-600 text-white flex items-center justify-center hover:bg-blue-700 disabled:opacity-40"
              >
                <ArrowUp className="w-5 h-5" />
              </button>
            )}
          </form>
        </div>
      </section>
    </div>
  );
};
