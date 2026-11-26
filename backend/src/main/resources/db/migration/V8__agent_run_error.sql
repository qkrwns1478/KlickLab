-- 실패한 실행(status = 'failed')의 사용자용 사유. 새로고침·기록 조회 때도 실행 중에 본 메시지를 그대로 보여 준다.
-- 기존 실행은 NULL 이고 화면이 일반 문구로 대신한다. 공급자 응답 원문은 담지 않는다.
ALTER TABLE agent_runs ADD COLUMN error_message TEXT;
