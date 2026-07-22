from typing import List, Sequence

from schemas import Slide, TranscriptTurn


QUESTION_TYPE_IDS = (
    "evidence",
    "counterexample",
    "application",
    "definition",
)


_QUESTION_TYPE_GUIDE = """
[공통 질문 유형]

질문은 다음 네 유형 중 정확히 하나만 선택하세요.

1. evidence — 근거 요구형
   발표에서 제시한 주장이나 결론을 뒷받침하는 근거, 이유, 과정,
   자료 또는 결과 중 한 가지를 확인합니다.

2. counterexample — 반례 제시형
   발표자의 주장이나 규칙이 성립하지 않을 수 있는 예외 조건 또는
   반대 사례 한 가지를 확인합니다.

3. application — 확장 적용형
   발표 내용을 자료 속 예시, 유사한 대상, 다른 환경 또는 상황에
   적용할 때 필요한 판단이나 조건 한 가지를 확인합니다.

4. definition — 정의 확인형
   발표에 등장한 핵심 용어 또는 개념의 의미, 역할, 범위, 개념 간 차이 중
   한 가지를 확인합니다.

하나의 질문에 두 가지 질문 유형을 결합하지 마세요.
먼저 자료 전체의 성격과 흐름을 파악하고, 해당 자료에 실제로 적합한 유형을 찾은 뒤
그중 persona의 우선순위가 높은 유형을 선택하세요.
우선순위는 강제 할당이 아니라 자료에 적합한 유형을 고르기 위한 기준입니다.
"""


_MATERIAL_FLOW_GUIDE = """
[자료 전체 흐름 분석]

질문을 만들기 전에 발표 대본과 모든 슬라이드를 처음부터 끝까지 읽고
다음 중 자료의 성격을 내부적으로 판단하세요.

- project_research: 문제·목적 → 방법·구현 → 결과 → 의의·한계 흐름
- proposal_argument: 배경·문제 → 주장·제안 → 근거 → 기대 효과·제약 흐름
- concept_lesson: 학습 주제 → 정의 → 개념 간 관계·비교 → 규칙·조건 → 예시·적용 흐름
- mixed: 위 흐름이 섞였으며 실제 슬라이드 순서를 기준으로 판단해야 하는 자료

이 분류는 내부 판단용이며 질문 문장에 분류명을 노출하지 마세요.
한 슬라이드의 문구를 격리해서 보지 말고, 의미를 이해하는 데 필요한 앞뒤 슬라이드가 있다면
함께 참고하세요. 다만 질문 하나에서 다룰 핵심 쟁점은 하나로 유지하세요.

특히 concept_lesson 자료에서는 이미 적힌 정의를 그대로 다시 말하게 하는 데 그치지 말고,
정의와 비교 기준, 규칙과 예시가 어떻게 연결되는지 확인하세요.
학생이 한 페이지를 암기했는지가 아니라 해당 단원의 흐름을 이해했는지 검증해야 합니다.
"""


_QUESTION_CONTRACT_GUIDE = """
[질문-평가 계약]

질문 문장에 명시된 요구 범위가 이후 평가의 계약입니다.
난이도는 질문 생성 시 질문 문장 안에 드러나야 하며, 평가 단계에서 질문에 없던 요구를
추가하는 근거로 사용하지 마세요.

- “무엇인가요?”, “몇 가지인가요?”, “두 가지를 말해 주세요”는 명칭·항목을 정확히 제시하면 충족입니다.
- “각각 어떤 역할인가요?”, “의미를 설명해 주세요”는 간단한 역할·의미 설명까지 요구합니다.
- “왜 그런가요?”, “근거는 무엇인가요?”는 이유 또는 근거의 연결을 요구합니다.
- “어떻게 수행하나요?”, “절차를 설명해 주세요”는 과정이나 순서를 요구합니다.
- “예시에 적용해 주세요”는 자료 속 사례에 대한 적용 판단을 요구합니다.

예를 들어 “복구의 두 가지 주요 작업은 무엇인가요?”라는 질문에는 “Undo와 Redo입니다.”라고
정확히 답하면 충분합니다. 각각의 수행 절차나 로그 종류는 별도 질문에서 명시적으로 요구하지
않는 한 평가 기준에 포함하지 마세요.

expected_answer_points는 질문 문장이 직접 요구한 답만 포함해야 합니다.
질문이 명칭 두 개만 요구하면 두 명칭만 넣고, 역할·이유·절차·예시는 추가하지 마세요.
자료 전체를 읽는 목적은 중요한 질문을 고르는 것이지, 한 답변에 전체 단원 내용을 요구하는 것이 아닙니다.
"""


