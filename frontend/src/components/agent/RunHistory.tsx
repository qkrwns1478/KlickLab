import React, { useState } from 'react';
import { Pencil, Plus, Trash2 } from 'lucide-react';
import clsx from 'clsx';
import type { ConversationSummary, RunStatus } from './types';

const DOT: Record<RunStatus, string> = {
  running: 'bg-blue-500 animate-pulse',
  succeeded: 'bg-green-500',
  budget_exhausted: 'bg-amber-500',
  failed: 'bg-red-500',
  rejected: 'bg-gray-400',
};

const MAX_TITLE = 100;

interface Props {
  conversations: ConversationSummary[];
  selectedId: string | null;
  busy: boolean;
  onSelect: (id: string) => void;
  onNew: () => void;
  onRename: (id: string, title: string) => void;
  onDelete: (id: string) => void;
}

export const RunHistory: React.FC<Props> = ({
  conversations,
  selectedId,
  busy,
  onSelect,
  onNew,
  onRename,
  onDelete,
}) => {
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState('');
  const [confirmId, setConfirmId] = useState<string | null>(null);

  const startEdit = (c: ConversationSummary) => {
    setEditingId(c.id);
    setDraft(c.title);
  };

  const commit = (c: ConversationSummary) => {
    const title = draft.trim();
    setEditingId(null);
    if (title && title !== c.title) onRename(c.id, title);
  };

  return (
    <aside className="w-72 shrink-0 border-r border-gray-200 bg-white flex flex-col min-h-0">
      <div className="p-3 border-b border-gray-100">
        <button
          onClick={onNew}
          disabled={busy}
          className="w-full flex items-center justify-center gap-2 py-2 rounded-lg bg-blue-600 text-white text-sm font-medium hover:bg-blue-700 disabled:opacity-50"
        >
          <Plus className="w-4 h-4" />새 대화
        </button>
      </div>
      <ul className="flex-1 overflow-y-auto">
        {conversations.map((c) => (
          <li
            key={c.id}
            className={clsx(
              'group relative border-b border-gray-50 hover:bg-gray-50',
              c.id === selectedId && 'bg-blue-50 hover:bg-blue-50',
            )}
          >
            {editingId === c.id ? (
              <div className="px-4 py-3">
                <input
                  autoFocus
                  value={draft}
                  maxLength={MAX_TITLE}
                  onChange={(e) => setDraft(e.target.value)}
                  onBlur={() => commit(c)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && !e.nativeEvent.isComposing) commit(c);
                    if (e.key === 'Escape') setEditingId(null);
                  }}
                  className="w-full text-sm border border-blue-400 rounded px-2 py-1 focus:outline-none"
                />
              </div>
            ) : (
              <>
                <button onClick={() => onSelect(c.id)} className="w-full text-left px-4 py-3 flex gap-3">
                  <span className={clsx('mt-1.5 w-2 h-2 rounded-full shrink-0', DOT[c.status])} />
                  <span className="min-w-0 flex-1">
                    <span className="block text-sm text-gray-900 line-clamp-2">{c.title}</span>
                    <span className="block mt-1 text-xs text-gray-400">
                      {new Date(c.updatedAt).toLocaleString('ko-KR', {
                        month: 'numeric',
                        day: 'numeric',
                        hour: '2-digit',
                        minute: '2-digit',
                      })}
                      {c.runCount > 1 && ` · ${c.runCount}`}
                    </span>
                  </span>
                </button>
                {confirmId === c.id ? (
                  <div className="absolute inset-0 flex items-center justify-end gap-1.5 px-3 bg-white/95">
                    <button
                      onClick={() => {
                        setConfirmId(null);
                        onDelete(c.id);
                      }}
                      className="px-3 py-1 rounded text-xs font-medium text-white bg-red-600 hover:bg-red-700"
                    >
                      삭제
                    </button>
                    <button
                      onClick={() => setConfirmId(null)}
                      className="px-3 py-1 rounded text-xs text-gray-600 bg-gray-100 hover:bg-gray-200"
                    >
                      취소
                    </button>
                  </div>
                ) : (
                  !(busy && c.id === selectedId) && (
                  <div className="absolute right-2 top-2 hidden group-hover:flex gap-0.5 bg-white/90 rounded">
                    <button
                      onClick={() => startEdit(c)}
                      className="p-1.5 rounded text-gray-400 hover:text-gray-700 hover:bg-gray-100"
                    >
                      <Pencil className="w-3.5 h-3.5" />
                    </button>
                    <button
                      onClick={() => setConfirmId(c.id)}
                      className="p-1.5 rounded text-gray-400 hover:text-red-600 hover:bg-gray-100"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                  )
                )}
              </>
            )}
          </li>
        ))}
      </ul>
    </aside>
  );
};
