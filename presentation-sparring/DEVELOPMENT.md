# profAIssor 개발 문서 (DEVELOPMENT.md)

> 유지보수·온보딩용 개발 문서. 아키텍처, 개발 히스토리, 트러블슈팅, 유지보수 가이드, 알려진 한계를 정리한다.
> 로드맵/작업 규칙은 [`PLAN.md`](./PLAN.md), 사용법/실행법은 [`README.md`](./README.md) 참고.

---

## 1. 개요

발표/구술시험을 앞둔 학생이 **발표 후 질의응답을 실전처럼 연습**하는 웹앱.

- 흐름: **발표 자료 등록(대본+슬라이드) → 페르소나가 압박 질문 → 답변 평가 + 꼬리질문 → 종합 피드백 리포트 → 히스토리 추이**
- 대상: 전공 발표/구술시험 준비생 (한국어 기본, 영어 발표 연습 모드 개발 중)
- 한 줄 정의: "여러 관점의 까다로운 청중을 동시에 상대하는 발표 질의응답 스파링 도구."

---

## 2. 기술 스택 & 핵심 원칙

| 영역 | 스택 |
|------|------|
| 프론트엔드 | React 18 + TypeScript + Vite, Tailwind, Recharts(히스토리 차트), lucide-react |
| 백엔드 | Python + FastAPI + uvicorn, Pydantic v2 |
| LLM | OpenAI / Gemini / mock (env로 선택, `llm_client` 뒤로 추상화) |
| 자료 추출 | python-pptx(PPTX), pypdf(PDF) |
| 음성 | 브라우저 Web Speech API(STT) + Web Audio API(AnalyserNode, 음성 지표) |
| 배포 | 백엔드 Render, 프론트 Netlify |

**끝까지 지켜야 할 아키텍처 원칙 (PLAN.md에서):**
1. **백엔드 완전 무상태(stateless)** — DB/세션 없음. 요청마다 `프롬프트 빌드 → LLM 호출 → JSON 파싱`. 모든 컨텍스트(대본/슬라이드/질의응답 기록)는 요청 본문으로 매번 전달된다.
2. **프론트 상태는 `useState`만** — 라우터/글로벌 스토어 없음. 화면 전환은 `App.tsx`의 `stage` 상태로.
3. **영속성은 브라우저 localStorage** — 히스토리 세션 저장. (Render 무료티어는 영속 디스크가 없고 앱에 인증이 없어 DB 대신 선택)
4. **LLM은 `llm_client.chat()/chat_json()` 뒤로 완전 추상화** — provider 추가/교체는 이 파일에 국한.

---

## 3. 디렉터리 구조

