# profAIssor 본선(최종 제출) 구현 로드맵

## 배경

예선 신청서(신청서.hwp)와 실제 코드를 대조한 결과 두 가지가 확인됐다.

1. **신청서-코드 불일치**: 신청서는 "OpenAI API(GPT-4o-mini)"를 핵심 AI 활용 방식으로 명시했지만, 실제 `backend/llm_client.py`에는 OpenAI 프로바이더가 없다(anthropic/gemini/groq/mock만 존재). 게다가 프로덕션(`render.yaml`)은 `LLM_PROVIDER=mock`이라 배포된 앱은 지금 캔드 응답만 준다.
2. **신청서 자체의 "멘토링 기간 고도화 계획" 6개 항목이 전부 미착수** — PPT 자동추출, 스파링 루프 고도화(난이도/꼬리질문 횟수), STT 용어보정, 전공계열별 페르소나, 세션 저장+그래프, 모바일/마이크 UX.

이 문서는 이 6개 항목 + OpenAI 연동을 본선 제출까지 구현하기 위한 로드맵이다. 마감 압박은 없으므로 임팩트/의존성 순서로 진행한다.

## 현재 아키텍처 제약 (구현 시 계속 지킬 것)

- 백엔드는 FastAPI, **완전 무상태**(stateless) — DB/세션 없음, 요청마다 프롬프트 빌드→LLM 호출→JSON 파싱.
- 프론트는 React 상태(`useState`)만으로 구동, 라우터/글로벌 스토어/영속성 없음.
- `main.py`의 `_fallback_coverage`가 슬라이드 커버리지의 결정론적 폴백을 이미 제공 — 이 패턴 재사용.
- LLM 프로바이더는 `llm_client.py`의 `chat()`/`chat_json()` 뒤에 완전히 추상화됨 — 새 프로바이더 추가는 이 파일에 국한.

## 진행 방식 (릴레이 구현 가이드)

- **Phase**는 우선순위/의존성 순서를 나타내는 큰 단위이고, 실제 작업 단위는 그 아래 **Step**이다.
- Step 하나 = 건드리는 파일이 1~3개로 한정 = 완료 기준(DoD)이 명확 = 커밋/PR 하나로 끊기는 핸드오프 지점.
- 같은 Phase 안에서도 "의존성 없음"이라 표시된 Step끼리는 다른 사람이 동시에 진행 가능(파일이 겹치지 않음).
- Step을 넘길 때는: ① DoD 체크 ② 확인 방법대로 직접 동작 확인 ③ 커밋 메시지에 Step 번호 표기, 순서로 핸드오프한다.
- 아래 체크리스트에 완료된 Step은 `[x]`로 표시해 진행 상황을 공유한다.

## 협업 규칙

1. **브랜치 → PR → 머지**: `main`에 직접 커밋하지 않는다. 작업은 항상 별도 브랜치에서 진행하고, 완료되면 PR을 만들어 머지한다. `main`은 언제나 정상 동작하는 상태를 유지한다(빌드/실행 안 되는 상태로 머지 금지).
2. **브랜치 이름 = Step ID**: `step/<Step번호>-<짧은설명>` 형식으로 만든다 (예: `step/1-1-difficulty-backend`, `step/3-1-ppt-extract`). PLAN.md의 Step ID와 1:1로 맞춰서, 브랜치 목록만 봐도 누가 어떤 Step을 진행 중인지 알 수 있게 한다.
3. **작업 선점 표시**: Step을 시작하기 전에 하단 체크리스트에 담당자를 적어둔다 (예: `- [ ] 1-1: 난이도/최대턴수/rubric (담당: 수진)`). 같은 Step을 동시에 두 명이 건드리는 것을 방지하기 위함.
4. **커밋 메시지에 Step 번호 포함**: 예) `[1-1] 난이도/최대턴수 스키마 추가`. 나중에 어떤 Step이 어떤 커밋에서 끝났는지 추적하기 쉽게 한다.
5. **PR 올리기 전 자체 확인**: 해당 Step의 "완료 기준"과 "확인 방법"을 PR 작성자가 직접 실행해보고, 결과(curl 출력, 스크린샷 등)를 PR 설명에 짧게 남긴다.
6. **리뷰 후 머지 원칙**: 3인 팀이므로 최소 1인의 승인을 받고 머지하는 것을 기본으로 한다. 다만 긴급하거나 리뷰어가 자리를 비운 경우 self-merge를 허용하되, 머지 후 팀 채널에 공유한다.
7. **의존성 있는 Step은 선행 Step 머지 후 브랜치 생성**: PLAN.md에 "의존성" 표시가 있는 Step(예: 1-3은 1-1·1-2에 의존)은 선행 Step이 `main`에 머지된 뒤 그 지점에서 새 브랜치를 딴다. 의존성 없는 Step끼리는 각자 `main`에서 바로 브랜치를 따 병렬로 진행해도 된다.
8. **시크릿은 절대 커밋 금지**: `.env`, API 키 등은 커밋하지 않는다. 새 환경변수가 필요하면 `.env.example`/`render.yaml`의 `sync: false` 항목만 갱신하고, 실제 값은 각자 로컬 `.env` 또는 Render 대시보드에 직접 등록한다.
9. **머지 후 체크리스트 갱신**: PR이 머지되면 같은 PR 또는 후속 커밋으로 하단 체크리스트의 해당 항목을 `[x]`로 갱신한다.

