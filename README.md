![5 - Copy](https://github.com/user-attachments/assets/672ea52a-5424-419d-8908-52b85057fdc0)


# *KlickLab*

## 목차

1. [프로젝트 소개](#프로젝트-소개)
2. [팀원 소개](#팀원-소개)
3. [대시보드 스크린샷](#대시보드-스크린샷)
4. [포스터](#포스터)
5. [아키텍처](#아키텍처)
6. [데이터 흐름도](#데이터-흐름도)
7. [기술 스택](#기술-스택)
8. [설치 및 실행](#설치-및-실행)

## 프로젝트 소개

> **KlickLab**은 웹사이트에서 발생하는 행동 데이터를 실시간 수집·구조화하여<br />
> 운영자가 **Data-Driven** 방식으로 합리적인 의사결정을 내릴 수 있도록<br />
> 지원하는 **클릭스트림** 분석 플랫폼입니다.

- 소개 영상 : https://jungle.krafton.com/news/64

## 팀원 소개

| <img src="https://avatars.githubusercontent.com/PurifiedPotion" width="100"/> | <img src="https://avatars.githubusercontent.com/jaykxo" width="100"/> | <img src="https://avatars.githubusercontent.com/qkrwns1478" width="100"/> | <img src="https://avatars.githubusercontent.com/whtierice" width="100"/> | <img src="https://avatars.githubusercontent.com/Fharena" width="100"/> | <img src="https://avatars.githubusercontent.com/At-this-moment" width="100"/> |
| :---: | :---: | :---: | :---: | :---: | :---: |
| [@PurifiedPotion](https://github.com/PurifiedPotion) | [@jaykxo](https://github.com/jaykxo) | [@qkrwns1478](https://github.com/qkrwns1478) | [@whtierice](https://github.com/whtierice) | [@Fharena](https://github.com/Fharena) | [@At-this-moment](https://github.com/At-this-moment) |
| 김관수 | 김재현 | 박준식 | 오주영 | 윤석주 | 이현재 |

## 대시보드 스크린샷

> 대시보드 탭별 스크린샷입니다. <br/>클릭하면 원본 해상도로 확대됩니다.

| Overview | User 분석 | 유입 분석 |
|:---:|:---:|:---:|
| [![Overview](https://github.com/user-attachments/assets/a069b4a0-c2b1-44b6-8d67-bb7441967522?raw=true)](https://github.com/user-attachments/assets/a069b4a0-c2b1-44b6-8d67-bb7441967522) | [![User](https://github.com/user-attachments/assets/0517d953-3da3-4f96-b83f-8aa821a82175?raw=true)](https://github.com/user-attachments/assets/0517d953-3da3-4f96-b83f-8aa821a82175) | [![Acquisition](https://github.com/user-attachments/assets/b0ffd88d-f281-43c2-9ded-27bbb89fb924?raw=true)](https://github.com/user-attachments/assets/b0ffd88d-f281-43c2-9ded-27bbb89fb924) |
| **참여도 분석** | **이벤트 타임라인** | **KPI & 설정** |
| [![Engage](https://github.com/user-attachments/assets/2b8c66e0-ea7f-42ee-9ce0-36bce874d143?raw=true)](https://github.com/user-attachments/assets/2b8c66e0-ea7f-42ee-9ce0-36bce874d143) | [![Timeline](https://github.com/user-attachments/assets/1c6546aa-0aca-4353-afea-47fe4e63b6f6?raw=true)](https://github.com/user-attachments/assets/1c6546aa-0aca-4353-afea-47fe4e63b6f6) | [![Report](https://github.com/user-attachments/assets/015974bb-86ed-4380-b6d0-e2d833becf1d?raw=true)](https://github.com/user-attachments/assets/015974bb-86ed-4380-b6d0-e2d833becf1d) |

<details>
<summary>컴포넌트 자세히 보기</summary> <br/>클릭하면 원본 해상도로 확대됩니다.
  
| 컴포넌트 1 | 컴포넌트 2 | 컴포넌트 3 |
|:---:|:---:|:---:|
| [![img1](https://github.com/user-attachments/assets/d0759a17-f49e-40c9-8db7-c496a19db8aa?raw=true)](https://github.com/user-attachments/assets/d0759a17-f49e-40c9-8db7-c496a19db8aa) | [![img2](https://github.com/user-attachments/assets/ef53d693-a40f-4228-a7ab-7a638e6affa8?raw=true)](https://github.com/user-attachments/assets/ef53d693-a40f-4228-a7ab-7a638e6affa8) | [![img3](https://github.com/user-attachments/assets/a3ddabd7-752b-4726-9cc3-2a428e395644?raw=true)](https://github.com/user-attachments/assets/a3ddabd7-752b-4726-9cc3-2a428e395644) |
| **컴포넌트 4** | **컴포넌트 5** | **컴포넌트 6** |
| [![img4](https://github.com/user-attachments/assets/0ea35f15-569a-48d0-8119-9f12c3ace596?raw=true)](https://github.com/user-attachments/assets/0ea35f15-569a-48d0-8119-9f12c3ace596) | [![img5](https://github.com/user-attachments/assets/f682c050-388e-4192-b9b5-fabaa8783c2e?raw=true)](https://github.com/user-attachments/assets/f682c050-388e-4192-b9b5-fabaa8783c2e) | [![img6](https://github.com/user-attachments/assets/e17d5e05-51f3-4439-a626-301313bae503?raw=true)](https://github.com/user-attachments/assets/e17d5e05-51f3-4439-a626-301313bae503) |
| **컴포넌트 7** | **컴포넌트 8** | **컴포넌트 9** |
| [![img7](https://github.com/user-attachments/assets/15f3e8ef-593d-41db-9d1a-f5e01077f46c?raw=true)](https://github.com/user-attachments/assets/15f3e8ef-593d-41db-9d1a-f5e01077f46c) | [![img8](https://github.com/user-attachments/assets/1b2b7fb9-06cf-4fec-9ea4-a0437d546e2a?raw=true)](https://github.com/user-attachments/assets/1b2b7fb9-06cf-4fec-9ea4-a0437d546e2a) | [![img9](https://github.com/user-attachments/assets/6a1d14cc-0578-423d-953b-19399e996782?raw=true)](https://github.com/user-attachments/assets/6a1d14cc-0578-423d-953b-19399e996782) |
| **컴포넌트 10** | **컴포넌트 11** | **컴포넌트 12** |
| [![img10](https://github.com/user-attachments/assets/2d0216a4-e75b-49fa-b779-d3a936a6d6fe?raw=true)](https://github.com/user-attachments/assets/2d0216a4-e75b-49fa-b779-d3a936a6d6fe) | [![img11](https://github.com/user-attachments/assets/bd6dd864-2fe1-4395-9647-229ca294e936?raw=true)](https://github.com/user-attachments/assets/bd6dd864-2fe1-4395-9647-229ca294e936) | [![img12](https://github.com/user-attachments/assets/407a9808-5a3e-4882-8b8c-ae5ced09edf3?raw=true)](https://github.com/user-attachments/assets/407a9808-5a3e-4882-8b8c-ae5ced09edf3) |
| **컴포넌트 13** | **컴포넌트 14** |  |
| [![img13](https://github.com/user-attachments/assets/a0af75d5-96f1-4593-9b40-a37e19669b9c?raw=true)](https://github.com/user-attachments/assets/a0af75d5-96f1-4593-9b40-a37e19669b9c) | [![img14](https://github.com/user-attachments/assets/e39dcf22-5c31-4566-9748-2ced79cb2eb6?raw=true)](https://github.com/user-attachments/assets/e39dcf22-5c31-4566-9748-2ced79cb2eb6) |  |

</details>

## 포스터

<details>
<summary>포스터 보기</summary>
<div align="center">
<img src="https://github.com/user-attachments/assets/2982378f-6e4d-42e7-be14-10f9972d5573" width="80%" alt="KlickLab Poster" />
</div>
</details>

## 아키텍처

<details>
<summary>아키텍처 다이어그램 보기</summary>
<div align="center">
<img src="https://github.com/user-attachments/assets/e1b65435-379c-494c-a612-03a6ae95a116" width="80%" alt="KlickLab Architecture" />
</div>
</details>

<details>
<summary>아키텍처 관련 글 모음</summary>

### Architectural Improvements 시리즈

1. [Architectural Improvements 1](https://velog.io/@qnfrma1997/Architectural-Improvements-1)
2. [Architectural Improvements 2](https://velog.io/@qnfrma1997/Architectural-Improvements-2)
3. [Architectural Improvements 3](https://velog.io/@qnfrma1997/Architectural-Improvements-3)
4. [Architectural Improvements 4](https://velog.io/@qnfrma1997/Architectural-Improvements4)

### DeepDive 시리즈

- [DeepDive: GC Triggered Stop-the-World](https://velog.io/@qnfrma1997/DeepDive-GC-Triggered-Stop-the-World)
- [DeepDive: Many Over Mighty](https://velog.io/@qnfrma1997/DeepDive-Many-Over-Mighty)

</details>

## 데이터 흐름도

<details>
<summary>데이터 흐름도 보기</summary>
<div align="center">
![Infra Architecture for KlickLab](https://github.com/user-attachments/assets/593b10fd-656f-4b7a-aa1f-e179306dcc1c)
</div>
</details>

## 기술 스택

### Frontend
![React](https://img.shields.io/badge/React-20232A?style=flat&logo=react&logoColor=61DAFB)
![TypeScript](https://img.shields.io/badge/TypeScript-3178C6?style=flat&logo=typescript&logoColor=white)
![Vite](https://img.shields.io/badge/Vite-646CFF?style=flat&logo=vite&logoColor=white)
![TailwindCSS](https://img.shields.io/badge/TailwindCSS-06B6D4?style=flat&logo=tailwindcss&logoColor=white)
![React Router](https://img.shields.io/badge/React--Router-CA4245?style=flat&logo=reactrouter&logoColor=white)
![Zustand](https://img.shields.io/badge/Zustand-000000?style=flat&logo=zustand&logoColor=white)
![Recharts](https://img.shields.io/badge/Recharts-FF4A00?style=flat&logo=chartdotjs&logoColor=white)
![HTML5](https://img.shields.io/badge/HTML5-E34F26?style=flat&logo=html5&logoColor=white)
![CSS3](https://img.shields.io/badge/CSS3-1572B6?style=flat&logo=css&logoColor=white)

### Backend
![Java](https://img.shields.io/badge/Java_21-007396?style=flat&logo=openjdk&logoColor=white)
![Spring Boot](https://img.shields.io/badge/Spring_Boot-6DB33F?style=flat&logo=springboot&logoColor=white)
![Spring Security](https://img.shields.io/badge/Spring_Security-6DB33F?style=flat&logo=springsecurity&logoColor=white)
![Gradle](https://img.shields.io/badge/Gradle-02303A?style=flat&logo=gradle&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-4169E1?style=flat&logo=postgresql&logoColor=white)
![pgvector](https://img.shields.io/badge/pgvector-4169E1?style=flat&logo=postgresql&logoColor=white)
![Flyway](https://img.shields.io/badge/Flyway-CC0200?style=flat&logo=flyway&logoColor=white)
![JWT](https://img.shields.io/badge/JWT-000000?style=flat&logo=jsonwebtokens&logoColor=white)
![Micrometer Prometheus](https://img.shields.io/badge/Micrometer--Prometheus-E6522C?style=flat&logo=prometheus&logoColor=white)

## 설치 및 실행

### 1. 레포지토리 클론

```bash
git clone https://github.com/Eatventory/KlickLab.git
cd klickLab
```

### 2. 데이터베이스 실행 (PostgreSQL 17 + pgvector)

```bash
cd backend
docker compose up -d          # 5432 포트가 사용 중이면: DB_PORT=5433 docker compose up -d
```

스키마는 애플리케이션 기동 시 Flyway(`src/main/resources/db/migration`)가 자동으로 생성합니다.

### 3. 환경변수 설정
`backend/.env.example`을 복사해 `backend/.env`를 만들고 값을 채워주세요. (`.env`는 Spring Boot가 자동으로 읽습니다)
- `JWT_SECRET`, `JWT_REFRESH_SECRET`는 HS256 서명을 위해 **32바이트 이상**이어야 합니다.

```bash
DB_URL=jdbc:postgresql://localhost:5432/klicklab
DB_USERNAME=klicklab
DB_PASSWORD=klicklab
JWT_SECRET=
JWT_REFRESH_SECRET=
AUTH_AUTO_APPROVE=false
```

### 4. 백엔드 실행 (JDK 17 이상)

Gradle 실행에는 JDK 17 이상이 필요하며, 프로젝트가 요구하는 JDK 21은 없으면 첫 빌드 때 자동으로 내려받습니다.

```bash
cd backend
./gradlew bootRun             # API: http://localhost:4000, 메트릭: http://localhost:9091/metrics
./gradlew test                # Testcontainers 통합 테스트 (Docker 필요)
```

#### 집계 Job (Spring Batch)

`bootRun` 중에는 `minutes_*` → `hourly_*` → `daily_*` → `weekly_*` 집계 테이블이 자동으로 채워집니다. (매 10분 / 정각 / 매일 00:10 / 매주 월요일 00:30)
특정 구간만 다시 집계하려면 웹 서버 없이 한 번 실행하고 종료하는 `--aggregate` 옵션을 사용합니다. 서버가 실행 중이어도 함께 쓸 수 있습니다.

```bash
./gradlew bootRun --args="--aggregate=minutes --at=2026-11-09T14:30"   # 10분 (생략 시 직전 구간)
./gradlew bootRun --args="--aggregate=hourly --at=2026-11-09T14"
./gradlew bootRun --args="--aggregate=daily --at=2026-11-09"
./gradlew bootRun --args="--aggregate=weekly --at=2026-11-02"           # 해당 날짜부터 7일
./gradlew bootRun --args="--aggregate=backfill --from=2026-11-01 --to=2026-11-09"  # 기간 전체 재집계 (생략 시 어제)
```

### 5. 분석 에이전트 서버 실행 (Python 3.12, uv)

자연어 질문을 SQL로 바꿔 조회하는 분석 에이전트(FastAPI)입니다. 대시보드의 **분석 에이전트** 탭을 쓰려면 필요하며, DB를 공유하므로 백엔드(4번)를 한 번 실행해 마이그레이션(V4, V5)이 적용된 뒤에 띄웁니다.

```bash
# 에이전트 전용 DB 롤에 로그인 허용 (최초 1회)
docker exec -it klicklab-postgres psql -U klicklab -d klicklab   -c "ALTER ROLE klicklab_agent_ro LOGIN PASSWORD 'agent_ro'"   -c "ALTER ROLE klicklab_agent LOGIN PASSWORD 'agent'"

cd agent
cp .env.example .env          # JWT_SECRET(backend/.env와 동일), GROQ_API_KEY 등을 채움. DB_PORT는 실제 DB 포트에 맞춤
uv sync
uv run uvicorn app.main:app --port 8000   # http://localhost:8000/agent/health
```

- 프론트엔드 개발 서버가 `/agent`를 `localhost:8000`으로 프록시합니다.
- RAG 모드(`KNOWLEDGE_MODE=rag`)를 쓰려면 먼저 `uv run python -m app.knowledge.indexer`로 지식 베이스를 적재합니다.

```powershell
cd agent
.venv\Scripts\python -m uvicorn app.main:app --port 8000
```

### 6. 프론트엔드 실행

```bash
cd frontend
npm install
npm run dev
```
