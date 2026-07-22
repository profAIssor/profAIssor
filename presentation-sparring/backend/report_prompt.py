"""자료 유무와 음성 지표를 구분하는 종합 리포트 프롬프트 생성."""

from typing import List

from schemas import Slide, TranscriptTurn


_SOURCE_TERM_RULE = """
[원문 용어 보존 규칙]
슬라이드나 대본에 영어로 적힌 기술 용어, 프로토콜명, 모드명,
알고리즘명, API·표준 명칭, 약어, 코드, 수식은 원문 철자와 대소문자를
그대로 유지하세요. 한국어 번역어·음역어·의역어로 바꾸지 마세요.
예를 들어 슬라이드의 "intention lock mode"를 임의로
"의도 잠금 모드"로 바꾸지 마세요.
"""

_REVISION_ACTION_GUIDE = """
[수정 행동 유형]

revisions의 각 항목은 다음 유형 중 가장 가까운 하나를 선택하세요.

- sentence_split: 한 문장에 여러 정보가 몰려 있어 나눠야 하는 경우
- signal_phrase: 구조 신호 문장이 없어 흐름을 놓치기 쉬운 경우
- emphasis_shift: 핵심 내용이 뒤쪽이나 부수적인 위치에 묻힌 경우
- term_explanation: 전문 용어나 축약 표현이 풀이 없이 등장한 경우
- other: 위 유형에 해당하지 않지만 구체적으로 수정할 수 있는 경우

revisions는 반드시 사용자가 제출한 발표 대본의 실제 문장만 근거로
작성하세요. observation에는 발표 대본에서 그대로 복사한 원문 문장 또는
10자 이상의 연속된 원문 구절을 넣고, 이를 바꾸어 말하지 마세요.
질의응답에서 학생이 말한 답변을 발표 대본 문장처럼 수정하지 마세요.
슬라이드는 대본과의 맥락 확인에만 사용할 수 있습니다.
"""


def _format_slides(slides: List[Slide]) -> str:
    """슬라이드 목록의 번호 순서 변환."""
    if not slides:
        return "(제출된 슬라이드 없음)"

    return "\n".join(
        f"[슬라이드 {slide.index}] {slide.text}"
        for slide in sorted(
            slides,
            key=lambda item: item.index,
        )
    )


def _format_script(script: str) -> str:
    """발표 대본의 프롬프트용 변환."""
    return script if script.strip() else "(제출된 발표 대본 없음)"


def _format_transcript(
    transcript: List[TranscriptTurn],
) -> str:
    """원질문과 쉬운 재질문을 함께 보존한 질의응답 기록 변환."""
    blocks: List[str] = []

    for turn in transcript:
        lines = [
            f"[{turn.persona_id}]",
            f"질문 유형: {turn.question_type or 'unknown'}",
            f"원질문: {turn.question}",
            f"첫 답변: {turn.answer}",
        ]

        if turn.retry_question:
            lines.extend(
                [
                    f"제공한 힌트: {turn.supplement or '없음'}",
                    f"쉬운 재질문: {turn.retry_question}",
                    f"재답변: {turn.retry_answer or '(답변 없음)'}",
                ]
            )

        if turn.final_explanation:
            lines.append(f"최종 개념 설명: {turn.final_explanation}")

        lines.extend(
            [
                f"최종 답변 상태: {turn.answer_status}",
                "최종 평가 축: "
                + (
                    ", ".join(
                        f"{axis}={value}"
                        for axis, value in turn.rubric.items()
                    )
                    or "없음"
                ),
                f"최종 보완점: {turn.gaps}",
                "관련 슬라이드: "
                f"{', '.join(map(str, turn.related_slides)) or '없음'}",
            ]
        )
        blocks.append("\n".join(lines))

    return "\n\n".join(blocks) or "(질의응답 기록 없음)"