---

## Phase 0 — OpenAI(GPT-4o-mini) 연동 + 프로덕션 기본값 전환

가장 작고 리스크가 큰 항목이라 최우선. 규모가 작아 스텝을 나누지 않고 한 번에 진행한다.

- [ ] **Step 0-1**: `llm_client.py`에 `_call_openai()` 추가(`_call_groq`와 동일한 OpenAI 호환 REST 형태), `_MODEL_CONFIG["openai"]`(default/high 모두 `gpt-4o-mini`)와 `_DISPATCH` 등록. `.env.example`/`README.md`에 `LLM_PROVIDER=openai`, `OPENAI_API_KEY` 문서화. `render.yaml`의 `LLM_PROVIDER`를 `mock`→`openai`로, `OPENAI_API_KEY`(`sync: false`) 추가.
  - 파일: `backend/llm_client.py`, `backend/.env.example`, `README.md`, `render.yaml`
  - 완료 기준: 로컬에서 `LLM_PROVIDER=openai` + 실제 키로 `/api/questions` 호출 시 실제 GPT-4o-mini 응답이 옴
  - 확인: `curl localhost:8000/api/health` → `{"provider":"openai"}`, Render 배포 후 프로덕션 URL로 동일 테스트(대시보드에 `OPENAI_API_KEY` 수동 등록 필요)
  - 의존성: 없음

---

## Phase 1 — 스파링 루프 고도화 + 전공계열별 페르소나

### Step 1-1: 난이도/최대턴수/rubric — 백엔드
- 파일: `backend/schemas.py`, `backend/prompts.py`, `backend/main.py`
- 작업: `QuestionRequest.difficulty`(easy/medium/hard, 기본 medium), `EvaluateRequest.max_turns`(0~5, 기본 2) 추가. `build_question_prompt`가 난이도별 톤 지시 추가, `build_evaluate_prompt`의 `turn < 2` 하드코딩을 `turn < max_turns`로 교체, `EvaluateResponse.rubric` 추가. `main.py`의 `req.turn >= 2` 하드가드를 `req.turn >= req.max_turns`로 교체.
- 완료 기준: `max_turns=0`/`5` 경계값 curl 테스트에서 꼬리질문 로직이 정확히 동작
- 의존성: 없음 (Step 1-2와 병렬 가능)

### Step 1-2: 전공계열별 페르소나 — 백엔드
- 파일: `backend/personas.py`, `backend/schemas.py`, `backend/main.py`
- 작업: `FIELD_HINTS`(공학/인문사회/자연) + `get_field_hint()` 추가. `QuestionRequest`/`EvaluateRequest`/`ReportRequest`에 `field: Optional[...] = None` 추가(기본값 None = 기존과 100% 호환). `main.py`에서 `persona["system"] + field_hint` 합성.
- 완료 기준: 동일 대본에 field만 바꿔 curl 호출 시 질문 톤이 계열별로 달라짐
- 의존성: 없음 (Step 1-1과 병렬 가능)

### Step 1-3: 프론트 연동
- 파일: `frontend/src/types.ts`, `frontend/src/components/SetupScreen.tsx`, `frontend/src/App.tsx`, `frontend/src/components/SparScreen.tsx`, `frontend/src/api.ts`
- 작업: 난이도 선택 + 최대턴수 스테퍼 + 계열 단일선택(페르소나 선택과 동일한 버튼그룹 패턴) UI 추가, `App.tsx` 상태로 보관해 API 호출까지 스레딩, rubric을 verdict 말풍선에 칩으로 표시.
- 완료 기준: 브라우저에서 난이도/계열 선택 후 스파링 진행 시 실제로 반영됨
- 의존성: Step 1-1, 1-2 완료 후 진행 (백엔드 스키마 확정 필요)