```
presentation-sparring/
├── backend/                     # FastAPI (무상태)
│   ├── main.py                  # 앱 부트스트랩 + CORS + 라우터 등록 + /api/health
│   ├── routers/                 # 얇은 HTTP 계층 (요청 검증 → 서비스 호출)
│   │   ├── slides.py            #   POST /api/slides/extract  (PPTX/PDF 업로드→슬라이드 텍스트)
│   │   ├── personas.py          #   GET  /api/personas        (공개 페르소나 목록)
│   │   ├── questions.py         #   POST /api/questions       (최초 질문 생성)
│   │   ├── evaluate.py          #   POST /api/evaluate        (답변 평가 + 꼬리질문)
│   │   ├── followup.py          #   POST /api/followup
│   │   └── report.py            #   POST /api/report          (종합 리포트)
│   ├── services/                # 도메인 로직 (프롬프트 빌드·LLM 호출·응답 검증)
│   │   ├── question_service.py
│   │   ├── evaluation_service.py
│   │   └── report_service.py
│   ├── core/prompt_rules.py     # 공통 프롬프트 규칙 조각
│   ├── prompts.py               # 질문/평가 프롬프트 빌더
│   ├── report_prompt.py         # 리포트/코칭 프롬프트 빌더
│   ├── personas.py              # 페르소나 정의(단일 원본) + 전공계열 힌트(FIELD_HINTS)
│   ├── material_context.py      # 대본·슬라이드 맥락 처리 헬퍼
│   ├── llm_client.py            # provider 추상화(openai/gemini/mock), 모델 config, usage 로그
│   ├── ppt_extract.py           # PPTX → Slide[] (python-pptx)
│   ├── pdf_extract.py           # PDF 1페이지 = Slide 1개 (pypdf)
│   ├── speech_metrics.py        # 답변 음성 지표 집계(WPM/침묵/필러 요약)
│   └── schemas.py               # Pydantic 요청/응답 모델
└── frontend/src/
    ├── App.tsx                  # stage(setup→spar→report / history) 라우팅 + 전역 상태
    ├── api.ts                   # 백엔드 호출 래퍼 (BASE = VITE_API_BASE)
    ├── components/
    │   ├── SetupScreen.tsx      # 대본/슬라이드/페르소나/난이도/계열 입력, 예상시간
    │   ├── SlideInput.tsx       # 슬라이드 수동 편집 + PPTX/PDF 업로드
    │   ├── SparScreen.tsx       # 질의응답 루프(질문·답변·평가·꼬리질문·STT·음성지표)
    │   ├── ReportScreen.tsx     # 종합 리포트
    │   └── HistoryScreen.tsx    # 세션 목록 + 추이 차트 + 삭제
    ├── hooks/
    │   ├── useSpeechRecognition.ts  # Web Speech API STT 래퍼(lang, 재시작, 용어 부스팅)
    │   └── useMicMetrics.ts         # Web Audio RMS 프레임 수집(음성 지표 원천)
    └── lib/
        ├── coverage.ts          # 슬라이드 커버리지율 계산
        ├── sessionStore.ts      # localStorage 세션 저장/조회/삭제
        ├── timing.ts            # 발표 예상 시간(어절/분), 분·초 포맷
        ├── speechMetrics.ts     # 답변별 음성 지표 계산(WPM/침묵/필러)
        ├── termCorrection.ts    # STT 전공용어 보정(편집거리 + 한국어 음성 별칭)
        └── browserSupport.ts    # 음성 기능 지원 브라우저 판정(데스크톱 Chrome)
```

---

## 4. 앱 흐름 (End-to-End)

```
[SetupScreen]
  대본/슬라이드 입력 (PPTX·PDF 업로드 가능) + 페르소나·난이도·계열 선택
        │  handleStart → stage='spar'
        ▼
[SparScreen]  (선택한 페르소나마다 반복)
  POST /api/questions   → 최초 질문 (persona 관점 + 난이도 + 자료 근거)
  사용자 답변 (타이핑 또는 🎙 STT)
  POST /api/evaluate    → 평가(verdict/strengths/gaps/rubric) + 다음 동작
        ├ 꼬리질문(ask_followup) → 같은 쟁점 심화 (최대 maxTurns회)
        ├ 답변불가(unknown) → 같은 주제 쉬운 재질문 1회
        └ 종료 → 다음 페르소나 / 전체 종료
        │  onFinish(transcript) → stage='report'
        ▼
[ReportScreen]
  POST /api/report      → 종합 요약(내용·전달·대응) + 슬라이드 커버리지 +
                          답변별 상세 교정 + 대본 수정 제안 + (음성 지표 요약)
  saveSession() → localStorage 저장
        │  히스토리 진입
        ▼
[HistoryScreen]  세션 목록 + 추이 차트(커버리지·예상시간) + 개별/전체 삭제
```