def _build_speech_rule(
    speech_context: str,
) -> str:
    """음성 지표 유무에 따른 출력 제한 규칙 생성."""
    if not speech_context.strip():
        return (
            "[음성 답변 코칭 규칙]\n"
            "검증된 음성 지표가 제공되지 않았습니다. "
            "속도, 멈춤, 음량, 억양, 강세, 자신감, 긴장 상태를 "
            "추측하지 마세요. "
            "speech_delivery_feedback은 빈 문자열로 작성하세요."
        )

    return (
        "[음성 답변 코칭 규칙]\n"
        "speech_delivery_feedback은 [검증된 음성 지표]의 판정만 "
        "근거로 작성하세요. 제공되지 않은 억양, 피치, 단어별 강세, "
        "자신감, 긴장, 감정 상태를 추측하지 마세요. "
        "필러 수는 실제 총횟수가 아니라 명확히 인식된 최소 횟수입니다. "
        "새 수치를 만들거나 기존 수치를 바꾸지 마세요. "
        "리포트 화면에 수치가 따로 표시되므로 수치를 반복하지 말고 "
        "다음 답변에서 실행할 행동 조언만 한국어 1~2문장으로 작성하세요."
    )


def _build_material_rule(
    *,
    has_script: bool,
    has_slides: bool,
) -> str:
    """대본·슬라이드 유무별 평가 가능 범위 생성."""
    if has_script and has_slides:
        return (
            "[자료 평가 범위]\n"
            "- content_feedback: 대본의 핵심 내용과 슬라이드의 일치·누락 평가\n"
            "- delivery_feedback: 대본 문장의 명확성·용어 설명·설명 순서 평가\n"
            "- slide_coverage: 모든 슬라이드와 대본을 비교해 작성\n"
            "- revisions: 발표 대본 문장만 대상으로 작성"
        )

    if has_script:
        return (
            "[자료 평가 범위]\n"
            "슬라이드가 제공되지 않았습니다.\n"
            "- content_feedback: 대본 자체의 내용 구조를 평가하되, "
            "슬라이드와의 일치 여부는 판단할 수 없다고 명시\n"
            "- delivery_feedback: 대본 문장의 명확성·용어 설명·설명 순서 평가\n"
            "- slide_coverage: 빈 배열\n"
            "- revisions: 발표 대본 문장만 대상으로 작성"
        )

    return (
        "[자료 평가 범위]\n"
        "발표 대본이 제공되지 않았습니다.\n"
        "- content_feedback: 대본이 없어 발표 내용 전달을 평가하지 못했다고 작성\n"
        "- delivery_feedback: 대본이 없어 문장 명확성·설명 순서를 평가하지 못했다고 작성\n"
        "- response_feedback: 질의응답 기록만 근거로 평가\n"
        "- slide_coverage: 빈 배열\n"
        "- revisions: 빈 배열\n"
        "슬라이드 내용을 발표자가 실제로 말한 것으로 간주하지 마세요."
    )


