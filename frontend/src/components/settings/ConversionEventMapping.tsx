import React, { useState, useRef, useEffect } from 'react';
import { Settings, Plus, Trash2, Search } from 'lucide-react';
import Toast from '../ui/Toast';


interface ConversionEvent {
  event_name: string;
  description: string;
  is_active: number;
  created_at: string;
  updated_at: string;
}

interface AvailableEvent {
  event_name: string;
  source_type: 'rule' | 'button';
  definition_count: number;
  created_date: string;
  description: string;
  event_count?: number;
  unique_users?: number;
  last_seen?: string;
}

export const ConversionEventMapping: React.FC = () => {
  const [events, setEvents] = useState<ConversionEvent[]>([]);
  const [availableEvents, setAvailableEvents] = useState<AvailableEvent[]>([]);
  const [selectedEvent, setSelectedEvent] = useState('');
  const [eventDescription, setEventDescription] = useState('');
  const [showAddForm, setShowAddForm] = useState(false);
  const [searchTerm, setSearchTerm] = useState('');
  const [loading, setLoading] = useState(false);
  const [showToast, setShowToast] = useState(false);
  const [toastMessage, setToastMessage] = useState('');
  const formRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = formRef.current;
    if (!el) return;

    if (showAddForm) {
      el.style.maxHeight = `${el.scrollHeight}px`;
      const handleTransitionEnd = () => (el.style.maxHeight = 'none');
      el.addEventListener('transitionend', handleTransitionEnd);
      return () => el.removeEventListener('transitionend', handleTransitionEnd);
    } else {
      el.style.maxHeight = `${el.scrollHeight}px`;
      requestAnimationFrame(() => {
        el.style.maxHeight = '0px';
      });
    }
  }, [showAddForm]);

  // 전환 이벤트 목록 조회
  const fetchEvents = async () => {
    try {
      const token = localStorage.getItem('klicklab_token') || sessionStorage.getItem('klicklab_token');
      const response = await fetch('/api/conversion-events', {
        headers: { Authorization: `Bearer ${token}` }
      });

      if (response.ok) {
        const data = await response.json();
        setEvents(data);
      }
    } catch (error) {
      console.error('Failed to fetch conversion events:', error);
    }
  };

  // 사용 가능한 이벤트 목록 조회
  const fetchAvailableEvents = async () => {
    try {
      const token = localStorage.getItem('klicklab_token') || sessionStorage.getItem('klicklab_token');
      const response = await fetch('/api/conversion-events/available', {
        headers: { Authorization: `Bearer ${token}` }
      });

      if (response.ok) {
        const data = await response.json();
        setAvailableEvents(data.available);
      }
    } catch (error) {
      console.error('Failed to fetch available events:', error);
    }
  };
  useEffect(() => {
    fetchEvents();
    fetchAvailableEvents();
  }, []);

  // 필터링된 이벤트 목록
  const filteredAvailableEvents = availableEvents.filter(event =>
    event.event_name.toLowerCase().includes(searchTerm.toLowerCase())
  );

  // 전환 이벤트 추가
  const handleAddEvent = async (eventName: string) => {
    setLoading(true);

    try {
      const token = localStorage.getItem('klicklab_token') || sessionStorage.getItem('klicklab_token');
      const response = await fetch('/api/conversion-events', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`
        },
        body: JSON.stringify({
          event_name: eventName,
          description: eventDescription || ''
        })
      });

      if (response.ok) {
        setToastMessage(`'${eventName}' 이벤트가 전환 이벤트로 추가되었습니다.`);
        setShowToast(true);
        setSelectedEvent('');
        setEventDescription('');
        setShowAddForm(false);
        fetchEvents();
        fetchAvailableEvents();
      }
    } catch (error) {
      console.error('Failed to add conversion event:', error);
      setToastMessage('전환 이벤트 추가에 실패했습니다.');
      setShowToast(true);
    } finally {
      setLoading(false);
    }
  };

  // 전환 이벤트 삭제
  const handleDeleteEvent = async (event_name: string) => {
    if (!window.confirm(`'${event_name}' 이벤트를 삭제하시겠습니까?`)) {
      return;
    }

    try {
      const token = localStorage.getItem('klicklab_token') || sessionStorage.getItem('klicklab_token');
      const response = await fetch(`/api/conversion-events/${event_name}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${token}` }
      });
      if (response.ok) {
        fetchEvents();
        setToastMessage('전환 이벤트가 삭제되었습니다.');
        setShowToast(true);
      }
    } catch (error) {
      console.error('Failed to delete conversion event:', error);
    }
  };

  return (
    <div className="custom-card">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Settings className="w-5 h-5 text-gray-600" />
          <h2 className="text-lg font-semibold text-gray-900">전환 이벤트 관리</h2>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => setShowAddForm(!showAddForm)}
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 transition-colors duration-200 text-sm"
          >
            <Plus className="w-4 h-4" />
            이벤트 추가
          </button>
        </div>
      </div>

      {/* 추가 폼 */}
      <div
        ref={formRef}
        className="overflow-hidden transition-all duration-300 ease-in-out"
        style={{ maxHeight: '0px' }}
      >
        <div className="mb-6 p-4 border rounded-md bg-gray-50">
          <h3 className="text-sm font-semibold text-gray-700 mb-3">수집된 이벤트에서 선택</h3>

          {/* 검색 */}
          <div className="relative mb-3">
            <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 w-4 h-4 text-gray-400" />
            <input
              type="text"
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="w-full pl-10 pr-3 py-2 border border-gray-300 rounded-md text-sm"
              placeholder="이벤트 이름 검색..."
            />
          </div>

          {/* 이벤트 선택 목록 */}
          <div className="max-h-48 overflow-y-auto border rounded-md bg-white mb-3">
            {filteredAvailableEvents.length === 0 ? (
              <div className="p-4 text-center text-gray-500 text-sm">
                선택 가능한 이벤트가 없습니다.
                <p className="text-xs mt-2">
                  이벤트 규칙이나 버튼 설정에서 먼저 이벤트를 정의해주세요.
                </p>
              </div>
            ) : (
              filteredAvailableEvents.map((event) => (
                <div
                  key={event.event_name}
                  onClick={() => setSelectedEvent(event.event_name)}
                  className={`p-3 border-b cursor-pointer hover:bg-gray-50 ${selectedEvent === event.event_name ? 'bg-blue-50' : ''
                    }`}
                >
                  <div className="flex justify-between items-center">
                    <div>
                      <span className="font-medium text-sm">{event.event_name}</span>
                      <div className="flex items-center gap-2 mt-1">
                        <span className={`text-xs px-2 py-0.5 rounded ${event.source_type === 'rule'
                            ? 'bg-purple-100 text-purple-700'
                            : 'bg-blue-100 text-blue-700'
                          }`}>
                          {event.source_type === 'rule' ? '규칙' : '버튼'}
                        </span>
                        <span className="text-xs text-gray-500">
                          {event.description}
                        </span>
                      </div>
                    </div>
                    <div className="text-right">
                      {event.event_count ? (
                        <div className="text-xs text-gray-500">
                          {event.event_count.toLocaleString()}회
                          <br />
                          {(event.unique_users ?? 0).toLocaleString()}명
                        </div>
                      ) : (
                        <div className="text-xs text-gray-400">
                          미발생
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>

          {/* 선택된 이벤트 정보 */}
          {selectedEvent && (
            <div className="mb-3">
              <label className="block text-sm font-medium text-gray-700 mb-1">설명 (선택사항)</label>
              <input
                type="text"
                value={eventDescription}
                onChange={(e) => setEventDescription(e.target.value)}
                className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm"
                placeholder="예: 구매 완료"
              />
            </div>
          )}

          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={() => {
                setShowAddForm(false);
                setSelectedEvent('');
                setEventDescription('');
              }}
              className="px-4 py-2 border border-gray-300 rounded-md text-sm text-gray-700 hover:bg-gray-50"
            >
              취소
            </button>
            <button
              onClick={() => handleAddEvent(selectedEvent)}
              disabled={!selectedEvent || loading}
              className="px-4 py-2 bg-blue-600 text-white rounded-md text-sm hover:bg-blue-700 disabled:opacity-50"
            >
              {loading ? '추가 중...' : '추가'}
            </button>
          </div>
        </div>
      </div>

      {/* 이벤트 목록 테이블 */}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-200">
              <th className="text-left py-3 px-4 font-medium text-gray-900">이벤트 이름</th>
              <th className="text-left py-3 px-4 font-medium text-gray-900">설명</th>
              <th className="text-center py-3 px-4 font-medium text-gray-900">액션</th>
            </tr>
          </thead>
          <tbody>
            {events.length === 0 ? (
              <tr>
                <td colSpan={4} className="text-center py-8 text-gray-500">
                  등록된 전환 이벤트가 없습니다.
                </td>
              </tr>
            ) : (
              events.map((event) => (
                <tr key={event.event_name} className="border-b border-gray-100">
                  <td className="py-3 px-4 text-gray-700 font-medium">
                    {event.event_name}
                  </td>
                  <td className="py-3 px-4 text-gray-600">
                    {event.description || '-'}
                  </td>
                  <td className="py-3 px-4 text-center">
                    <button
                      onClick={() => handleDeleteEvent(event.event_name)}
                      className="text-red-600 hover:text-red-800"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* 안내 메시지 */}
      <div className="mt-4 p-4 bg-blue-50 rounded-md">
        <p className="text-sm text-blue-800">
          💡 전환 이벤트는 실제로 수집된 이벤트 중에서만 선택할 수 있습니다.
          Dictionary는 5-6분마다 갱신되므로 변경사항 반영에 시간이 걸릴 수 있습니다.
        </p>
      </div>

      {showToast && (
        <Toast
          message={toastMessage}
          onClose={() => setShowToast(false)}
        />
      )}
    </div>
  );
}; 