_DIFFICULTY_HINTS = {
    "easy": (
        "[난이도: 쉬움]\n"
        "전체 자료의 흐름은 먼저 읽되, 질문은 서로 인접하거나 직접 연결된 1~2개 슬라이드의 "
        "명시적 내용만 사용하세요. 발표자가 1~2문장으로 답할 수 있어야 하며, "
        "외부 지식이나 숨은 전제를 요구하지 마세요. "
        "정의 확인형은 핵심 의미나 두 개념의 직접적인 차이 하나를 묻고, "
        "근거 요구형은 자료에 직접 나온 이유나 근거 하나만 확인하세요. "
        "확장 적용형은 자료에 이미 제시된 예시 또는 매우 유사한 상황에만 적용하세요. "
        "반례 제시형은 자료에 예외·한계·대상 차이가 직접 제시된 경우에만 사용하세요."
    ),
    "medium": (
        "[난이도: 보통]\n"
        "자료 전체의 흐름을 읽고 직접 관련된 2~3개 슬라이드를 연결할 수 있지만, "
        "추론은 한 단계로 제한하세요. "
        "정의 확인형은 개념의 역할, 비교 기준, 사용 조건 중 하나를 묻고, "
        "근거 요구형은 주장과 자료상 근거가 어떻게 연결되는지 확인하세요. "
        "반례 제시형은 자료와 직접 연결된 예외 조건 하나를 제시하세요. "
        "확장 적용형은 자료 속 규칙이나 주장을 다른 예시·대상·환경에 적용할 때 필요한 "
        "판단 또는 변경점 하나를 묻으세요. "
        "자료에 없는 전문 이론, 조사 설계 또는 복수의 가정을 요구하지 마세요."
    ),
    "hard": (
        "[난이도: 어려움]\n"
        "발표 전체 또는 하나의 완결된 단원 흐름을 바탕으로 전제, 타당성, 실패 조건, "
        "적용 조건, 개념의 경계 중 하나를 깊게 검증하세요. "
        "정의 확인형은 개념의 범위와 유사 개념과의 경계를, "
        "근거 요구형은 근거의 타당성이나 일반화 가능성을, "
        "반례 제시형은 결론이나 규칙이 깨지는 조건을, "
        "확장 적용형은 다른 환경에서 성립하기 위한 조건과 한계를 확인하세요. "
        "외부 사례가 불확실하면 실제 사실처럼 말하지 말고 하나의 가정형 상황으로 명시하세요. "
        "여러 약점이나 요구 사항을 한 질문에 결합하지 마세요."
    ),
}


_EVALUATION_DIFFICULTY_HINTS = {
    "easy": (
        "[쉬움 평가 기준] 질문 문장에 직접 적힌 요구만 평가하세요. "
        "명칭·항목을 묻는 질문은 정확한 명칭만 제시해도 충분하며, "
        "추가 설명이나 근거가 없다는 이유로 감점하지 마세요."
    ),
    "medium": (
        "[보통 평가 기준] 질문 문장에 역할·관계·이유·조건 설명이 명시된 경우에만 "
        "그 한 단계 설명을 요구하세요. 질문이 명칭이나 항목만 묻는 형태라면 "
        "난이도가 보통이어도 설명을 숨은 요구 사항으로 추가하지 마세요."
    ),
    "hard": (
        "[어려움 평가 기준] 질문 문장에 타당성·실패 조건·적용 조건·개념 경계가 "
        "명시된 경우에만 그 깊이를 평가하세요. 질문에 없는 한계·절차·사례를 "
        "추가로 말하지 않았다는 이유로 감점하지 마세요."
    ),
}


_QUESTION_TYPE_EVALUATION_RULES = {
    "evidence": (
        "현재 질문은 근거 요구형입니다. 주장에 직접 답했는지와 제시한 근거가 "
        "해당 주장과 실제로 연결되는지를 평가하세요. "
        "같은 유형을 유지한다면 근거의 구체성 또는 연결 관계만 더 좁혀 물으세요."
    ),
    "counterexample": (
        "현재 질문은 반례 제시형입니다. 제시된 예외 조건을 이해했는지, "
        "그 조건에서 기존 결론이나 규칙이 어떻게 달라지는지 답했는지를 평가하세요. "
        "같은 유형을 유지한다면 동일한 예외 조건의 영향만 더 좁혀 물으세요."
    ),
    "application": (
        "현재 질문은 확장 적용형입니다. 자료의 규칙이나 주장을 해당 예시·상황에 "
        "적용할 수 있는지와 필요한 판단 또는 조건을 설명했는지 평가하세요. "
        "같은 유형을 유지한다면 동일한 적용 상황에서 빠진 조건 하나만 물으세요."
    ),
    "definition": (
        "현재 질문은 정의 확인형입니다. 핵심 개념의 의미, 역할, 범위 또는 개념 간 차이를 "
        "질문 수준에 맞게 설명했는지 평가하세요. "
        "같은 표현으로 정의를 반복하게 하지 말고, 의미가 대체로 맞지만 실제 이해가 불분명하면 "
        "자료 속 예시나 사용 상황에 적용하게 하는 방식을 우선 검토하세요."
    ),
}


