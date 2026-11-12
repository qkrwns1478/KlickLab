import React, { useState } from 'react';
import { ChevronRight, ThumbsDown, ThumbsUp } from 'lucide-react';
import clsx from 'clsx';
import { AnswerChart } from './AnswerChart';
import { StepList } from './StepList';
import type { Difficulty, RunView } from './types';

const DIFFICULTY_LABEL: Record<Difficulty, string> = {
  lookup: '조회',
  compare: '비교',
  diagnose: '진단',
  out_of_scope: '범위 밖',
};

const HIDDEN_TOOL = 'submit_report';

interface Props {
  turn: RunView;
  busy: boolean;
  /** 실시간 실행 중인 턴은 실행 단계를 펼친 채로 시작한다 */
  live: boolean;
  onRate: (value: 1 | -1) => void;
}

/** 대화의 한 턴: 질문, 실행 단계, 답변(근거·차트), 피드백. */
export const TurnView: React.FC<Props> = ({ turn, busy, live, onRate }) => {
  const [stepsOpen, setStepsOpen] = useState(live);
  const [expanded, setExpanded] = useState<Set<number>>(new Set());

  const prefix = turn.id ?? 'live';
  const steps = turn.steps.filter((s) => s.tool !== HIDDEN_TOOL);
  const { answer } = turn;

  const toggleStep = (seq: number) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (!next.delete(seq)) next.add(seq);
      return next;
    });

  const showEvidence = (seq: number) => {
    setStepsOpen(true);
    setExpanded((prev) => new Set(prev).add(seq));
    requestAnimationFrame(() =>
      document
        .getElementById(`agent-step-${prefix}-${seq}`)
        ?.scrollIntoView({ behavior: 'smooth', block: 'center' }),
    );
  };

  return (
    <div className="flex flex-col gap-5">
      <div className="self-end max-w-[85%] bg-blue-600 text-white rounded-2xl rounded-br-sm px-4 py-2.5 text-sm whitespace-pre-wrap">
        {turn.question}
      </div>

      {turn.difficulty && (
        <div className="text-xs text-gray-500">
          {DIFFICULTY_LABEL[turn.difficulty]}
          {turn.status === 'budget_exhausted' && ' · 예산 소진'}
          {turn.fallback && (
            <span className="ml-1.5 px-1.5 rounded bg-amber-50 text-amber-700" title={turn.fallback.model}>
              {turn.fallback.provider === 'local' ? '로컬 모델' : turn.fallback.model}
            </span>
          )}
        </div>
      )}

      {steps.length > 0 && (
        <div>
          <button
            onClick={() => setStepsOpen((o) => !o)}
            className="flex items-center gap-2 text-sm text-gray-600 hover:text-gray-900 mb-2"
          >
            <ChevronRight className={clsx('w-4 h-4 transition-transform', stepsOpen && 'rotate-90')} />
            실행 단계 {steps.length}
          </button>
          {stepsOpen && (
            <StepList steps={steps} idPrefix={prefix} expanded={expanded} onToggle={toggleStep} />
          )}
        </div>
      )}

      {answer && (
        <div className="flex flex-col gap-4">
          <div className="bg-white border border-gray-200 rounded-lg p-5">
            <p className="text-gray-900 whitespace-pre-wrap">{answer.summary}</p>
            {answer.findings.length > 0 && (
              <ul className="mt-4 flex flex-col gap-2.5">
                {answer.findings.map((f, i) => (
                  <li key={i} className="flex gap-2 text-sm text-gray-800">
                    <span className="mt-2 w-1 h-1 rounded-full bg-gray-400 shrink-0" />
                    <span>
                      {f.claim}
                      {f.evidence.map((seq) => (
                        <button
                          key={seq}
                          onClick={() => showEvidence(seq)}
                          className="ml-1.5 px-1.5 rounded bg-blue-50 text-blue-700 text-xs hover:bg-blue-100 align-middle"
                        >
                          {seq}
                        </button>
                      ))}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>

          {answer.chart && <AnswerChart chart={answer.chart} steps={turn.steps} />}

          {turn.id && turn.status !== 'running' && turn.status !== 'rejected' && (
            <div className="flex gap-1">
              {([1, -1] as const).map((v) => {
                const Icon = v === 1 ? ThumbsUp : ThumbsDown;
                return (
                  <button
                    key={v}
                    onClick={() => onRate(v)}
                    className={clsx(
                      'p-2 rounded-full hover:bg-gray-200',
                      turn.feedback === v ? 'text-blue-600' : 'text-gray-400',
                    )}
                  >
                    <Icon className="w-4 h-4" fill={turn.feedback === v ? 'currentColor' : 'none'} />
                  </button>
                );
              })}
            </div>
          )}
        </div>
      )}

      {turn.error && (
        <div className="bg-red-50 border border-red-200 text-red-700 rounded-lg px-4 py-3 text-sm">
          {turn.error}
        </div>
      )}

      {busy && live && !answer && (
        <div className="flex gap-1 py-2">
          {[0, 1, 2].map((i) => (
            <span
              key={i}
              className="w-2 h-2 rounded-full bg-gray-400 animate-bounce"
              style={{ animationDelay: `${i * 0.15}s` }}
            />
          ))}
        </div>
      )}
    </div>
  );
};
