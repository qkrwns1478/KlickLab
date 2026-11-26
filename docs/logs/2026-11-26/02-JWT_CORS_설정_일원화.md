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

## 버전 2.0.0 통일 (추가 작업)

- 기술 스택 전환(React+Node.js → React+Spring Boot+FastAPI)을 MAJOR 변경으로 보고 제품 버전을 2.0.0 으로 정했다.
- 사이드바 표시 문구(1.1.1), `frontend/package.json`(0.0.0), `agent/pyproject.toml`(0.1.0)을 2.0.0 으로 바꿨다. `backend/build.gradle` 은 이미 2.0.0 이었다.
- `npm install` 로 `package-lock.json` 을 갱신했다. `uv` 가 설치되어 있지 않아 `uv.lock` 의 `klicklab-agent` version 한 줄은 직접 고쳤다.

## 프론트엔드 의존성 취약점 보완 (추가 작업)

- `npm audit`: 21건(high 15, moderate 4, low 2). 모두 `--force` 없이 고칠 수 있었다.
- `npm audit fix` 를 두 번 실행했다 (첫 실행 뒤 의존성 트리가 바뀌어 10건이 새로 보였다). 결과 0건.
- `package.json` 은 바뀌지 않았고 `package-lock.json` 만 갱신됐다. 주요 변경: vite 7.0.0 → 7.3.8, rollup 4.44.1 → 4.68.8, esbuild 0.25.5 → 0.28.2, postcss 8.5.6 → 8.5.33, typescript-eslint 8.35.0 → 8.74.0.
- 확인: `npm run build` 성공. `npm run lint` 는 오류 0, 경고 9 (모두 `react-hooks/exhaustive-deps`. 플러그인 버전은 그대로라 기존 경고다).