---

## Phase 2 — STT 전공용어 보정 + 마이크 권한 UX

### Step 2-1: STT 용어사전 보정
- 파일: `frontend/src/lib/termCorrection.ts`(신규), `frontend/src/components/SparScreen.tsx`, `frontend/package.json`
- 작업: `buildTermDictionary(script, slides)` / `correctText(text, dict)` 구현(어절 단위 편집거리 유사도 매칭, `fastest-levenshtein` 사용). `SparScreen.tsx`의 STT `onFinal` 콜백에서 답변창 반영 전에 통과. 보조로 `EvaluateRequest.term_hints` 추가해 `build_evaluate_prompt`에 용어집 힌트 삽입(`backend/schemas.py`, `backend/prompts.py`).
- 완료 기준: 전공 용어 포함 대본으로 실제 마이크 받아쓰기 시 보정 전/후 차이 확인
- 의존성: 없음

### Step 2-2: 마이크 권한 에러 UX
- 파일: `frontend/src/hooks/useSpeechRecognition.ts`, `frontend/src/components/SparScreen.tsx`
- 작업: `rec.onerror`가 현재 무동작(`() => {}`)이라 권한 거부 시 무설명 실패 — `micError: string | null`을 훅에서 노출하고 `SparScreen.tsx`에 인라인 에러 메시지 렌더.
- 완료 기준: 브라우저 마이크 권한을 차단한 상태에서 에러 메시지가 노출됨
- 의존성: 없음 (Step 2-1과 병렬 가능, 서로 다른 부분을 건드림)

---

## Phase 3 — PPT 업로드 + 슬라이드별 구체적 누락 피드백

### Step 3-1: PPT 추출 백엔드
- 파일: `backend/requirements.txt`(`python-pptx` 추가), `backend/ppt_extract.py`(신규), `backend/main.py`, `backend/schemas.py`
- 작업: `extract_slides(file_bytes) -> List[Slide]` 구현. `POST /api/slides/extract`(multipart, 확장자/MIME/크기(20MB) 검증, `.ppt` 구버전은 400) 신규 엔드포인트, `SlideExtractResponse` 스키마 추가.
- 완료 기준: 실제 `.pptx` 파일 curl 업로드 시 슬라이드 텍스트 JSON 반환, `.ppt` 업로드 시 400
- 의존성: 없음

### Step 3-2: PPT 업로드 프론트 연동
- 파일: `frontend/src/api.ts`, `frontend/src/components/SlideInput.tsx`
- 작업: `FormData` 기반 `extractSlides(file)` 헬퍼 추가(기존 `post()`는 JSON 전용). `SlideInput.tsx`에 업로드 컨트롤 추가, 추출 결과를 기존 수동 편집 리스트에 채워 사용자가 오추출을 직접 수정 가능하게 유지.
- 완료 기준: 브라우저에서 PPT 업로드 시 슬라이드 입력창이 자동으로 채워짐
- 의존성: Step 3-1 완료 후 진행

### Step 3-3: 슬라이드별 구체적 누락 피드백
- 파일: `backend/prompts.py`, `backend/main.py`
- 작업: `build_report_prompt`가 누락 카테고리(수치/정의/근거/방법/결론)를 명시하도록 지시 강화. `_fallback_coverage`를 숫자/퍼센트 패턴 여부로 분기해 "핵심 수치(예: X)" vs "핵심 용어(예: X)" 문구로 구체화.
- 완료 기준: 커버리지 미달 슬라이드에서 구체적 항목명이 포함된 문구가 리포트에 나타남
- 의존성: 없음 (Step 3-1, 3-2와 병렬 가능)

---

## Phase 4 — 세션 저장(localStorage) + 추이 그래프(Recharts)

> DB가 아니라 localStorage를 쓰는 이유: Render 무료 티어는 영속 디스크가 없어 SQLite도 재배포 시 소실되고, 앱에 인증이 없어 DB를 붙여도 결국 익명 ID를 localStorage에 저장해야 함. 여러 기기 동기화는 요구사항에 없음 — 로그인 기능이 생기면 재검토.