_FOLLOWUP_DIFFICULTY_RULES = {
    "easy": (
        "쉬움 꼬리질문은 관련 슬라이드에 직접 나온 의미나 예시 중 빠진 한 부분만 확인하세요. "
        "정의 확인형에서 확장 적용형으로 전환할 때도 자료에 직접 나온 예시만 사용하세요. "
        "새로운 전제, 복잡한 반례, 외부 지식 또는 심화 근거를 추가하지 마세요."
    ),
    "medium": (
        "보통 꼬리질문은 같은 핵심 주제 안에서 빠진 근거·이유·관계·조건 하나만 구체화하세요. "
        "같은 유형을 반복하면 질문이 사실상 중복될 때에만 인접 유형으로 한 번 전환할 수 있습니다."
    ),
    "hard": (
        "어려움 꼬리질문은 최초 질문의 핵심 주제를 유지하면서 전제·타당성·실패 조건·"
        "적용 조건 중 이미 관련 자료에서 드러난 한 부분만 더 좁히세요. "
        "여러 검증 축을 동시에 추가하지 마세요."
    ),
}


_TYPE_TRANSITION_GUIDE = """
[꼬리질문 유형 전환 규칙]

꼬리질문은 같은 핵심 주제와 난이도를 유지해야 합니다.
질문 유형은 무조건 고정하지 않지만, 같은 표현을 반복하는 것을 피하기 위해
첫 번째 꼬리질문(turn=0)에서만 다음 인접 유형으로 한 번 전환할 수 있습니다.

- definition → application: 개념 설명을 자료 속 예시나 사용 상황에 적용해 이해를 확인
- evidence → counterexample: 제시한 근거가 자료에 드러난 예외 조건에서도 유지되는지 확인
- application → definition: 적용 판단에 사용한 핵심 개념이나 기준을 다시 명확히 확인
- counterexample → evidence: 예외에 대한 대응이나 기존 결론 유지의 근거를 확인

쉬움에서는 definition → application 전환만 허용하며, 반드시 자료에 직접 제시된 예시를 사용하세요.
turn이 1 이상이면 더 이상 유형을 전환하지 말고 현재 유형을 유지하거나 종료하세요.
유형 전환은 질문을 더 어렵게 만들기 위한 것이 아니라 실제 이해를 확인하기 위한 것입니다.
"""


def _format_slides(slides: List[Slide]) -> str:
    """슬라이드 목록을 LLM이 구분하기 쉬운 텍스트로 변환합니다."""
    if not slides:
        return "(제출된 슬라이드 없음)"

    return "\n".join(
        f"[슬라이드 {slide.index}] {slide.text}"
        for slide in sorted(slides, key=lambda item: item.index)
    )


def _format_script(script: str) -> str:
    """대본이 없는 슬라이드 전용 세션도 프롬프트가 깨지지 않게 처리합니다."""
    if not script.strip():
        return "(대본이 제공되지 않았습니다. 슬라이드 전체 흐름을 근거로 판단하세요.)"

    return script


def _format_question_type_priority(
    question_type_priority: Sequence[str] | None,
) -> str:
    """유효한 질문 유형만 남겨 persona별 우선순위를 문자열로 변환합니다."""
    valid_types = [
        question_type
        for question_type in (question_type_priority or ())
        if question_type in QUESTION_TYPE_IDS
    ]

    if not valid_types:
        valid_types = [
            "definition",
            "evidence",
            "application",
            "counterexample",
        ]

    return " > ".join(valid_types)


def _format_context_slides(
    slides: List[Slide],
    context_slides: List[int] | None,
) -> str:
    """평가 단계에는 최초 질문과 관련된 슬라이드만 우선 전달합니다."""
    if not slides:
        return "(제출된 슬라이드 없음)"

    requested = {
        index
        for index in (context_slides or [])
        if isinstance(index, int)
    }

    if requested:
        selected = [
            slide
            for slide in sorted(slides, key=lambda item: item.index)
            if slide.index in requested
        ]
        if selected:
            return _format_slides(selected)

    # 이전 클라이언트처럼 context_slides가 없는 경우에는 전체 자료를 사용합니다.
    return _format_slides(slides)


def _format_excluded_questions(excluded_questions: List[str] | None) -> str:
    """같은 persona에서 이미 사용한 질문을 반복 방지 목록으로 변환합니다."""
    questions = [
        question.strip()
        for question in (excluded_questions or [])
        if isinstance(question, str) and question.strip()
    ]

    if not questions:
        return "(없음)"

    return "\n".join(
        f"- {question[:300]}"
        for question in questions[-6:]
    )


