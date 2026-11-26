-- =====================================================================
-- 에이전트 RLS 기준값을 위조할 수 없는 테넌트 토큰으로 바꾼다
--
--  V4 정책은 sdk_key = current_setting('app.sdk_key') 였다. app.sdk_key 는 세션 사용자가 바꿀 수 있는
--  설정이라, SQL 정적 검증(agent guard)을 우회한 쿼리라면 initplan/CTE 안의 set_config 한 번으로
--  다른 테넌트 행을 볼 수 있었다 (Phase 4 안전성 평가에서 확인: 공격 테넌트 세션에서 데모 테넌트 33,714행).
--
--  * agent_tenant_tokens: sdk_key 마다 추측할 수 없는 토큰. klicklab_agent_ro 는 이 테이블을 읽을 수 없다
--  * agent_issue_tenant_token(sdk_key): 토큰 발급·조회. 실행 로그 롤(klicklab_agent)만 호출할 수 있다
--  * agent_current_sdk_key(): 세션의 app.tenant_token 에 대응하는 sdk_key. 토큰이 없거나 틀리면 NULL → 0행
--  * 읽기 전용 연결은 자기 테넌트 토큰만 알 수 있으므로 app.tenant_token 을 바꿔도 다른 테넌트가 보이지 않는다
-- =====================================================================

CREATE TABLE agent_tenant_tokens (
    sdk_key    VARCHAR(64) PRIMARY KEY,
    token      TEXT        NOT NULL UNIQUE DEFAULT gen_random_uuid()::text,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

REVOKE ALL ON agent_tenant_tokens FROM PUBLIC;

CREATE FUNCTION agent_issue_tenant_token(p_sdk_key VARCHAR) RETURNS TEXT
    LANGUAGE sql
    SECURITY DEFINER
    SET search_path = pg_catalog, public
AS $$
    INSERT INTO public.agent_tenant_tokens (sdk_key) VALUES (p_sdk_key)
    ON CONFLICT (sdk_key) DO UPDATE SET sdk_key = EXCLUDED.sdk_key
    RETURNING token
$$;

REVOKE ALL ON FUNCTION agent_issue_tenant_token(VARCHAR) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION agent_issue_tenant_token(VARCHAR) TO klicklab_agent;

CREATE FUNCTION agent_current_sdk_key() RETURNS VARCHAR
    LANGUAGE sql
    STABLE
    SECURITY DEFINER
    SET search_path = pg_catalog, public
AS $$
    SELECT sdk_key FROM public.agent_tenant_tokens
    WHERE token = current_setting('app.tenant_token', true)
$$;

REVOKE ALL ON FUNCTION agent_current_sdk_key() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION agent_current_sdk_key() TO klicklab_agent_ro;

-- (SELECT ...) 로 감싸 쿼리당 한 번만 계산한다 (initplan). 행마다 함수를 부르지 않고 sdk_key 인덱스도 쓸 수 있다
DO $$
DECLARE
    t TEXT;
BEGIN
    FOR t IN
        SELECT tablename FROM pg_policies
        WHERE schemaname = 'public' AND policyname = 'agent_ro_sdk_key'
    LOOP
        EXECUTE format(
            'ALTER POLICY agent_ro_sdk_key ON %I USING (sdk_key = (SELECT agent_current_sdk_key()))', t);
    END LOOP;
END
$$;