### Step 4-1: 세션 저장 유틸
- 파일: `frontend/src/lib/sessionStore.ts`(신규)
- 작업: `SessionRecord` 타입(id/completedAt/field/personaIds/report/estMinutes), `saveSession`/`loadSessions`/`clearSessions`(storage 비활성 대비 try/catch, 최대 50개 보관).
- 완료 기준: 유닛 테스트 또는 콘솔에서 저장→조회 왕복 확인
- 의존성: Phase 1~3에서 `Report` 모양이 안정화된 뒤 진행 권장(먼저 하면 `schemaVersion` 방어 로직 필요)

### Step 4-2: App.tsx 연동
- 파일: `frontend/src/App.tsx`, `frontend/src/types.ts`
- 작업: `handleFinish` 성공 경로에서 `saveSession()` 호출. `Stage`에 `'history'` 추가, 헤더에 상시 "히스토리" 내비게이션 추가(기존 셋업→스파링→리포트 위저드와 별개).
- 완료 기준: 세션 완료 후 새로고침해도 히스토리 진입 가능
- 의존성: Step 4-1 완료 후 진행

### Step 4-3: 히스토리 화면 + 그래프
- 파일: `frontend/src/components/HistoryScreen.tsx`(신규), `frontend/package.json`(`recharts` 추가)
- 작업: 필러단어/어절수/예상시간/슬라이드커버리지율의 시계열 라인차트 + 과거 세션 목록. 선택: `ReportScreen.tsx`에 직전 세션 대비 델타 표시.
- 완료 기준: 세션 2회 이상 완료 후 히스토리에서 두 시점을 반영한 추이 그래프 확인
- 의존성: Step 4-2 완료 후 진행

---

## Phase 5 — 모바일 사용성 정리

Phase 1~4에서 새로 생긴 UI(난이도/계열 선택, PPT 업로드, HistoryScreen/차트)까지 포함해 마지막에 한 번에 정리한다.

### Step 5-1: SparScreen 레이아웃
- 파일: `frontend/src/components/SparScreen.tsx`
- 작업: 고정 `h-[420px]` 채팅 로그를 `dvh` 기반으로, 답변 입력바 sticky 처리(가상 키보드 회피). 마이크/텍스트영역/전송 버튼 탭 타겟 ~44×44px, textarea font-size ≥16px(iOS 자동 줌 방지).
- 완료 기준: 실기기/DevTools 모바일 뷰포트에서 입력 UI가 가려지지 않음
- 의존성: 없음

### Step 5-2: 전역 진행 표시
- 파일: `frontend/src/App.tsx`
- 작업: 현재 `hidden sm:flex`라 모바일에 진행 표시가 없음 — 헤더 아래 컴팩트 진행바 추가.
- 완료 기준: 모바일 뷰포트에서도 현재 단계 인지 가능
- 의존성: 없음 (Step 5-1과 병렬 가능)

### Step 5-3: 전체 모바일 QA 패스
- 파일: 없음(회귀 확인만)
- 작업: 셋업→스파링→리포트→히스토리 전 흐름을 모바일 뷰포트에서 실행, Phase 1~4에서 추가된 신규 UI 요소 포함해 확인.
- 완료 기준: 전 흐름이 모바일에서 막힘 없이 동작
- 의존성: Phase 1~4 전체 + Step 5-1, 5-2 완료 후 진행

---

## 전체 체크리스트

> Step을 시작할 때 `(담당: 이름)`을 채워 선점을 표시하고, 머지되면 `[x]`로 바꾼다.

- [x] 0-1: OpenAI 연동 + 프로덕션 기본값 (담당: cl-o-lc)
- [ ] 1-1: 난이도/최대턴수/rubric (백엔드) (담당: cl-o-lc)
- [ ] 1-2: 전공계열별 페르소나 (백엔드) (담당: )
- [ ] 1-3: 난이도/계열 프론트 연동 (담당: )
- [ ] 2-1: STT 용어사전 보정 (담당: )
- [ ] 2-2: 마이크 권한 에러 UX (담당: )
- [ ] 3-1: PPT 추출 백엔드 (담당: )
- [ ] 3-2: PPT 업로드 프론트 연동 (담당: )
- [ ] 3-3: 슬라이드별 구체적 누락 피드백 (담당: )
- [ ] 4-1: 세션 저장 유틸 (담당: )
- [ ] 4-2: App.tsx 히스토리 연동 (담당: )
- [ ] 4-3: 히스토리 화면 + 그래프 (담당: )
- [ ] 5-1: SparScreen 모바일 레이아웃 (담당: )
- [ ] 5-2: 전역 진행 표시 (담당: )
- [ ] 5-3: 전체 모바일 QA 패스 (담당: )