def _format_expected_points(expected_answer_points: List[str] | None) -> str:
    """최초 질문의 내부 채점 기준을 읽기 쉬운 목록으로 변환합니다."""
    points = [
        point.strip()
        for point in (expected_answer_points or [])
        if isinstance(point, str) and point.strip()
    ]

    if not points:
        return "(명시된 기대 답변 요소 없음 — 질문과 관련 슬라이드에서 판단)"

    return "\n".join(
        f"- {point}"
        for point in points[:3]
    )


def build_question_prompt(
    persona_system: str,
    script: str,
    slides: List[Slide],
    difficulty: str = "medium",
    question_type_priority: Sequence[str] | None = None,
    excluded_questions: List[str] | None = None,
):
    """전체 자료 흐름을 바탕으로 유형과 내부 평가 맥락이 있는 최초 질문을 생성합니다."""
    difficulty_hint = _DIFFICULTY_HINTS.get(
        difficulty,
        _DIFFICULTY_HINTS["medium"],
    )

    priority_text = _format_question_type_priority(question_type_priority)

    system = (
        f"[페르소나]\n{persona_system}\n\n"
        f"{_MATERIAL_FLOW_GUIDE}\n"
        f"{_QUESTION_TYPE_GUIDE}\n"
        f"{_QUESTION_CONTRACT_GUIDE}\n"
        f"[질문 유형 우선순위]\n{priority_text}\n\n"
        f"{difficulty_hint}\n\n"
        "[질문 생성 순서]\n"
        "1. 발표 대본과 모든 슬라이드를 처음부터 끝까지 읽으세요.\n"
        "2. 자료의 성격과 도입→설명→비교·근거→예시·결론의 실제 흐름을 내부적으로 정리하세요.\n"
        "3. 전체 흐름에서 발표자가 반드시 이해해야 하는 핵심 주제 하나를 고르세요.\n"
        "4. 해당 주제를 이해하는 데 필요한 관련 슬라이드 1~3개를 context_slides로 선택하세요.\n"
        "5. 현재 난이도에서 답할 수 있는 질문 유형을 찾고 persona 우선순위를 참고해 하나를 선택하세요.\n"
        "6. 제외할 이전 질문 목록과 핵심 초점이 겹치지 않는지 확인하세요.\n"
        "7. 선택한 유형과 난이도에 맞는 질문 한 문장, 질문 초점, 기대 답변 요소를 작성하세요.\n\n"
        "질문은 전체 자료를 읽고 만든 것이어야 하지만 한 번에 하나의 핵심 쟁점만 다루세요. "
        "제외할 이전 질문이 있다면 같은 문장을 바꾸어 말하거나 같은 핵심 초점을 다시 묻지 마세요. "
        "자료에 다른 유효한 쟁점이 없을 때만 가장 가까운 주제를 선택하되 이전 질문과 요구 사항을 분명히 달리하세요. "
        "슬라이드 문구나 제목을 그대로 읽고 '설명해 주세요'라고 되묻지 마세요. "
        "개념 설명·교재형 자료에서는 정의만 반복시키지 말고, 비교 기준·사용 조건·예시의 연결을 "
        "현재 난이도 범위 안에서 확인하세요. "
        "자료에 없는 조사 방식, 응답자 특성, 인과관계, 실패 원인, 정답을 사실처럼 추가하지 마세요. "
        "난이도에서 기대하는 깊이는 질문 문장의 동사와 요구 사항에 직접 드러내세요. "
        "예를 들어 보통 난이도에서 역할 설명을 기대한다면 처음부터 각각 어떤 역할을 하는지 물으세요. "
        "명칭만 묻고 평가 단계에서 역할 설명을 추가로 요구하는 질문은 만들지 마세요. "
        "expected_answer_points는 자료에서 확인 가능한 핵심 요소 중 질문 문장이 직접 요구한 것만 1~3개 작성하세요. "
        "학생에게 보이지 않는 내부 평가 기준이라는 이유로 질문보다 넓은 범위를 넣지 마세요. "
        "context_slides는 질문을 이해하고 평가하는 데 실제로 필요한 슬라이드 번호만 오름차순으로 넣으세요. "
        "targets_slide는 질문과 가장 직접적으로 연결된 대표 슬라이드 한 장의 번호이며 없으면 null입니다. "
        "질문은 한국어 존댓말 한 문장으로 작성하세요.\n"
        'JSON만 반환: {'
        '"question": "<한국어 한 문장>", '
        '"question_type": "evidence|counterexample|application|definition", '
        '"targets_slide": <정수 또는 null>, '
        '"question_focus": "<검증할 핵심 주제를 짧은 한국어 구절로>", '
        '"context_slides": [<관련 슬라이드 번호 1~3개>], '
        '"expected_answer_points": ["<자료 기반 핵심 요소 1>", "<선택 요소 2>"]'
        "}"
    )

    user = (
        f"[발표 대본]\n{_format_script(script)}\n\n"
        f"[전체 슬라이드]\n{_format_slides(slides)}\n\n"
        f"[제외할 이전 질문]\n{_format_excluded_questions(excluded_questions)}\n\n"
        "자료 전체의 흐름을 먼저 파악한 다음, 한 페이지의 문구를 고립해서 되묻지 말고 "
        "가장 중요한 학습·발표 흐름을 확인하는 질문 하나를 만드세요."
    )

    return system, user


