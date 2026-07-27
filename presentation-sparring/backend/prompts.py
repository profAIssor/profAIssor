from typing import List, Sequence

from schemas import Slide


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


_SEMANTIC_EQUIVALENCE_GUIDE = """
[의미 동등성 판정 절차]

일반 평가를 작성하기 전에 기대 답변 요소별로 다음 절차를 반드시 수행하세요.

1. 각 expected_answer_point를 정답 문구가 아니라 독립된 원자 명제로 해석하세요.
2. 학생 답변에서 그 명제를 직접 말했거나 문맥상 필연적으로 함의하는 짧은 원문 구절을 찾으세요.
3. 동의어, 바꿔 말하기, 능동·수동 전환뿐 아니라 구체적인 작동 방식이나 사례가 상위 개념을
   명백히 함의하는 경우도 충족으로 인정하세요. 상위 개념의 문구를 그대로 반복하도록 요구하지 마세요.
4. 같은 단어가 등장했다는 이유만으로는 충족이 아닙니다. 답변의 실제 명제가 기대 요소와
   논리적으로 같은 내용인지 확인하세요.
5. 의미상 충족된 요소는 gaps에 누락으로 적지 마세요.
   근거 구절을 찾을 수 없는 요소만 미충족으로 판단하세요.

예를 들어 기대 요소가 "전체 토큰 쌍 대신 일부 토큰 관계만 계산한다"이고 학생이
"인접한 토큰끼리만 상호작용해 주변 K개의 토큰만 계산한다"고 답했다면,
국소적인 계산 방식이 일부 관계만 선택한다는 상위 개념을 필연적으로 함의하므로 충족입니다.

학생 답변은 음성 인식(STT) 전사일 수 있습니다. 평가 전에 질문, 관련 슬라이드, 용어 참고를 이용해
조사·어미·띄어쓰기와 문맥상 명백한 음성 오인식을 내부적으로 복원하세요.
예를 들어 문맥이 뒷받침하면 "주변 케익의 토큰"을 "주변 K개의 토큰"으로 해석할 수 있습니다.
전사 표현이 발표 자료의 용어와 다르더라도 질문·관련 슬라이드·주변 문맥을 함께 보았을 때
하나의 원문 용어로만 해석된다면 그 용어로 복원해 의미를 평가하세요.
strengths와 gaps는 사용자가 바로 이해할 수 있는 자기완결적인 한국어 평가여야 합니다.
자료·답변의 원문 문장, 조건식, 식별자, 기호를 그대로 붙여 넣어 부족한 점을 대신 설명하지 마세요.
기술 용어·고유 명칭은 꼭 필요할 때만 원문 표기를 유지하되, 그 용어가 이 질문에서 어떤 개념·관계·조건과
연결되는지 한국어로 설명하세요. 문맥만으로 역할을 확정할 수 없는 표기는 평가에 사용하거나 임의로 해석하지 마세요.
answer_evidence만 내부 검증용으로 학생 답변에서 그대로 복사한 짧은 원문 구절을 사용하세요. 이는 사용자에게 보이는
strengths와 gaps의 문체를 결정하는 근거가 아닙니다.
다만 문맥으로 확정할 수 없는 누락된 주장이나 근거를 새로 만들어 답변에 보태지는 마세요.
복원 후보가 둘 이상이거나 자료에서 근거를 찾을 수 없다면 임의로 정답 처리하지 말고 표현이 모호하다고 판단하세요.
"""


