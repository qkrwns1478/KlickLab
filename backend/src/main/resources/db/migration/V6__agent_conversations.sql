-- =====================================================================
-- 분석 에이전트 대화(멀티턴): 같은 conversation_id 의 실행(run)이 한 대화를 이룬다.
--  * 기존 실행은 각각 하나의 대화로 취급한다 (conversation_id = id).
--  * 새 컬럼은 klicklab_agent 의 기존 테이블 권한(SELECT, INSERT, UPDATE)에 포함된다.
-- =====================================================================

ALTER TABLE agent_runs ADD COLUMN conversation_id UUID;
UPDATE agent_runs SET conversation_id = id;
ALTER TABLE agent_runs
    ALTER COLUMN conversation_id SET NOT NULL,
    ALTER COLUMN conversation_id SET DEFAULT gen_random_uuid();

CREATE INDEX idx_agent_runs_conversation
    ON agent_runs (sdk_key, user_id, conversation_id, created_at);
