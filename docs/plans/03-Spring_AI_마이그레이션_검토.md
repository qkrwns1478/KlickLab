# Spring AI 마이그레이션 검토

작성일: 2026-11-26

## 검토 질문

Python(FastAPI)으로 분리된 분석 에이전트 서버를 Spring 백엔드에 통합하고, LLM 연동을 Spring AI로 대체하는 편이 나은가?

## 결론

**Python 서버 분리를 유지한다.**

현재 에이전트의 핵심은 Spring AI가 기본으로 제공하는 영역(표준 tool calling, RAG 파이프라인)이 아니라, 그 바깥에 있는 제어 로직이다. 예산 관리, 단계별 이벤트 스트리밍, 공급자별 예외 처리, SQL 정적 검증이 여기에 해당한다. 마이그레이션하더라도 Spring AI는 모델 클라이언트 정도로만 쓰이고, 나머지는 Java로 다시 작성해야 한다. 재작성 비용과 보안·품질 회귀 위험에 비해, 얻는 이득(배포 단위 하나 감소, 설정 공유)은 작다. 설정 공유는 마이그레이션 없이도 해결할 수 있으며 이미 적용했다 (아래 "후속 조치").

## 현재 에이전트 구성

| 구성 | 위치 | 규모·특징 |
|---|---|---|
| Tool Loop | `agent/app/agent/loop.py` | 843줄. 도구 호출마다 예산을 차감하고 SSE 이벤트를 내보낸다. 이력 압축, 도구 호출 형식 오류 재시도, 호출별 타임아웃을 처리한다 |
| 난이도 분류·예산 | `agent/app/agent/router.py`, `budget.py` | 난이도별 한도, 80% 경고, 1회 승격(`request_more_budget`), 레이트 리밋 대기 시간 제외 |
| LLM 계층 | `agent/app/llm/` | Chat Completions와 Responses API를 함께 지원한다. gpt-6 계열은 도구와 `reasoning_effort`를 함께 쓰려면 Responses API가 필요하다. Ollama 폴백, `tool_choice` 무시 대응, 429 대기, 파라미터 제거 등 공급자별 처리가 있다 |
| SQL 가드 | `agent/app/sql/guard.py` | sqlglot으로 테이블 화이트리스트와 위험 함수를 차단한다. DB 롤과 RLS 앞에 있는 보안 계층이다 |
| 지식 베이스 | `agent/app/knowledge/` | prompt/rag 모드. 로컬 임베딩은 sentence-transformers(bge-m3)를 쓴다 |
| 관측 | `agent/app/tracing.py`, `metrics.py` | Langfuse ingestion API를 직접 호출하고, Prometheus 메트릭을 내보낸다 |
| 테스트·평가 | `agent/tests/`, `agent/evals/` | 앱 코드 약 5.8천 줄, 테스트·평가 코드 약 6.2천 줄. golden SQL, 안전성, 원인 분석 문항과 LLM judge, 실측 리포트, CI workflow |

백엔드는 Spring Boot 4.1.2, Java 21이다.

## 항목별 비교

| 항목 | Python 분리 유지 | Spring AI 통합 |
|---|---|---|
| 루프 제어 | 이미 세밀하게 구현되어 있다 | 내부 도구 실행이 루프를 숨긴다. 단계별 예산과 이벤트를 제어하려면 `internalToolExecutionEnabled(false)`로 끄고 루프를 직접 작성해야 하므로, 결국 현재 로직을 Java로 옮기는 일이 된다 |
| 공급자 대응 | Responses API, reasoning, Ollama 처리를 갖추고 있다 | 추상화 계층이 최신 API와 공급자별 동작을 늦게 따라가는 경향이 있다. Responses API와 reasoning 파라미터 지원 여부를 먼저 검증해야 한다 |
| SQL 가드 | sqlglot이 PostgreSQL 방언을 충분히 지원한다 | JSqlParser 등으로 다시 작성해야 한다. 보안 계층이므로 회귀가 생기면 위험하다 |
| 임베딩 | sentence-transformers로 로컬 계산 | ONNX 변환 모델이나 외부 임베딩 엔드포인트로 대체해야 한다 |
| 평가 체계 | 그대로 사용한다 | 하네스를 다시 작성하거나 HTTP 호출 방식으로 바꿔야 하고, 기준선을 유료 평가로 다시 측정해야 한다 |
| 배포·운영 | 컨테이너가 하나 더 있다 | 배포 단위가 하나 줄고, 인증·Actuator·Micrometer를 공유한다 |
| 장애 격리 | LLM 지연이나 메모리 문제가 대시보드 API에 번지지 않는다 | 긴 SSE 요청이 같은 JVM에서 실행된다. 가상 스레드로 완화할 수 있지만 격리와 독립 확장은 잃는다 |
| 버전 호환 | 해당 없음 | Boot 4.1 위에서는 Spring AI 2.x 계열이 필요하다. 호환되는 안정 버전부터 확인해야 한다 |
| 설계 의도 | 계획 01에서 "Spring 백엔드는 건드리지 않는다"고 정했고, 서비스 경계를 드러내는 것이 목표다 | 이 결정을 뒤집는다 |

## 마이그레이션이 더 나은 조건

아래 조건이 대부분 해당하면 Spring AI 통합을 다시 검토한다. 현재는 거의 해당하지 않는다.

- 에이전트가 단순한 RAG나 표준 tool calling 수준이라서 프레임워크 기본 동작으로 충분하다.
- 팀이 Java만 유지보수할 수 있어서 Python 서비스 자체가 부담이다.
- 운영 인력이 적어서 컨테이너 하나를 줄이는 이득이 크다.

## 후속 조치

- JWT·CORS 설정 일원화: 루트 `.env`를 공통 값의 단일 출처로 정하고, 두 서버가 루트 `.env` → 서비스별 `.env` 순으로 읽게 했다. compose는 `x-shared-env` 앵커로 공통 값을 공유한다. ([작업 로그](../logs/2026-11-26/02-JWT_CORS_설정_일원화.md))
- 관측 통합(선택): 두 서비스가 이미 Prometheus로 수집되므로 Grafana 대시보드를 합치면 운영 관점에서 한 시스템처럼 볼 수 있다.