_DIFFICULTY_HINTS = {
    "easy": (
        "[난이도: 쉬움 — 발표 이해 확인]\n"
        "목적은 발표자가 자료의 핵심 개념, 흐름, 각 요소의 역할을 제대로 이해했는지 확인하는 것입니다. "
        "전체 자료를 읽되 질문은 1~2개 슬라이드에서 직접 확인되는 핵심 용어, 절차, 역할 또는 "
        "개념 간 직접 관계 하나만 다루세요. 발표자가 1~2문장으로 답할 수 있어야 하며, "
        "외부 지식, 숨은 전제, 다른 환경의 적용, 실패 조건은 요구하지 마세요. "
        "정의 확인형은 핵심 의미·역할·직접 차이 하나를, 근거 요구형은 자료에 명시된 이유나 근거 하나를 확인하세요."
    ),
    "medium": (
        "[난이도: 보통 — 발표 설명 검증]\n"
        "목적은 발표의 주장과 설명이 타당한지, 발표자가 왜 그렇게 설명했는지와 개념들이 어떻게 연결되는지를 "
        "말할 수 있는지 확인하는 것입니다. 직접 관련된 2~3개 슬라이드 또는 개념 두 개를 연결하되 추론은 한 단계로 제한하세요. "
        "질문은 주장과 근거의 연결, 두 개념의 관계, 선택한 방법의 이유, 자료 안의 조건 중 하나를 분명히 요구해야 합니다. "
        "단순 명칭이나 정의만 다시 묻지 마세요. 자료에 없는 실제 환경, 복수의 가정, 실패 조건의 종합 검토는 어려움으로 남기세요."
    ),
    "hard": (
        "[난이도: 어려움 — 실제 적용 검토]\n"
        "목적은 발표 내용을 응용 분야나 실제 환경에 적용할 수 있는지, 필요한 전제와 통제 조건을 꼼꼼히 파악했는지 확인하는 것입니다. "
        "발표 전체 또는 하나의 완결된 단원 흐름을 바탕으로 적용 조건, 환경 차이, 실패 조건, 한계, 통제 변수 중 하나를 깊게 검증하세요. "
        "근거 요구형은 일반화 가능성이나 전제의 타당성을, 반례 제시형은 결론이 깨지는 조건을, "
        "확장 적용형은 다른 환경에서 성립하기 위한 조건이나 조정점을 물으세요. "
        "외부 사례가 불확실하면 실제 사실처럼 말하지 말고 하나의 가정형 상황으로 명시하세요. "
        "여러 약점이나 요구 사항을 한 질문에 결합하지 말고 가장 중요한 조건 하나만 깊게 다루세요."
    ),
}


_EVALUATION_DIFFICULTY_HINTS = {
    "easy": (
        "[쉬움 평가 기준] 발표 자료에 직접 나온 핵심 의미, 흐름, 역할을 이해했는지만 질문의 범위 안에서 평가하세요. "
        "명칭·항목·직접 관계를 묻는 질문은 정확한 답만 제시해도 충분하며, "
        "추가 근거나 실제 적용 조건이 없다는 이유로 감점하지 마세요."
    ),
    "medium": (
        "[보통 평가 기준] 질문이 요구한 주장·근거·개념 관계·선택 이유 중 한 가지를 실제로 연결해 설명했는지 평가하세요. "
        "질문에 없는 실제 환경의 한계나 통제 변수까지 추가로 요구하지 마세요."
    ),
    "hard": (
        "[어려움 평가 기준] 질문에 명시된 실제 적용 조건, 환경 차이, 실패 조건, 한계, 통제 변수 중 "
        "한 가지를 자료 근거와 함께 검토했는지 평가하세요. 질문에 없는 다른 한계·절차·사례를 "
        "추가로 말하지 않았다는 이유로 감점하지 마세요."
    ),
}


_QUESTION_TYPE_EVALUATION_RULES = {
    "evidence": (
        "현재 질문은 근거 요구형입니다. 주장에 직접 답했는지와 제시한 근거가 "
        "해당 주장과 실제로 연결되는지를 평가하세요."
    ),
    "counterexample": (
        "현재 질문은 반례 제시형입니다. 제시된 예외 조건을 이해했는지, "
        "그 조건에서 기존 결론이나 규칙이 어떻게 달라지는지 답했는지를 평가하세요."
    ),
    "application": (
        "현재 질문은 확장 적용형입니다. 자료의 규칙이나 주장을 해당 예시·상황에 "
        "적용할 수 있는지와 필요한 판단 또는 조건을 설명했는지 평가하세요."
    ),
    "definition": (
        "현재 질문은 정의 확인형입니다. 핵심 개념의 의미, 역할, 범위 또는 개념 간 차이를 "
        "질문 수준에 맞게 설명했는지 평가하세요."
    ),
}


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
    indexed_points = [
        (index, point.strip())
        for index, point in enumerate(expected_answer_points or [])
        if isinstance(point, str) and point.strip()
    ]

    if not indexed_points:
        return "(명시된 기대 답변 요소 없음 — 질문과 관련 슬라이드에서 판단)"

    return "\n".join(
        f"- [{index}] {point}"
        for index, point in indexed_points[:3]
    )


