"""Prompt templates. Provider-agnostic pure text.

Each builder returns a (system, user) tuple. The LLM is always instructed to
return strict JSON so the backend can parse deterministically.
"""
from typing import List
from schemas import Slide, TranscriptTurn


def _format_slides(slides: List[Slide]) -> str:
    if not slides:
        return "(제출된 슬라이드 없음)"
    return "\n".join(f"[슬라이드 {s.index}] {s.text}" for s in slides)


_DIFFICULTY_HINTS = {
    "easy": "질문 난이도는 '쉬움'입니다. 단순 확인형 질문 하나만 던지세요 "
            "(예: 방금 말한 용어나 수치를 다시 확인하는 수준). 복합적인 압박은 피하세요.",
    "medium": "질문 난이도는 '보통'입니다. 근거가 약하거나 생략된 지점 하나를 짚어 "
               "적당히 파고드는 질문을 던지세요.",
    "hard": "질문 난이도는 '어려움'입니다. 발표에서 약점 두 가지를 동시에 엮어 "
            "(예: 근거 부족 + 논리적 비약) 반박하기 어려운 복합 압박 질문을 던지세요.",
}


# ---------------------------------------------------------------- questions
def build_question_prompt(persona_system: str, script: str, slides: List[Slide],
                          difficulty: str = "medium"):
    difficulty_hint = _DIFFICULTY_HINTS.get(difficulty, _DIFFICULTY_HINTS["medium"])
    system = (
        persona_system
        + f"\n\n{difficulty_hint}"
        + "\n\n반드시 아래 JSON 형식으로만 응답하세요. 다른 텍스트를 덧붙이지 마세요:\n"
        + '{"question": "<질문 한 개>", "targets_slide": <슬라이드 번호 정수 또는 null>}'
    )
    user = (
        "다음은 학생의 발표 대본과 슬라이드입니다.\n\n"
        f"[발표 대본]\n{script}\n\n"
        f"[슬라이드]\n{_format_slides(slides)}\n\n"
        "위 발표에서 근거가 약하거나, 생략되었거나, 설명이 불충분한 지점을 "
        "당신의 페르소나 관점에서 공략하는 압박 질문을 정확히 1개만 만드세요. "
        "특정 슬라이드와 관련된 질문이면 그 슬라이드 번호를 targets_slide 에 넣고, "
        "아니면 null 로 두세요."
    )
    return system, user


# ---------------------------------------------------------------- evaluate
def build_evaluate_prompt(persona_system: str, script: str, question: str,
                          answer: str, turn: int, max_turns: int = 2,
                          term_hints: List[str] | None = None):
    allow_followup = turn < max_turns
    term_hint_text = ""
    if term_hints:
        term_hint_text = (
            "\n\n[전공 용어 참고 목록] 아래는 이 발표의 대본/슬라이드에 등장하는 용어입니다. "
            "학생 답변은 음성 인식(STT)으로 받아쓴 것이라 발음이 비슷한 용어가 오탈자로 "
            "바뀌었을 수 있습니다 — 이 목록을 참고해 그런 오탈자는 실제 오답으로 채점하지 마세요: "
            + ", ".join(term_hints)
        )
    system = (
        persona_system
        + "\n\n당신은 방금 던진 질문에 대한 학생의 답변을 평가합니다. "
        + "다음 세 축으로 각각 '부족'/'보통'/'우수' 중 하나로 채점하세요: "
        + "직접성(질문에 직접 답했는가), 근거(근거를 제시했는가), 논리(논리가 일관적인가).\n"
        + ("답변이 불충분하면 같은 약점을 더 파고드는 꼬리 질문 1개를 followup 에 넣으세요. "
           if allow_followup
           else "이번 턴에서는 더 이상 꼬리 질문을 하지 말고 followup 을 반드시 null 로 두세요. ")
        + "답변이 충분하면 followup 을 null 로 두세요."
        + term_hint_text
        + "\n\n반드시 아래 JSON 형식으로만 응답하세요:\n"
        + '{"verdict": "<한줄 총평>", "strengths": "<잘한 점>", '
        + '"gaps": "<부족한 점>", "followup": "<꼬리질문 또는 null>", '
        + '"rubric": {"직접성": "부족|보통|우수", "근거": "부족|보통|우수", "논리": "부족|보통|우수"}}'
    )
    user = (
        f"[발표 대본 요약 참고]\n{script[:1500]}\n\n"
        f"[던진 질문]\n{question}\n\n"
        f"[학생 답변]\n{answer}\n\n"
        f"(현재 턴: {turn})\n위 답변을 평가하세요."
    )
    return system, user


# ---------------------------------------------------------------- report
def build_report_prompt(script: str, slides: List[Slide],
                        transcript: List[TranscriptTurn]):
    system = (
        "당신은 발표 스파링 세션 전체를 종합 평가하는 코치입니다. "
        "세 축으로 피드백을 작성하세요: 내용(content), 전달(delivery), 대응(response). "
        "또한 각 슬라이드의 핵심 내용이 발표 대본에서 실제로 '말로' 언급/설명되었는지 판정하세요. "
        "슬라이드에만 적혀 있고 대본에서 다뤄지지 않은 핵심이 있으면 covered=false 로 하고, "
        "무엇이 누락됐는지 missing_point 에 한 문장으로 적으세요.\n\n"
        "반드시 아래 JSON 형식으로만 응답하세요:\n"
        "{\n"
        '  "content_feedback": "<내용 축 피드백>",\n'
        '  "delivery_feedback": "<전달 축 피드백>",\n'
        '  "response_feedback": "<질의응답 대응 축 피드백>",\n'
        '  "slide_coverage": [{"index": <int>, "covered": <bool>, "missing_point": "<누락 핵심 또는 null>"}]\n'
        "}"
    )
    transcript_text = "\n\n".join(
        f"[페르소나 {t.persona_id}] 질문: {t.question}\n답변: {t.answer}\n평가: {t.verdict} / 부족: {t.gaps}"
        for t in transcript
    ) or "(질의응답 기록 없음)"
    user = (
        f"[발표 대본]\n{script}\n\n"
        f"[슬라이드]\n{_format_slides(slides)}\n\n"
        f"[질의응답 기록]\n{transcript_text}\n\n"
        "위 세션을 종합해 축별 피드백과 슬라이드 커버리지를 JSON 으로 작성하세요. "
        "slide_coverage 에는 제출된 모든 슬라이드를 index 순서대로 포함하세요."
    )
    return system, user
