# 🎤 발표 스파링 파트너 (Presentation Sparring Partner)

전공 발표/구술시험을 앞둔 학생이 **발표 후 질의응답을 실전처럼 연습**하는 웹앱.

발표 대본과 슬라이드 텍스트를 넣으면 → AI가 청중 페르소나(교수/동료/일반청중)로
압박 질문을 던지고 → 학생이 답하면 꼬리 질문을 이어가고 → 끝나면 정량 피드백
리포트를 준다.

> **한 문장 정의:** "여러 관점의 까다로운 청중을 동시에 상대하는 발표 질의응답 스파링 도구."

## 핵심 기능 (예선 MVP)

- **셋업**: 발표 대본 + 슬라이드별 텍스트 + 페르소나 선택
- **스파링 루프**: 페르소나가 질문 → 답변 평가 → 부실하면 꼬리 질문(최대 2턴) → 다음 페르소나로 로테이션
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

`backend/.env` 의 `LLM_PROVIDER` **한 줄만** 바꾸면 된다:

```
LLM_PROVIDER=mock          # gemini | groq | anthropic | mock
GEMINI_API_KEY=...
GROQ_API_KEY=...
ANTHROPIC_API_KEY=...
```

- `mock` — API 키 없이 캔드 응답으로 전체 흐름을 데모 (오프라인 시연/개발용)
- `gemini` — Google Gemini (`gemini-2.0-flash`)
- `groq` — Groq (`llama-3.3-70b-versatile`)
- `anthropic` — Anthropic Claude (`claude-sonnet-5`, 교수 페르소나는 `claude-opus-4-8` 상위 티어로 라우팅)

모든 provider는 `backend/llm_client.py` 의 `chat()` 하나 뒤에 숨겨져 있다.
페르소나별 모델 티어 분리(`model_hint`)도 열려 있다.

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
- **LLM**: 환경변수로 교체 가능한 provider 추상화 (gemini / groq / anthropic / mock)
- **슬라이드 커버리지**: LLM 판정 + 키워드 오버랩 폴백 (모든 슬라이드가 항상 리포트에 표시됨)

## 스코프 밖 (본선 고도화)

- 실시간 STT/TTS 음성 (Web Speech API)
- 로그인/DB/세션 히스토리 — 상태는 메모리(React state)로만
- BGE-M3 의미유사도 기반 슬라이드 커버리지

## 본선 구현 로드맵

본선(최종 제출)을 위한 단계별 구현 계획은 [`PLAN.md`](./PLAN.md) 참고.
