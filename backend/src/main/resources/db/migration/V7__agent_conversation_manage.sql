-- =====================================================================
-- 분석 에이전트 대화 관리: 이름 변경, 삭제
--  * 이름을 바꾼 대화만 agent_conversation_titles 에 제목을 둔다 (없으면 첫 질문이 제목).
--  * 대화 삭제는 해당 conversation_id 의 agent_runs 를 지우고, agent_steps 는 CASCADE 로 함께 지워진다.
--    그래서 klicklab_agent 에 agent_runs DELETE 권한을 준다.
-- =====================================================================

CREATE TABLE agent_conversation_titles (
    conversation_id UUID        PRIMARY KEY,
    sdk_key         VARCHAR(64) NOT NULL,
    user_id         UUID        NOT NULL,
    title           VARCHAR(100) NOT NULL,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_agent_conversation_titles_owner
    ON agent_conversation_titles (sdk_key, user_id);

GRANT SELECT, INSERT, UPDATE, DELETE ON agent_conversation_titles TO klicklab_agent;
GRANT DELETE ON agent_runs TO klicklab_agent;
