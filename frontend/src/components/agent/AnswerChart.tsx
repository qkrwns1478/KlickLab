import React, { useMemo } from 'react';
import HorizontalBarChart from '../HorizontalBarChart';
import HorizontalLineChart from '../HorizontalLineChart';
import type { AnswerChart as ChartSpec, Step } from './types';

const num = (v: unknown): number => {
  const n = typeof v === 'number' ? v : Number(v);
  return Number.isFinite(n) ? n : 0;
};

interface Props {
  chart: ChartSpec;
  steps: Step[];
}

/** 답변의 chart 스펙을 근거 step 의 결과 행으로 그린다. 컬럼이 맞지 않으면 아무것도 그리지 않는다. */
export const AnswerChart: React.FC<Props> = ({ chart, steps }) => {
  const output = steps.find((s) => s.seq === chart.stepId)?.output;
  const columns = output?.columns;
  const rows = output?.rows;

  const indexes = useMemo(() => {
    if (!columns || !rows) return null;
    const xi = columns.indexOf(chart.x);
    const yi = chart.y.map((y) => columns.indexOf(y));
    if (xi < 0 || yi.length === 0 || yi.some((i) => i < 0)) return null;
    return { xi, yi };
  }, [columns, rows, chart.x, chart.y]);

  if (!rows || !indexes) return null;
  const { xi, yi } = indexes;

  return (
    <div className="border border-gray-200 rounded-lg bg-white p-4">
      {chart.title && <div className="text-sm font-semibold text-gray-800 mb-3">{chart.title}</div>}
      {chart.type === 'line' ? (
        <HorizontalLineChart
          data={rows.map((r) => {
            const item: Record<string, unknown> = { date: String(r[xi]) };
            chart.y.forEach((y, k) => (item[y] = num(r[yi[k]])));
            return item;
          })}
          lines={chart.y.map((y) => ({ key: y, name: y }))}
          showLegendBottom={chart.y.length > 1}
          height={chart.y.length > 1 ? 240 : 220}
        />
      ) : (
        <div className="flex flex-col gap-4">
          {chart.y.map((y, k) => (
            <div key={y}>
              {chart.y.length > 1 && <div className="text-xs text-gray-500 mb-1">{y}</div>}
              <HorizontalBarChart
                data={rows.map((r) => ({ label: String(r[xi]), value: num(r[yi[k]]) }))}
                valueFormatter={(v) =>
                  Number.isInteger(v) ? v.toLocaleString() : String(Math.round(v * 100) / 100)
                }
              />
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
