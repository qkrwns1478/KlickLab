import React from 'react';

const MAX_ROWS = 50;

const format = (v: unknown): string => {
  if (v === null || v === undefined) return '-';
  if (typeof v === 'number') {
    return Number.isInteger(v) ? v.toLocaleString() : String(Math.round(v * 10000) / 10000);
  }
  return String(v);
};

interface Props {
  columns: string[];
  rows: unknown[][];
  rowCount?: number;
}

export const ResultTable: React.FC<Props> = ({ columns, rows, rowCount }) => {
  const shown = rows.slice(0, MAX_ROWS);
  const total = rowCount ?? rows.length;
  return (
    <div>
      <div className="overflow-auto max-h-72 border border-gray-200 rounded">
        <table className="min-w-full text-xs">
          <thead className="bg-gray-50 sticky top-0">
            <tr>
              {columns.map((c) => (
                <th key={c} className="px-3 py-1.5 text-left font-medium text-gray-600 whitespace-nowrap">
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {shown.map((row, i) => (
              <tr key={i} className="border-t border-gray-100">
                {row.map((cell, j) => (
                  <td
                    key={j}
                    className={`px-3 py-1 whitespace-nowrap ${typeof cell === 'number' ? 'text-right tabular-nums' : ''}`}
                  >
                    {format(cell)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {total > shown.length && (
        <div className="mt-1 text-xs text-gray-500">
          {shown.length} / {total.toLocaleString()}행
        </div>
      )}
    </div>
  );
};
