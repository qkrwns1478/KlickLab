# JWT·CORS 설정 일원화

## 배경

백엔드와 에이전트가 같은 `JWT_SECRET`, `CORS_ALLOWED_ORIGINS` 를 각자의 `.env` 와 compose 항목에 중복으로 갖고 있었다. CORS 기본값도 서비스마다 달랐다 (백엔드 5173+8080, 에이전트 5173, compose 8080).

## 변경

- 루트 `.env` 를 공통 값의 단일 출처로 정했다. 로컬 개발 서버도 루트 `.env` 를 먼저 읽고 서비스별 `.env` 로 덮어쓴다.
  - `backend/src/main/resources/application.yml`: `spring.config.import` 에 `optional:file:../.env[.properties]` 를 앞에 추가
  - `agent/app/config.py`: `env_file=("../.env", ".env")`
- CORS 기본값을 `http://localhost:5173,http://127.0.0.1:5173,http://localhost:8080,http://127.0.0.1:8080` 로 통일했다 (에이전트 기본값, compose 기본값).
- `docker-compose.yml`: `x-shared-env` 앵커(`JWT_SECRET`, `CORS_ALLOWED_ORIGINS`, `TZ`)를 만들어 backend·agent 가 `<<: *shared-env` 로 공유한다. 에이전트도 `JWT_SECRET` 이 없으면 기동을 거부한다.
- `.env.example` 3종과 README 환경변수 설정 절을 새 구조에 맞게 고쳤다. 서비스별 예시에서 JWT·CORS 항목을 뺐다.

## 확인

- `docker compose config`: backend·agent 모두 같은 JWT_SECRET·CORS 값으로 풀린다.
- 에이전트 `pytest`: 344 passed.
- 백엔드는 설정 파일만 바뀌어 기동 테스트는 하지 않았다.

## 로컬 .env 정리 (추가 작업)

- 루트 `.env` 를 `.env.example` 로부터 만들고, `backend/.env` 의 `JWT_SECRET`, `JWT_REFRESH_SECRET` 을 옮겼다 (`agent/.env` 의 `JWT_SECRET` 과 같은 값임을 확인).
- `backend/.env` 의 JWT 두 항목, `agent/.env` 의 `JWT_SECRET`, `CORS_ALLOWED_ORIGINS`(5173만 허용하던 값)를 지웠다. CORS 는 통일된 기본값(5173+8080)을 쓴다.
- 확인: 에이전트 `Settings()` 가 루트 `.env` 에서 이전과 같은 JWT 시크릿과 통일된 CORS 목록을 읽는다. 백엔드는 기동 확인을 하지 않았다.
- `OPENAI_API_KEY` 는 범위 밖이라 `agent/.env` 에만 두었다. compose 로 띄우려면 루트 `.env` 에도 채워야 한다.