def build_report_prompt(
    script: str,
    slides: List[Slide],
    transcript: List[TranscriptTurn],
    *,
    speech_context: str = "",
):
    """텍스트 자료와 검증된 음성 신호 기반 종합 리포트 생성."""
    has_script = bool(script.strip())
    has_slides = bool(slides)
    speech_rule = _build_speech_rule(speech_context)
    material_rule = _build_material_rule(
        has_script=has_script,
        has_slides=has_slides,
    )

    system = (
        "발표 대본, 슬라이드, 질의응답 기록과 서버가 판정한 "
        "검증된 음성 신호만 근거로 평가하세요.\n\n"
        f"{_SOURCE_TERM_RULE}\n"
        f"{material_rule}\n\n"
        f"{speech_rule}\n\n"
        f"{_REVISION_ACTION_GUIDE}\n"
        "[답변별 참고 답변 규칙]\n"
        "answer_coaching은 질의응답 기록의 각 질문 슬롯에 대해 작성하세요.\n"
        "- turn_index는 질의응답 기록의 0부터 시작하는 순번입니다.\n"
        "- 최종 답변 상태가 answered이고 직접성·근거·논리 평가가 모두 "
        "'우수'인 경우 reference_answer는 null입니다.\n"
        "- 위 조건을 충족하지 못하는 모든 경우에는 reference_answer를 "
        "반드시 작성하세요. 즉 하나라도 '보통' 또는 '부족'이거나, "
        "평가 축이 비어 있거나, 답변 상태가 unknown이면 참고 답변이 필요합니다.\n"
        "- 쉬운 재질문이 있는 경우 최초의 '잘 모르겠습니다' 답변이 아니라 "
        "retry_question과 retry_answer를 기준으로 참고 답변을 작성하세요.\n"
        "- reference_answer는 발표 대본과 관련 슬라이드만 근거로 질문에 직접 "
        "답하는 1~3문장의 완결된 참고 답변이어야 합니다.\n"
        "- 학생 답변을 단순히 문장만 다듬지 말고, 최종 평가에서 부족했던 "
        "핵심 내용을 보충하세요.\n"
        "- 발표 자료에 없는 사실을 추가하지 말고 영문 기술 용어는 원문을 유지하세요.\n"
        "[공통 평가 규칙]\n"
        "response_feedback은 원질문과 쉬운 재질문을 포함한 질의응답 기록에서 "
        "질문 이해, 직접성, 근거 제시, 재학습 필요 항목을 요약하세요.\n"
        "content_feedback, delivery_feedback, response_feedback은 "
        "각각 한국어 2문장 이내로 작성하세요.\n"
        "질의응답 답변을 발표 대본으로 간주하지 마세요.\n"
        "answer_structure_tip은 질의응답 기록을 바탕으로 "
        "결론→근거→한계 또는 예외 순서의 답변 습관을 2~3문장으로 작성하세요.\n"
        "자료가 없어서 판단할 수 없는 항목을 추측하지 마세요.\n\n"
        'JSON만 반환: {'
        '"content_feedback": "<내용 또는 판단 불가 안내>", '
        '"delivery_feedback": "<대본 전달 또는 판단 불가 안내>", '
        '"response_feedback": "<질의응답 대응>", '
        '"speech_delivery_feedback": "<음성 행동 조언 또는 빈 문자열>", '
        '"slide_coverage": ['
        '{"index": 1, "covered": true, "missing_point": null}'
        "], "
        '"revisions": ['
        '{"slide_index": <정수 또는 null>, '
        '"observation": "<대본 원문 문장 또는 10자 이상 원문 구절>", '
        '"impact": "<청중 이해 영향>", '
        '"action_type": '
        '"sentence_split|signal_phrase|emphasis_shift|'
        'term_explanation|other", '
        '"action": "<구체적 수정 행동>", '
        '"example": "<대본 수정 예시>"}'
        "], "
        '"answer_coaching": ['
        '{"turn_index": 0, '
        '"reference_answer": "<참고 답변 또는 null>"}'
        "], "
        '"answer_structure_tip": "<답변 구조 안내>"'
        "}"
    )

    user = (
        f"[발표 대본]\n{_format_script(script)}\n\n"
        f"[슬라이드]\n{_format_slides(slides)}\n\n"
        f"[질의응답]\n{_format_transcript(transcript)}\n\n"
        "[검증된 음성 지표]\n"
        f"{speech_context.strip() or '(없음)'}\n\n"
        "위 자료 유무와 평가 가능 범위를 지켜 JSON을 작성하세요. "
        "revisions는 발표 대본 원문만 대상으로 작성하세요. "
        "answer_coaching은 모든 평가 축이 우수하지 않은 질문의 "
        "참고 답변만 작성하세요. 영문 전공 용어와 고유 명칭은 원문 그대로 유지하세요."
    )

    return system, user