> **중요(설계 결정):** 리포트는 **스파링을 완료해야만** 도달한다. "질문 없이 결과만 보기"는 답변별 상세 교정·'대응' 항목이 비어 반쪽짜리 리포트가 나오는 문제로 제거됨(PR #24).

---

## 5. LLM Provider 추상화

`backend/llm_client.py`가 유일한 LLM 접점.

- `PROVIDER = LLM_PROVIDER` (openai | gemini | mock, 기본 mock)
- `_MODEL_CONFIG`: provider별 모델(`OPENAI_MODEL` 기본 gpt-4o-mini, `GEMINI_MODEL` 기본 gemini-3.1-flash-lite)
- `chat()` / `chat_json()`: 공통 인터페이스. `chat_json`은 JSON 강제(`response_format`) 후 파싱.
- `mock`: API 키 없이 캔드 응답으로 전체 흐름 데모 가능(질문 유형·꼬리질문 흐름까지 흉내). **단, 영어/실전 품질 검증은 불가.**
- usage 로그: `LLM_USAGE_LOG`(기본 on)일 때 토큰 사용량을 INFO 로그로 남김.

**모델 교체 = 코드 변경 없이 env 하나** (`OPENAI_MODEL` 등). 자세한 건 §10 참고.

---

## 6. 데이터 모델 (핵심)

| 모델 | 위치 | 요지 |
|------|------|------|
| `Slide` | backend/schemas, frontend/types | `{ index, text }`. PPTX 도형/표 텍스트 또는 PDF 페이지 텍스트 |
| `TranscriptTurn` | 동상 | 한 질의응답 턴: `question, answer, verdict, strengths, gaps, rubric, question_type, answer_status, supplement, related_slides` (+음성 지표) |
| `Report` | 동상 | `content/delivery/response_feedback, slide_coverage[], revisions[], answer_structure_tip, word_count, filler_count, (speech_summary)` |
| `SlideCoverage` | 동상 | `{ index, covered, missing_point }`. 미달 시 누락 유형(수치/용어) 구체화 |
| `SessionRecord` | frontend/lib/sessionStore | localStorage 1건: `{ id, completedAt, field, personaIds, report, estMinutes }` |

### 리포트 섹션별 입력 요구사항 (설계 기준)

| 리포트 섹션 | 필요한 입력 |
|------|------|
| 답변별 상세 교정 | 스파링(질의응답 기록) |
| 슬라이드 커버리지 | 발표 대본 + 슬라이드 (둘 다) |
| 대본 수정 제안 | 발표 대본 |
| 종합요약 — 내용·전달 | 발표 대본 |
| 종합요약 — 대응 | 스파링 |

> 입력이 일부만 있을 때(예: 대본 없이 슬라이드만)의 섹션별 graceful degradation은 아직 정식 규칙으로 구현되지 않음 — §12 참고.

---

## 7. 슬라이드 커버리지 (킬러 기능) 동작

`report_service`/`prompts`의 LLM 판정을 우선하되, LLM이 판정하지 못한 슬라이드는 **결정론적 폴백**(`_fallback_coverage`)으로 처리:

- 슬라이드 키워드가 대본에 충분히 등장하면 covered.
- 미달 시 누락 항목을 **수치(숫자/퍼센트) vs 용어**로 구분해 구체적으로 표기 — 예: `핵심 수치(45%)가 대본에서 언급되지 않았습니다` / `핵심 용어(정규화)가 …` (PR #17).
- 노이즈 제거: 페이지번호 등 순수 숫자·앞자리 0(예 `02`) 토큰 제외, 여러 슬라이드에 반복되는 boilerplate(러닝헤더) 제외, 연도(1900~2099)는 핵심 수치 후순위.

---

## 8. 자료 추출 (PPTX / PDF)

- 엔드포인트: `POST /api/slides/extract` (multipart). 확장자로 분기.
- **PPTX**(`ppt_extract.py`): 슬라이드 도형 text_frame + 표 셀 텍스트를 슬라이드당 하나로 합침.
- **PDF**(`pdf_extract.py`, PR #18): **PDF 1페이지 = Slide 1개**. `pypdf`로 페이지 텍스트 추출. 텍스트가 없는 페이지(스캔/이미지 슬라이드)는 업로드를 실패시키지 않고 **빈 슬라이드**로 두어 사용자가 수동 편집.
- 검증: 구버전 `.ppt` 400(안내), 미지원 확장자 400, 20MB 상한, content-type은 확장자별 허용셋(브라우저 변형 대비 `octet-stream` 허용).
- **이미지·도표만 있는 슬라이드는 설계상 범위 밖**(텍스트/전달 평가 도구). 비전 LLM 추가 해석은 비용·복잡도 대비 효과가 낮아 보류.

---

## 9. 환경변수

**백엔드 (`backend/.env`, 커밋 금지):**

| 변수 | 기본 | 설명 |
|------|------|------|
| `LLM_PROVIDER` | `mock` | `openai` \| `gemini` \| `mock` |
| `OPENAI_API_KEY` | — | openai 사용 시 |
| `OPENAI_MODEL` | `gpt-4o-mini` | openai 모델 |
| `GEMINI_API_KEY` | — | gemini 사용 시 |
| `GEMINI_MODEL` | `gemini-3.1-flash-lite` | gemini 모델 |
| `LLM_USAGE_LOG` | `true` | 토큰 사용량 로그 |
| `FRONTEND_ORIGIN` | `http://localhost:5173` | CORS 허용 origin |
| `EXTRA_ORIGINS` | — | 쉼표 구분 추가 origin |

**프론트 (`frontend/.env`):**

| 변수 | 값 | 설명 |
|------|------|------|
| `VITE_API_BASE` | `http://localhost:8000` | 백엔드 주소 (로컬) |

> Netlify/Render 배포에서는 CORS가 `*.netlify.app` / `*.onrender.com` 정규식으로 허용됨.

---

## 10. 로컬 실행 & 배포

### 로컬
```bash
# 백엔드 (포트 8000) — backend 디렉터리 안에서 실행해야 main:app import 됨
cd presentation-sparring/backend
pip install -r requirements.txt
cp .env.example .env            # 기본 mock, 키 없이 데모 가능
uvicorn main:app --reload --port 8000

# 프론트 (포트 5173)
cd presentation-sparring/frontend
npm install
npm run dev
```
- 프론트 `.env`의 `VITE_API_BASE`는 **반드시 8000**을 가리켜야 함(§13-1).
- 음성 기능 확인은 **데스크톱 Chrome + 마이크 권한** 필요.

### 배포
- **백엔드**: Render. `LLM_PROVIDER`, `OPENAI_API_KEY` 등은 대시보드 env로 등록(`render.yaml`의 `sync:false`). 모델 교체도 대시보드 env만 바꾸면 재배포 불필요.
- **프론트**: Netlify 정적 빌드. `VITE_API_BASE`를 배포된 백엔드 URL로 설정.

---

## 11. 개발 히스토리 (주요 마일스톤)

> 팀 규칙: `main` 직접 커밋 금지, `step/*` 또는 `feat/*`/`fix/*` 브랜치 → PR → 리뷰 후 머지.

**초기(예선 MVP → 본선 로드맵):** 스파링 MVP, STT 추가, UI 리스킨, Render/Netlify 배포, PLAN.md 로드맵.

**Phase 0~4 (팀):**
- OpenAI 연동 + provider별 단일 모델 구조 정리
- 난이도(쉬움/보통/어려움) · 최대 꼬리질문 수(0~3) · rubric
- 전공계열별 페르소나 힌트(공학/인문사회/자연)
- 스파링 흐름 고도화(1-4): 질문 유형(근거/반례/적용/정의), 자료 흐름 분석, `root_question` 유지, 답변불가 재분류 → 쉬운 재질문, 리포트를 관찰→영향→수정행동→예시 구조로
- STT 전공용어 보정, 마이크 권한 UX
- PPT 추출 + 업로드 프론트 연동
- 세션 저장(localStorage) + 히스토리 화면 + 추이 그래프
- **도메인 모듈 리팩터링**: `main.py` 단일 파일 → `routers/` + `services/` 분리, 페르소나 백엔드 단일 원본화, 음성 리소스 누수 수정

**최근 세션 PR (본 문서 작성 세션):**
| PR | 내용 |
|----|------|
| #17 | 슬라이드 커버리지 누락 항목을 수치/용어로 구체화(`_figures`/`_figure_rank`) |
| #18 | 발표 자료 **PDF 업로드** 지원(`pdf_extract.py`, pypdf) |
| #19 | 스파링 UX 3종: (질문 없이 결과보기)·발표 예상시간(`timing.ts`)·Enter 전송·답변창 포커스 유지 |
| #20 | 히스토리 **정리 기능**(개별 삭제 `deleteSession` + 전체 삭제) |
| #24 | **리포트를 스파링 완료 후에만** 볼 수 있게(#19의 "질문 없이 보기" 되돌림) |

**진행 중(미머지) — `add-english-speech` 브랜치:**
- **영어 질의응답 모드**(ko/en 토글) + **음성 비언어 지표**(답변 속도 WPM·침묵·필러). 상태와 한계는 §12·§14 참고.

---

## 12. 트러블슈팅 (실제 겪은 이슈)

| 증상 | 원인 | 해결 |
|------|------|------|
| 업로드/질문 시 `404 (Not Found)`가 `localhost:5173/api/...`로 감 | 프론트 `.env`의 `VITE_API_BASE`가 비었거나 5173을 가리킴 → 상대경로로 자기 자신 호출 | `VITE_API_BASE=http://localhost:8000` 설정 후 **Vite 재시작**(env는 시작 시 1회 로드) |
| `uvicorn ... Could not import module "main"` | 프로젝트 루트/`presentation-sparring`에서 실행 → `main.py`가 없는 위치 | 반드시 `backend/` 디렉터리에서 `uvicorn main:app` 실행 |
| Enter로 답변 제출 후 매번 입력창을 다시 클릭해야 함 | 제출 중 `busy`로 textarea가 `disabled`되며 포커스 상실, 다음 질문에 자동 복귀 안 함 | `answerInputRef` + `[busy, question]` 변화 시 focus effect (PR #19) |
| 예상 발표 시간이 "0.2분"처럼 비직관적, 히스토리 차트 초록선이 바닥에 깔림 | 소수 분 단위 표기 + 분 단위라 다른 축(커버리지%)에 눌림 | `formatMinutes`로 "약 N분 M초" 통일, 차트는 초 단위 (PR #19) |
| 슬라이드 커버리지 오탐(페이지번호·반복 헤더가 "핵심 키워드"로) | 순수 숫자/boilerplate 토큰이 키워드로 잡힘 | 숫자·앞자리 0·문서빈도 높은 토큰 제외 (PR #17) |
| Enter가 한글 입력 중 오작동(조합 확정 시 전송) | IME 조합 중 Enter를 전송으로 처리 | `event.nativeEvent.isComposing` 가드 (PR #19) |
| (개발환경) `pypdf` import 시 `_cffi_backend` 오류 | 시스템 `cryptography` 깨짐 | 환경 이슈. `pip install --upgrade cffi cryptography`. 코드 문제 아님 |

---

## 13. 유지보수 가이드

### LLM Provider 추가/교체
- **교체**: `backend/.env`(로컬) 또는 Render env의 `LLM_PROVIDER`/`OPENAI_MODEL` 변경. 코드 변경 불필요.
- **추가**: `llm_client.py`에 `_call_<provider>()` + `_MODEL_CONFIG` 항목 + dispatch만 추가. 나머지 코드는 `chat()/chat_json()`만 쓰므로 영향 없음.

### 모델 업그레이드 (품질 이슈 시)
현재 기본값(`gpt-4o-mini`, `gemini-3.1-flash-lite`)은 각 provider **최하위 티어**라 품질이 아쉬울 수 있음.
- **드롭인(코드 변경 없음)**: `OPENAI_MODEL=gpt-4.1-mini` 또는 `gpt-4o` — `temperature`/`max_tokens`/`json_object` 그대로 호환.
- **GPT-5 계열**(`gpt-5-mini`/`gpt-5`, 최상급 추론): `_call_openai`가 `temperature`·`max_tokens`를 보내는데 GPT-5 계열은 커스텀 `temperature`를 막고 `max_completion_tokens`를 요구할 수 있음 → 400 나면 그 2가지를 조정해야 함.

### 페르소나 추가/수정
- `backend/personas.py`가 **단일 원본**. 프론트는 `GET /api/personas`로 목록을 받아 렌더(`personas.ts`는 캐시).
- 각 페르소나: `name/blurb/system`(질문 관점) + 질문 유형 우선순위.

### 프롬프트 수정
- 질문/평가: `prompts.py` + `core/prompt_rules.py`. 리포트/코칭: `report_prompt.py`.
- 프롬프트는 무상태 원칙상 매 요청 빌드됨. 난이도·질문유형·계열 힌트가 조합됨.

### 프론트 상태/화면 추가
- 화면 전환은 `App.tsx`의 `stage`. 새 화면은 `Stage` 유니온에 추가 후 조건부 렌더.
- 세션 영속성은 `sessionStore`(localStorage). 스키마 변경 시 `STORAGE_KEY` 버전(`...v1`) 고려.

### 음성/브라우저 지원
- 음성(STT·지표)은 `browserSupport.ts`로 **데스크톱 Chrome만** 활성화, 그 외에는 텍스트 입력으로 폴백. 새 기능이 Web Speech/Web Audio에 의존하면 반드시 이 게이트와 폴백을 지킬 것.

---

## 14. 알려진 한계 & 기술 부채

### 음성 비언어 지표 (`add-english-speech`)
- **필러 카운트는 사실상 하한선(≈0)**: Web Speech `final` 결과가 "음/어/um/uh"를 대부분 버림. UI에 "최소 N회/인식 하한선"으로 정직하게 표기하고 추이 차트에서 제외함. 복구 로직(~100줄) 대비 효과는 낮음.
- **음량 변화 지표가 소스에서 훼손**: 마이크를 `autoGainControl:true`로 잡아 AGC가 볼륨을 평탄화 → `volume_variation`이 사실상 무의미(그리고 현재 화면 미표시).
- **WPM은 "조음 시간 기준"으로 분모(발화 시간)는 신뢰 가능하나 분자(단어 수)가 STT 결과**라 인식률에 영향받음 → 절대값보다 경향으로 해석.
- **측정만 하고 미표시되는 필드**: `volume_variation`, `average_initial_latency_ms`, `input_mode` — 노출하거나 제거 필요(죽은 배선).
- **잔재 코드**: `report_service`의 옛 `_FILLER_PATTERN`/`_count_fillers` 미사용.
- 잘된 점: 타이핑 답변은 가짜 0 대신 음성 지표 생략, 나눗셈/신뢰도 방어 견고, 데스크톱 Chrome 폴백 명시.

### 영어 모드 (`add-english-speech`)
- **입력 경로(질문 생성·STT `en-US`)는 영어로 관통하지만, 피드백·리포트·상당수 UI가 한국어로 남음** → 현재는 "영어로 묻고 한국어로 답해주는" 형태. 대상 사용자가 "한국 학생의 영어 발표 연습"이면 한국어 피드백은 정당하나, 영어권 단독 사용자는 사용 불가.
- **영어 질문에 한글 누출 검증 없음**: 리포트 쪽은 한글 섞이면 재생성하지만 질문 생성엔 동일 가드 없음 → 약한 모델일수록 한국어가 샐 수 있음.
- 회복 팁 안내문이 반쪽만 번역, 영어 모드에서도 "예시 데이터"가 한국어, 페르소나 이름/설명 한국어, `build_speech_coaching_prompt(language)` 파라미터가 미사용(죽은 인자) 등 정리 필요.

### 공통
- 리포트 섹션별 부분 입력(대본만/슬라이드만) graceful degradation은 미구현. 대본 없이 커버리지를 돌리면 전부 "미달"로 잡히는 등 왜곡 가능 → §6 표를 규칙으로 구현하는 것이 과제.

---

## 15. 다음 작업 후보 (우선순위 감)
1. `add-english-speech` 정리 후 머지: 질문 한글 누출 검증, 회복 팁 번역, 죽은 지표/코드 제거.
2. 모델 업그레이드(env) — 질문·평가 품질 체감 개선.
3. 리포트 섹션별 입력 요구 규칙화(§6) — 부분 입력 시 섹션 자동 표시/숨김.
4. 모바일 UI 정리(PLAN.md Phase 5).
