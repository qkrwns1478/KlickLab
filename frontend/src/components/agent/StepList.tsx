import React from 'react';
import { ChevronRight, AlertCircle, Database, Search, Table2, TrendingUp, Loader2 } from 'lucide-react';
import clsx from 'clsx';
import { ResultTable } from './ResultTable';
import type { Step } from './types';

const TOOL_ICONS: Record<string, React.ElementType> = {
  run_sql: Database,
  search_knowledge: Search,
  describe_table: Table2,
  request_more_budget: TrendingUp,
};

const summarize = (step: Step): string => {
  const i = step.input;
  if (step.tool === 'run_sql') return String(i.purpose ?? i.sql ?? '');
  if (step.tool === 'describe_table') return String(i.table_name ?? i.table ?? '');
  if (step.tool === 'search_knowledge') return String(i.query ?? '');
  if (step.tool === 'request_more_budget') return String(i.reason ?? '');
  return '';
};

const StepBody: React.FC<{ step: Step }> = ({ step }) => {
  const out = step.output;
  const sql = out?.sql ?? step.input.sql;
  return (
    <div className="px-4 pb-4 pt-1 flex flex-col gap-3">
      {step.tool === 'run_sql' && sql != null && (
        <pre className="text-xs bg-gray-900 text-gray-100 rounded p-3 overflow-auto whitespace-pre-wrap">
          {String(sql)}
        </pre>
      )}
      {step.error && <div className="text-xs text-red-600 whitespace-pre-wrap">{step.error}</div>}
      {step.tool === 'run_sql' && out?.columns && out.rows ? (
        <ResultTable columns={out.columns} rows={out.rows} rowCount={out.rowCount} />
      ) : step.tool === 'run_sql' && out?.cachedFrom != null ? (
        <div className="text-xs text-gray-500">단계 {out.cachedFrom}의 결과를 재사용</div>
      ) : (
        out && (
          <pre className="text-xs bg-gray-50 border border-gray-200 rounded p-3 overflow-auto max-h-72 whitespace-pre-wrap">
            {JSON.stringify(out, null, 2)}
          </pre>
        )
      )}
    </div>
  );
};

interface Props {
  steps: Step[];
  idPrefix: string;
  expanded: Set<number>;
  onToggle: (seq: number) => void;
}

export const StepList: React.FC<Props> = ({ steps, idPrefix, expanded, onToggle }) => (
  <ol className="border border-gray-200 rounded-lg bg-white divide-y divide-gray-100">
    {steps.map((step) => {
      const Icon = TOOL_ICONS[step.tool] ?? Database;
      const open = expanded.has(step.seq);
      return (
        <li key={step.seq} id={`agent-step-${idPrefix}-${step.seq}`}>
          <button
            onClick={() => onToggle(step.seq)}
            disabled={step.pending}
            className="w-full flex items-center gap-3 px-4 py-2.5 text-left hover:bg-gray-50"
          >
            <ChevronRight className={clsx('w-4 h-4 text-gray-400 transition-transform', open && 'rotate-90')} />
            <span className="w-5 text-xs text-gray-400 tabular-nums">{step.seq}</span>
            <Icon className="w-4 h-4 text-gray-500 shrink-0" />
            <span className="text-sm text-gray-800 truncate flex-1">{summarize(step)}</span>
            {step.pending ? (
              <Loader2 className="w-4 h-4 text-blue-500 animate-spin" />
            ) : (
              <>
                {step.error && <AlertCircle className="w-4 h-4 text-red-500" />}
                {step.durationMs != null && (
                  <span className="text-xs text-gray-400 tabular-nums">
                    {(step.durationMs / 1000).toFixed(1)}s
                  </span>
                )}
              </>
            )}
          </button>
          {open && !step.pending && <StepBody step={step} />}
        </li>
      );
    })}
  </ol>
);