def build_evaluate_prompt(
    persona_system: str,
    script: str,
    slides: List[Slide],
    question: str,
    answer: str,
    turn: int,
    max_turns: int = 2,
    term_hints: List[str] | None = None,
    difficulty: str = "medium",
    root_question: str | None = None,
    root_question_type: str | None = None,
    question_type: str | None = None,
    question_focus: str = "",
    context_slides: List[int] | None = None,
    expected_answer_points: List[str] | None = None,
    is_no_answer: bool = False,
):
    """자료 맥락을 참고해 답변을 평가하고, 답변 불가 시 힌트와 쉬운 재질문을 생성합니다."""
    allow_followup = turn < max_turns

    difficulty_hint = _EVALUATION_DIFFICULTY_HINTS.get(
        difficulty,
        _EVALUATION_DIFFICULTY_HINTS["medium"],
    )

    followup_difficulty_rule = _FOLLOWUP_DIFFICULTY_RULES.get(
        difficulty,
        _FOLLOWUP_DIFFICULTY_RULES["medium"],
    )

    root_question_text = (root_question or question).strip()
    root_type_text = (
        root_question_type
        if root_question_type in QUESTION_TYPE_IDS
        else "unknown"
    )

    if question_type in _QUESTION_TYPE_EVALUATION_RULES:
        question_type_text = question_type
        question_type_rule = _QUESTION_TYPE_EVALUATION_RULES[question_type]
    else:
        question_type_text = "unknown"
        question_type_rule = (
            "질문 유형 정보가 전달되지 않았습니다. 최초 질문과 직전 질문을 보고 "
            "근거 요구형, 반례 제시형, 확장 적용형, 정의 확인형 중 하나로 분류한 뒤 평가하세요."
        )

    if is_no_answer:
        followup_rule = (
            "서버가 학생 답변을 답변 불가로 판정했습니다. "
            "followup은 정상 꼬리질문 횟수에 포함되지 않는 학습용 재질문입니다. "
            "같은 핵심 주제를 한 단계 낮춰 묻고 원래 질문의 범위를 넓히거나 새 주제로 바꾸지 말며, "
            "질문 관련 슬라이드에 직접 제시된 정보 한 가지만 사용해 1문장으로 답할 수 있게 만드세요. "
            "근거·반례·적용을 요구한 질문이었다면 먼저 핵심 개념이나 자료에 명시된 기본 관계를 묻는 "
            "definition 유형으로 낮출 수 있습니다. 원래 질문이 definition 유형이면 같은 개념에서 "
            "가장 기본적인 의미나 차이 한 가지만 더 구체적으로 물으세요. "
            "재질문 문장 안에 정답을 그대로 포함하지 마세요. 자료만으로 안전한 재질문을 만들 수 없을 때만 "
            "followup과 followup_question_type을 null로 두세요."
        )
        answer_mode_rule = (
            "answer_status는 unknown, verdict는 '확인 필요'로 작성하세요. "
            "strengths는 빈 문자열로 두고, gaps에는 발표 전에 질문의 핵심 내용을 "
            "다시 확인해야 한다는 짧은 안내만 작성하세요. "
            "직접성·근거·논리를 채점하지 말고 rubric은 빈 객체로 두세요. "
            "supplement에는 정답 전체나 완성된 모범 답안을 대신 작성하지 말고, "
            "질문 관련 슬라이드와 기대 답변 요소에서 확인되는 핵심 개념·비교 기준·순서 중 "
            "재질문을 시도할 수 있는 가장 중요한 실마리만 한국어 1~2문장으로 제시하세요. "
            "자료만으로 보충 내용을 확정할 수 없으면 임의의 사실을 만들지 말고 "
            "추가로 준비해야 할 핵심 항목을 안내하세요. "
            "related_slides에는 supplement를 직접 뒷받침하는 실제 슬라이드 번호만 "
            "1~3개 넣고, 해당 슬라이드가 없으면 빈 배열로 두세요."
        )
        result_rule = (
            "답변 불가 전용 필드와 쉬운 재질문을 위 규칙대로 작성하고 일반 평가를 수행하지 마세요."
        )
    else:
        if allow_followup:
            followup_rule = (
                "max_turns는 이 persona에서 기본 질문 뒤에 실제로 진행할 정상 꼬리질문 수입니다. "
                "현재 turn이 max_turns보다 작으므로 followup을 반드시 한국어 한 문장으로 생성하고, "
                "followup_question_type도 반드시 지정하세요. "
                "학생 답변이 충분하더라도 평가 결과를 억지로 낮추지 말고 verdict는 '충분', "
                "gaps는 '없음'으로 유지한 채 같은 핵심 주제의 다른 관점·예시·조건을 한 단계 이어서 확인하세요. "
                "학생 답변이 부분 충족이거나 부족하면 직전 질문에서 빠진 핵심 한 부분을 우선 확인하세요. "
                "질문의 핵심 주제와 관련 슬라이드 범위를 유지하고 직전 질문을 동의어나 유사 표현으로 반복하지 마세요. "
                "관련된 내용이라는 이유로 로그 종류, 장애 처리 절차, 추가 사례처럼 무관한 새 하위 주제로 이동하지 마세요. "
                "예를 들어 정의를 충분히 설명했다면 같은 정의를 다시 요구하지 말고 자료 속 예시 적용이나 사용 조건으로 이어가세요. "
                f"{followup_difficulty_rule}"
            )
        else:
            followup_rule = (
                "선택한 정상 꼬리질문 횟수를 모두 진행했으므로 followup과 "
                "followup_question_type을 반드시 null로 두세요."
            )

        answer_mode_rule = (
            "서버 사전 판정은 answered이지만, 최종 분류는 답변 내용을 보고 결정하세요. "
            "학생 답변이 실질적인 내용 없이 모르겠다, 기억나지 않는다, 준비하지 못했다, "
            "배운 적 없다, 넘어가 달라는 뜻을 표현하거나 질문과 무관한 말로 회피한다면 "
            "answer_status를 unknown으로 설정하고 다음 답변 불가 규칙을 따르세요: "
            "verdict는 '확인 필요', strengths는 빈 문자열, gaps에는 발표 전에 질문의 핵심을 "
            "다시 확인하라는 짧은 안내, rubric은 빈 객체, supplement에는 정답 대신 관련 슬라이드와 "
            "기대 답변 요소에서 확인되는 핵심 실마리만 1~2문장, related_slides에는 그 근거 슬라이드 "
            "번호 1~3개를 넣으세요. followup에는 같은 주제를 자료에 직접 나온 기본 개념이나 관계 "
            "한 가지로 낮춘 재질문을 작성하고, followup_question_type에는 그 재질문의 유형을 넣으세요. "
            "안전한 재질문을 만들 수 없을 때만 두 필드를 null로 두세요. "
            "단, '정확하지 않지만', '확실하진 않은데' 같은 불확실 표현이 있어도 "
            "실질적인 답변 내용이 이어지면 unknown이 아니라 answered로 평가하세요. "
            "answered인 경우 supplement는 null, related_slides는 빈 배열로 두세요. "
            "개념의 사용 조건을 수량이나 단순 형태 차이로 잘못 설명했다면 "
            "어떤 기준이 다른지 gaps에 명확히 작성하세요. "
            "직접성은 질문의 핵심에 바로 답했는지, 근거는 질문에서 근거나 설명을 요구한 경우 "
            "그 수준을 충족했는지, 논리는 답변 내부의 설명이 모순 없이 연결되는지를 뜻합니다. "
            "질문이 근거를 요구하지 않았다면 추가 근거가 없다는 이유로 근거를 부족 처리하지 마세요. "
            "각 rubric 값은 부족·보통·우수 중 하나입니다."
        )
        result_rule = (
            "먼저 답변이 위 답변 불가 조건에 해당하는지 판단하고, 해당하면 unknown 규칙을 "
            "우선 적용하세요. 해당하지 않을 때만 아래 기준으로 평가하세요. "
            "답변이 질문의 명시적 요구를 모두 충족하면 verdict는 충분, gaps는 없음으로 작성하세요. "
            "다만 turn이 max_turns보다 작으면 충분한 답변이어도 followup을 반드시 생성하고, "
            "turn이 max_turns 이상일 때만 followup을 null로 두세요. "
            "명시적 요구 일부가 빠졌지만 핵심 방향은 맞으면 verdict는 부분 충족으로 작성하고, "
            "빠진 한 요소만 gaps와 꼬리질문에서 다루세요. "
            "핵심이 틀렸거나 질문의 요구에 실질적으로 답하지 못했다면 verdict는 부족으로 작성하세요. "
            "답변이 부분적으로 맞고 같은 유형으로 다시 물으면 반복이 되는 경우에만 허용된 인접 유형으로 "
            "전환하세요."
        )

    term_hint_text = ""

    if term_hints:
        term_hint_text = (
            "\n[용어 참고]\n"
            + ", ".join(term_hints[:12])
            + "\nSTT 오탈자 가능성만 보정하고 개념 오류로 바로 단정하지 마세요."
        )

    system = (
        f"[페르소나]\n{persona_system}\n\n"
        f"{_QUESTION_CONTRACT_GUIDE}\n"
        f"{difficulty_hint}\n\n"
        f"[현재 질문 유형 평가 규칙]\n{question_type_rule}\n\n"
        f"{_TYPE_TRANSITION_GUIDE}\n"
        "먼저 직전 질문의 명시적 요구를 추출한 뒤 그 범위만 평가하세요. "
        "질문이 두 명칭을 묻고 학생이 두 명칭을 정확히 답했다면 그 답변은 충분합니다. "
        "관련 슬라이드나 expected_answer_points에 역할·절차·근거가 있더라도 질문에서 요구하지 않았다면 "
        "누락으로 처리하지 마세요. "
        "학생의 답변은 정확한 단어 일치가 아니라 의미를 기준으로 평가하세요. "
        "expected_answer_points는 질문 범위 안의 내부 기준일 뿐이며 정답 문구를 그대로 말해야만 "
        "맞는 것으로 보지 마세요. 같은 의미를 자신의 말로 설명하면 인정하세요. "
        "반대로 핵심 개념을 다른 기준으로 오해했다면 짧게 답했더라도 구체적으로 지적하세요. "
        "학생이 말하지 않은 장점이나 자료에 없는 사실을 만들지 마세요. "
        f"{answer_mode_rule} "
        f"{followup_rule} "
        f"{result_rule} "
        "꼬리질문은 한국어 존댓말 한 문장으로 작성하세요.\n"
        'JSON만 반환: {'
        '"answer_status": "answered|unknown", '
        '"verdict": "충분|부분 충족|부족|확인 필요", '
        '"strengths": "<질문 범위 안에서 확인된 강점 또는 빈 문자열>", '
        '"gaps": "<없음 또는 보완 안내>", '
        '"supplement": "<답변 불가 시 핵심 보충 1~2문장 또는 null>", '
        '"related_slides": [<관련 슬라이드 번호 1~3개>], '
        '"followup": "<질문 또는 null>", '
        '"followup_question_type": "evidence|counterexample|application|definition 또는 null", '
        '"rubric": {'
        '"직접성": "부족|보통|우수", '
        '"근거": "부족|보통|우수", '
        '"논리": "부족|보통|우수"'
        "}}"
    )

    answer_status_hint = "unknown" if is_no_answer else "answered"

    user = (
        f"[발표 대본 일부]\n{_format_script(script)[:1600]}\n\n"
        f"[질문 관련 슬라이드]\n{_format_context_slides(slides, context_slides)}\n\n"
        f"[질문 초점]\n{question_focus.strip() or '(명시되지 않음)'}\n\n"
        f"[기대 답변 요소]\n{_format_expected_points(expected_answer_points)}\n\n"
        f"[최초 질문 유형]\n{root_type_text}\n\n"
        f"[현재 질문 유형]\n{question_type_text}\n\n"
        f"[최초 질문]\n{root_question_text[:700]}\n\n"
        f"[직전 질문]\n{question[:700]}\n\n"
        f"[학생 답변]\n{answer[:1800]}\n\n"
        f"[답변 상태 사전 판정]\n{answer_status_hint}\n\n"
        f"[진행]\nturn={turn}, max_turns={max_turns}, difficulty={difficulty}\n\n"
        "관련 슬라이드의 흐름과 기대 답변 요소를 함께 보고 응답 JSON을 작성하세요."
    )

    return system, user


