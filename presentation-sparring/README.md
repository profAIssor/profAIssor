# 🎤 발표 스파링 파트너 (Presentation Sparring Partner)

전공 발표/구술시험을 앞둔 학생이 **발표 후 질의응답을 실전처럼 연습**하는 웹앱.

발표 대본과 슬라이드 텍스트를 넣으면 → AI가 청중 페르소나(교수/동료/일반청중)로
압박 질문을 던지고 → 학생이 답하면 꼬리 질문을 이어가고 → 끝나면 정량 피드백
리포트를 준다.

> **한 문장 정의:** "여러 관점의 까다로운 청중을 동시에 상대하는 발표 질의응답 스파링 도구."

## 핵심 기능 (예선 MVP)

- **셋업**: 발표 대본 + 슬라이드별 텍스트 + 페르소나 선택
- **스파링 루프**: 페르소나가 기본 질문 → 답변 평가 → 필요하면 꼬리질문 1회, 아니면 새 기본 질문 → 설정한 추가 질문 슬롯을 소진하면 다음 페르소나로 로테이션
- **슬라이드 커버리지 (킬러 기능)**: 슬라이드 텍스트 vs 대본을 비교해 "말로 전달되지 않은 슬라이드 핵심"을 탐지
- **피드백 리포트**: 축별 요약(내용/전달/대응) + 슬라이드 커버리지 + 필러 단어 카운트 + 대략 말속도
- **음성 답변 (STT)**: 스파링 화면에서 🎙 버튼으로 말하면 브라우저 내장 음성인식(Web Speech API)이
  답변창에 실시간 받아쓰기. 텍스트 흐름은 그대로라 마이크 미지원 브라우저에선 버튼이 숨겨지고 타이핑으로 동작.
  (Chrome 데스크톱 권장)

---

## 로컬 실행법

### 1. 백엔드 (FastAPI, 포트 8000)

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # 기본 LLM_PROVIDER=mock (API 키 없이 바로 데모 가능)
uvicorn main:app --reload --port 8000
```

### 2. 프론트엔드 (React + Vite, 포트 5173)

```bash
cd frontend
npm install
npm run dev                   # http://localhost:5173
```

브라우저에서 `http://localhost:5173` 접속 → 셋업 → 스파링 → 리포트 흐름이 텍스트만으로 끝까지 돈다.

---

## LLM Provider 교체

`backend/.env`의 `LLM_PROVIDER` 값을 변경해 provider를 선택한다.

```dotenv
LLM_PROVIDER=mock  # openai | gemini | mock

OPENAI_API_KEY=
OPENAI_MODEL=gpt-4o-mini

GEMINI_API_KEY=
GEMINI_MODEL=gemini-3.1-flash-lite
```

- `mock` — API 키 없이 화면과 API 연결을 검사하는 개발·시연용 고정 응답
- `openai` — OpenAI `gpt-4o-mini`, 현재 1차 MVP와 Render에서 사용하는 기본 provider
- `gemini` — Google `gemini-3.1-flash-lite`, 추후 품질·비용 비교를 위한 대체 provider

모든 provider는 `backend/llm_client.py`의 `chat()`과 `chat_json()` 뒤에 숨겨져 있다.

각 provider는 환경변수에 지정한 **하나의 모델만 사용**한다. 교수·동료·일반 청중 persona는 질문 관점과 표현 방식만 바꾸며, `OPENAI_MODEL_HIGH` 같은 별도 상위 티어 모델로 라우팅하지 않는다.

Groq와 Anthropic은 더이상 사용하지 않으므로 고려 대상에서 제외한다.

---

## API 엔드포인트 (curl 예시)

```bash
# 질문 생성
curl -X POST localhost:8000/api/questions -H 'content-type: application/json' \
  -d '{"script":"...","slides":[{"index":1,"text":"..."}],"persona_id":"professor"}'

# 답변 평가 (+ 꼬리 질문)
curl -X POST localhost:8000/api/evaluate -H 'content-type: application/json' \
  -d '{"script":"...","persona_id":"professor","question":"...","answer":"...","turn":0}'

# 종합 리포트
curl -X POST localhost:8000/api/report -H 'content-type: application/json' \
  -d '{"script":"...","slides":[...],"transcript":[...]}'
```

---

## 기술 스택

- **프론트**: React 18 + TypeScript + Vite + Tailwind CSS
- **백엔드**: Python + FastAPI + uvicorn
- **LLM**: 환경변수로 교체 가능한 provider 추상화 (`openai` / `gemini` / `mock`)
- **슬라이드 커버리지**: LLM 판정 + 키워드 오버랩 폴백 (모든 슬라이드가 항상 리포트에 표시됨)

## 스코프 밖 (본선 고도화)

- 실시간 STT/TTS 음성 (Web Speech API)
- 로그인/DB/세션 히스토리 — 상태는 메모리(React state)로만
- BGE-M3 의미유사도 기반 슬라이드 커버리지

## 본선 구현 로드맵

본선(최종 제출)을 위한 단계별 구현 계획은 [`PLAN.md`](./PLAN.md) 참고.