def build_question_prompt(
    persona_system: str,
    script: str,
    slides: List[Slide],
    difficulty: str = "medium",
    question_type_priority: Sequence[str] | None = None,
    excluded_questions: List[str] | None = None,
    language: str = "ko",
):
    """전체 자료 흐름을 바탕으로 유형과 내부 평가 맥락이 있는 최초 질문을 생성합니다."""
    difficulty_hint = _DIFFICULTY_HINTS.get(
        difficulty,
        _DIFFICULTY_HINTS["medium"],
    )

    priority_text = _format_question_type_priority(question_type_priority)
    if language == "en":
        output_language_rule = (
            "[Output language]\n"
            "Treat the presentation script and slides as English material. Write question, question_focus, "
            "and expected_answer_points in natural English. Ask one polite English question. Preserve technical "
            "terms exactly as written in the source. Set speech_term_aliases to an empty array because English "
            "speech recognition uses the source terms directly."
        )
    else:
        output_language_rule = (
            "[출력 언어]\n"
            "question, question_focus, expected_answer_points는 자연스러운 한국어로 작성하세요. "
            "질문은 한국어 존댓말 한 문장으로 작성하세요. speech_term_aliases에는 원문의 영문 기술 용어와 "
            "ko-KR 발음·흔한 STT 변형만 넣고, 없으면 빈 배열로 두세요."
        )

    system = (
        f"[페르소나]\n{persona_system}\n\n"
        f"{_MATERIAL_FLOW_GUIDE}\n"
        f"{_QUESTION_TYPE_GUIDE}\n"
        f"{_QUESTION_CONTRACT_GUIDE}\n"
        f"[질문 유형 우선순위]\n{priority_text}\n\n"
        f"{difficulty_hint}\n\n"
        f"{output_language_rule}\n\n"
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
        "쉬움은 이해한 의미·흐름·역할을, 보통은 왜 그런지·어떻게 연결되는지를, "
        "어려움은 실제 적용에 필요한 조건·한계를 처음부터 물으세요. "
        "명칭만 묻고 평가 단계에서 역할 설명을 추가로 요구하는 질문은 만들지 마세요. "
        "expected_answer_points는 자료에서 확인 가능한 핵심 요소 중 질문 문장이 직접 요구한 것만 1~3개 작성하세요. "
        "학생에게 보이지 않는 내부 평가 기준이라는 이유로 질문보다 넓은 범위를 넣지 마세요. "
        "context_slides는 질문을 이해하고 평가하는 데 실제로 필요한 슬라이드 번호만 오름차순으로 넣으세요. "
        "targets_slide는 질문과 가장 직접적으로 연결된 대표 슬라이드 한 장의 번호이며 없으면 null입니다. "
        "speech_term_aliases는 출력 언어 규칙을 따르세요.\n"
        'JSON만 반환: {'
        '"question": "<질문 한 문장>", '
        '"question_type": "evidence|counterexample|application|definition", '
        '"targets_slide": <정수 또는 null>, '
        '"question_focus": "<검증할 핵심 주제>", '
        '"context_slides": [<관련 슬라이드 번호 1~3개>], '
        '"expected_answer_points": ["<자료 기반 핵심 요소 1>", "<선택 요소 2>"], '
        '"speech_term_aliases": ['
        '{"canonical": "<자료 원문의 영문 용어>", '
        '"aliases": ["<한글 발음 표기 1>", "<선택 발음 표기 2>"]}'
        "]"
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
    term_hints: List[str] | None = None,
    difficulty: str = "medium",
    root_question: str | None = None,
    root_question_type: str | None = None,
    question_type: str | None = None,
    question_focus: str = "",
    context_slides: List[int] | None = None,
    expected_answer_points: List[str] | None = None,
    language: str = "ko",
):
    """자료 맥락을 참고해 답변 내용만 평가합니다."""
    difficulty_hint = _EVALUATION_DIFFICULTY_HINTS.get(
        difficulty,
        _EVALUATION_DIFFICULTY_HINTS["medium"],
    )
    if language == "en":
        output_language_rule = (
            "[Output language]\n"
            "Interpret the student's answer as an English presentation answer, but write strengths, gaps, and every "
            "user-visible evaluation or coaching explanation in natural Korean. Preserve English source technical "
            "terms exactly only when they are needed in the explanation. Do not use raw source sentences, formulas, "
            "or unexplained notation as visible feedback. Only answer_evidence is an internal exact source excerpt. "
            "For server "
            "compatibility, keep answer_status, verdict, rubric keys, and rubric values in the exact enumerated "
            "forms required by the JSON schema."
        )
    else:
        output_language_rule = (
            "[출력 언어]\n학생에게 보이는 설명은 자연스러운 한국어로 작성하세요."
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

    answer_mode_rule = (
        "서버의 명시적 무응답 판정은 이미 별도 처리됐지만, 최종 분류는 답변 내용을 보고 결정하세요. "
        "학생 답변이 실질적인 내용 없이 모르겠다, 기억나지 않는다, 준비하지 못했다, "
        "배운 적 없다, 넘어가 달라는 뜻을 표현하거나 질문과 무관한 말로 회피한다면 "
        "answer_status를 unknown으로 설정하세요. 이때 verdict는 '확인 필요', "
        "strengths는 빈 문자열, gaps에는 발표 전에 질문의 핵심을 다시 확인하라는 짧은 안내, "
        "rubric은 빈 객체로 두세요. "
        "단, '정확하지 않지만', '확실하진 않은데' 같은 불확실 표현 뒤에 실질적인 답변이 이어지면 "
        "unknown이 아니라 answered로 평가하세요. "
        "개념의 사용 조건을 수량이나 단순 형태 차이로 잘못 설명했다면 어떤 기준이 다른지 "
        "gaps에 명확히 작성하세요. 직접성은 질문의 핵심에 바로 답했는지, 근거는 질문에서 "
        "근거나 설명을 요구한 수준을 충족했는지, 논리는 답변 내부의 설명이 모순 없이 "
        "연결되는지를 뜻합니다. 질문이 근거를 요구하지 않았다면 추가 근거가 없다는 이유로 "
        "근거를 부족 처리하지 마세요. verdict가 '부분 충족'이면 rubric 세 축을 모두 "
        "'부족'으로 두지 마세요. 답변의 핵심 방향이나 일부 설명을 strengths로 인정했다면 "
        "직접성은 최소 '보통'이어야 합니다. 핵심 요소 하나가 빠졌다는 사실만으로 논리까지 "
        "'부족'으로 중복 감점하지 말고, 실제 모순이나 연결 단절이 있을 때만 논리를 "
        "'부족'으로 평가하세요. 각 rubric 값은 부족·보통·우수 중 하나입니다."
    )
    result_rule = (
        "먼저 답변 불가 조건을 판단하고, 해당하면 unknown 규칙을 우선 적용하세요. "
        "그렇지 않고 질문의 명시적 요구를 모두 충족하면 verdict는 충분, gaps는 없음으로 "
        "작성하세요. 일부가 빠졌지만 핵심 방향은 맞으면 verdict는 부분 충족으로 작성하고 "
        "빠진 한 요소만 gaps에서 다루세요. 핵심이 틀렸거나 질문의 요구에 실질적으로 "
        "답하지 못했다면 verdict는 부족으로 작성하세요."
    )

    term_hint_text = (
        ", ".join(term_hints[:12])
        if term_hints
        else "(별도 용어 힌트 없음)"
    )

    system = (
        f"[페르소나]\n{persona_system}\n\n"
        f"{_QUESTION_CONTRACT_GUIDE}\n"
        f"{_SEMANTIC_EQUIVALENCE_GUIDE}\n"
        f"{difficulty_hint}\n\n"
        f"{output_language_rule}\n\n"
        f"[현재 질문 유형 평가 규칙]\n{question_type_rule}\n\n"
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
        f"{result_rule} "
        'JSON만 반환: {'
        '"answer_status": "answered|unknown", '
        '"verdict": "충분|부분 충족|부족|확인 필요", '
        '"strengths": "<질문 범위 안에서 확인된 강점 또는 빈 문자열>", '
        '"gaps": "<없음 또는 보완 안내>", '
        '"expected_point_assessments": ['
        '{"point_index": <0부터 시작하는 기대 요소 번호>, '
        '"covered": <true|false>, '
        '"answer_evidence": "<covered=true이면 학생 답변의 짧은 원문 구절, 아니면 빈 문자열>"}'
        "], "
        '"rubric": {'
        '"직접성": "부족|보통|우수", '
        '"근거": "부족|보통|우수", '
        '"논리": "부족|보통|우수"'
        "}}"
    )

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
        f"[용어 참고]\n{term_hint_text}\n\n"
        "기대 답변 요소마다 목록에 표시된 번호를 point_index로 사용해 "
        "expected_point_assessments를 빠짐없이 작성하세요. "
        "covered=true의 answer_evidence는 해석하거나 고쳐 쓴 문장이 아니라 학생 답변에서 "
        "그대로 옮긴 짧은 구절이어야 합니다. 기대 답변 요소가 없거나 answer_status가 unknown이면 "
        "expected_point_assessments는 빈 배열로 두세요. "
        "마지막으로 의미상 충족된 요소가 gaps에 들어가지 않았는지 다시 확인한 뒤 응답 JSON을 작성하세요."
    )

    return system, user