_REVISION_ACTION_GUIDE = """
[수정 행동 유형]

revisions의 각 항목은 다음 네 유형 중 가장 가까운 하나를 action_type으로 선택하세요.
자유 서술이 아니라 실행 가능한 행동 하나로 좁혀야 합니다.

- sentence_split: 한 문장에 여러 정보(개념+근거+예시 등)가 몰려 있어 나눠 말해야 하는 경우
- signal_phrase: "정리하면", "차이점은", "결론부터 말씀드리면" 같은 구조 신호 문장이 없어서
  청중이 흐름을 놓치기 쉬운 경우
- emphasis_shift: 핵심 내용이 문장 뒤쪽이나 부수적인 위치에 묻혀 있어 앞으로 옮겨야 하는 경우
- term_explanation: 전문 용어나 축약된 표현이 풀이 없이 등장해 배경지식이 없는 청중이
  이해하기 어려운 경우
- other: 위 네 유형에 해당하지 않지만 구체적으로 지적할 수 있는 경우에만 사용

같은 관찰에 여러 유형을 섞지 말고, 대본이나 슬라이드 텍스트에서 실제로 확인되는
사실만 observation에 적으세요. 관찰되지 않은 문제를 짐작해서 만들지 마세요.
"""


def build_report_prompt(
    script: str,
    slides: List[Slide],
    transcript: List[TranscriptTurn],
):
    """텍스트 자료만으로 종합 피드백, 슬라이드 커버리지, 구체적 수정 제안을 생성"""
    system = (
        "발표 대본, 슬라이드, 질의응답 텍스트만 근거로 평가하세요. "
        "내용은 근거·구조·결과 해석, "
        "전달은 텍스트의 명확성·용어 설명·설명 순서, "
        "대응은 질문 이해·직접성·근거 제시를 평가합니다. "
        "음성 정보가 없으므로 속도, 억양, 음량, 자신감, 긴장 상태를 추측하지 마세요. "
        "질문별 상세 교정은 별도 화면에 이미 표시되므로, "
        "content_feedback/delivery_feedback/response_feedback은 각각 2문장 이내로 핵심만 간결하게 요약하세요. "
        "슬라이드 핵심이 대본에서 의미 있게 설명됐을 때만 covered=true로 두세요. "
        "covered=false인 슬라이드의 missing_point에는 빠진 항목의 유형을 "
        "수치·정의·근거·방법·결론 중 하나로 밝히고 그 구체적 예시를 함께 적으세요. "
        "예: \"핵심 수치(32% 감소)가 대본에서 설명되지 않았습니다\", "
        "\"핵심 용어(정규화)의 정의가 대본에서 생략됐습니다\". "
        "covered=true이면 missing_point는 null로 두세요.\n"
        f"{_REVISION_ACTION_GUIDE}\n"
        "[revisions 작성 순서]\n"
        "1. 대본과 슬라이드, 질의응답 기록에서 개선 여지가 있는 지점을 최대 4곳 고르세요.\n"
        "2. 각 지점마다 observation(실제 관찰), impact(청중 이해에 미치는 영향), "
        "action_type과 action(구체적 행동), example(대본에 바로 넣을 문장) 순서로 작성하세요.\n"
        "3. 슬라이드 커버리지 미달 지점이 있다면 최소 하나는 그 슬라이드 번호를 "
        "slide_index로 지정하고, 그 슬라이드의 누락 핵심을 채우는 문장을 example로 제시하세요.\n"
        "4. 답변 대응이 약했던 지점이 있다면 최소 하나는 그 질문과 관련된 revision을 만드세요.\n"
        "5. 근거 없이 만든 문제를 지적하지 말고, 실제로 확인 가능한 지점이 4개보다 적으면 "
        "그 개수만큼만 작성하세요.\n\n"
        "answer_structure_tip에는 질의응답 대응 기록을 바탕으로 결론→근거→한계(또는 예외) "
        "순서로 답하는 습관을 권장하는 한국어 2~3문장을 작성하세요. "
        "특정 질문에 실제로 부족했던 부분이 있었다면 그 사례를 근거로 구체적으로 설명하세요.\n"
        'JSON만 반환: {"content_feedback": "<내용>", '
        '"delivery_feedback": "<텍스트 기준 전달>", '
        '"response_feedback": "<대응>", '
        '"slide_coverage": ['
        '{"index": 1, "covered": true, "missing_point": null}'
        "], "
        '"revisions": ['
        '{"slide_index": <정수 또는 null>, '
        '"observation": "<대본·슬라이드에서 확인된 사실 1문장>", '
        '"impact": "<청중 이해에 미치는 영향 1문장>", '
        '"action_type": "sentence_split|signal_phrase|emphasis_shift|term_explanation|other", '
        '"action": "<구체적 행동 1문장>", '
        '"example": "<대본에 추가·수정할 한국어 문장 예시>"}'
        "], "
        '"answer_structure_tip": "<결론-근거-한계 순서 권장 안내 2~3문장>"'
        "}"
    )

    transcript_text = "\n".join(
        (
            f"[{turn.persona_id}] 질문 유형: {turn.question_type or 'unknown'}\n"
            f"질문: {turn.question}\n"
            f"답변: {turn.answer}\n"
            f"답변 상태: {turn.answer_status}\n"
            f"부족: {turn.gaps}\n"
            f"보충 힌트: {turn.supplement or '없음'}\n"
            f"관련 슬라이드: {', '.join(map(str, turn.related_slides)) or '없음'}"
        )
        for turn in transcript
    ) or "(질의응답 기록 없음)"

    user = (
        f"[발표 대본]\n{_format_script(script)}\n\n"
        f"[슬라이드]\n{_format_slides(slides)}\n\n"
        f"[질의응답]\n{transcript_text}\n\n"
        "모든 슬라이드를 index 순서대로 포함해 평가하세요."
    )

    return system, user