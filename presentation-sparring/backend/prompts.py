from typing import List
from schemas import Slide, TranscriptTurn


def _format_slides(slides: List[Slide]) -> str:
    if not slides:
        return "(제출된 슬라이드 없음)"
    return "\n".join(f"[슬라이드 {slide.index}] {slide.text}" for slide in slides)


_DIFFICULTY_HINTS = {
    "easy": (
        "쉬움: 자료에 직접 나온 용어, 목적 또는 핵심 내용을 확인하세요. "
        "추론이나 외부 지식은 요구하지 마세요."
    ),
    "medium": (
        "보통: 자료 안에서 근거, 이유, 과정, 조건 또는 결과 해석 중 "
        "한 가지를 한 단계만 설명하게 하세요. "
        "자료에 없는 조사 설계, 편향, 전문 이론을 새로 가정하지 마세요."
    ),
    "hard": (
        "어려움: 자료와 관련된 일반 지식을 활용해 전제, 한계, 예외 또는 "
        "다른 해석 중 한 가지를 깊게 검증하세요. "
        "외부 사례가 불확실하면 실제 사실이 아니라 가정형 상황으로 제시하세요."
    ),
}

_EVALUATION_DIFFICULTY_HINTS = {
    "easy": "쉬움 수준을 유지하고 기본 의미나 용어 이해를 확인하세요.",
    "medium": "보통 수준을 유지하고 자료 안의 근거·이유·과정·조건 중 하나를 확인하세요.",
    "hard": "어려움 수준을 유지하고 전제·한계·예외·다른 해석 중 하나를 검증하세요.",
}


def build_question_prompt(
    persona_system: str,
    script: str,
    slides: List[Slide],
    difficulty: str = "medium",
):
    """발표 자료를 바탕으로 최초 질문 하나를 생성"""
    difficulty_hint = _DIFFICULTY_HINTS.get(
        difficulty,
        _DIFFICULTY_HINTS["medium"],
    )

    system = (
        f"{persona_system}\n\n{difficulty_hint}\n\n"
        "먼저 발표 대본과 슬라이드에 실제로 적힌 주장, 수치, 개념 중 하나를 고르세요. "
        "자료에 없는 조사 방식, 응답자 특성, 인과관계, 실패 원인을 사실처럼 추가하지 마세요. "
        "수치나 조사 결과를 묻는다면 출처·대상·측정 기준 중 하나만 선택하세요. "
        "인과 주장을 묻는다면 근거·과정·해석 중 하나만 선택하세요. "
        "한 질문에 두 가지 요구를 넣지 말고, 자료의 표현보다 과도하게 깊게 확장하지 마세요. "
        "슬라이드 기반 질문이면 슬라이드 번호와 확인할 내용을 질문 안에 포함하세요.\n"
        'JSON만 반환: {"question": "<한국어 한 문장>", "targets_slide": <정수 또는 null>}'
    )

    user = (
        f"[발표 대본]\n{script}\n\n"
        f"[슬라이드]\n{_format_slides(slides)}\n\n"
        "선택한 persona와 난이도에 맞는 질문 하나를 만드세요."
    )
    return system, user


def build_evaluate_prompt(
    persona_system: str,
    script: str,
    question: str,
    answer: str,
    turn: int,
    max_turns: int = 2,
    term_hints: List[str] | None = None,
    difficulty: str = "medium",
    root_question: str | None = None,
):
    """직전 답변을 평가하고 필요한 경우 같은 쟁점의 꼬리질문을 생성"""
    allow_followup = turn < max_turns
    difficulty_hint = _EVALUATION_DIFFICULTY_HINTS.get(
        difficulty,
        _EVALUATION_DIFFICULTY_HINTS["medium"],
    )
    root_question_text = (root_question or question).strip()

    if allow_followup:
        followup_rule = (
            "답변이 부족하면 최초 질문에서 선택한 하나의 검증 관점을 유지한 채, "
            "직전 답변에서 아직 설명되지 않은 부분만 더 좁혀 꼬리질문 하나를 만드세요. "
            "새로운 전공 평가 항목으로 이동하지 마세요. "
            "직전 답변을 반영하되 같은 질문 반복이나 새 주제 이동은 피하세요. "
            "학생이 모른다고 하거나 검색을 요구하면 첫 평가에서는 질문 범위를 더 좁히고, "
            "같은 회피가 반복되면 null로 끝내세요. 공부 계획이나 검색 방법은 묻지 마세요."
        )
    else:
        followup_rule = "허용 횟수에 도달했으므로 followup은 null로 두세요."

    term_hint_text = ""
    if term_hints:
        term_hint_text = (
            "\n용어 참고: "
            + ", ".join(term_hints[:12])
            + ". STT 오탈자만 참고하고 개념 오류로 단정하지 마세요."
        )

    system = (
        f"{persona_system}\n\n{difficulty_hint}\n\n"
        "학생의 직전 답변을 직접성, 근거, 논리로 평가하세요. "
        "각 값은 부족·보통·우수 중 하나입니다. 학생이 말하지 않은 장점은 만들지 마세요. "
        f"{followup_rule} 답변이 충분하면 남은 횟수와 관계없이 followup은 null입니다."
        f"{term_hint_text}\n"
        'JSON만 반환: {"verdict":"<총평>","strengths":"<강점>",'
        '"gaps":"<부족점>","followup":"<질문 또는 null>",'
        '"rubric":{"직접성":"부족|보통|우수","근거":"부족|보통|우수",'
        '"논리":"부족|보통|우수"}}'
    )

    script_reference = (
        f"[발표 대본 일부]\n{script[:1000]}\n\n"
        if turn == 0
        else ""
    )

    user = (
        f"{script_reference}"
        f"[최초 질문]\n{root_question_text[:600]}\n\n"
        f"[직전 질문]\n{question[:600]}\n\n"
        f"[학생 답변]\n{answer[:1600]}\n\n"
        f"[진행]\nturn={turn}, max_turns={max_turns}\n"
        "답변을 평가하고 필요한 경우 같은 쟁점의 꼬리질문을 만드세요."
    )
    return system, user


def build_report_prompt(
    script: str,
    slides: List[Slide],
    transcript: List[TranscriptTurn],
):
    """텍스트 자료만으로 종합 피드백과 슬라이드 커버리지를 생성"""
    system = (
        "발표 대본, 슬라이드, 질의응답 텍스트만 근거로 평가하세요. "
        "내용은 근거·구조·결과 해석, 전달은 텍스트의 명확성·용어 설명·설명 순서, "
        "대응은 질문 이해·직접성·근거 제시를 평가합니다. "
        "음성 정보가 없으므로 속도, 억양, 음량, 자신감, 긴장 상태를 추측하지 마세요. "
        "슬라이드 핵심이 대본에서 의미 있게 설명됐을 때만 covered=true로 두세요.\n"
        'JSON만 반환: {"content_feedback":"<내용>",'
        '"delivery_feedback":"<텍스트 기준 전달>",'
        '"response_feedback":"<대응>",'
        '"slide_coverage":[{"index":1,"covered":true,'
        '"missing_point":null}]}'
    )

    transcript_text = "\n".join(
        (
            f"[{turn.persona_id}] 질문: {turn.question}\n"
            f"답변: {turn.answer}\n"
            f"부족: {turn.gaps}"
        )
        for turn in transcript
    ) or "(질의응답 기록 없음)"

    user = (
        f"[발표 대본]\n{script}\n\n"
        f"[슬라이드]\n{_format_slides(slides)}\n\n"
        f"[질의응답]\n{transcript_text}\n\n"
        "모든 슬라이드를 index 순서대로 포함해 평가하세요."
    )
    return system, user