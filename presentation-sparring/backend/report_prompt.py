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
사용자에게 보이는 내용·전달·질의응답 피드백과 답변 구조 조언은
자기완결적인 한국어 설명으로 작성하세요. 원문 문장·조건식·식별자·기호를
그대로 붙여 넣어 평가를 대신하지 마세요. 원문 용어가 꼭 필요할 때만
표기를 유지하고, 그 용어가 문맥에서 어떤 역할을 하는지 한국어로 설명하세요.
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

        # 질문이 겨눈 핵심과 자료 기준 기대 요소.
        # 참고 답변이 사용자 답변을 되풀이하지 않고, 미충족 요소를
        # 자료 근거로 보충하도록 판단 재료를 함께 제공한다.
        if turn.question_focus.strip():
            lines.append(f"질문 초점: {turn.question_focus.strip()}")
        expected_points = [
            point.strip()
            for point in turn.expected_answer_points
            if point.strip()
        ]
        if expected_points:
            lines.append(
                "자료 기준 기대 요소: "
                + " / ".join(expected_points[:4])
            )

        if turn.retry_question:
            lines.extend(
                [
                    f"제공한 자료 기반 답변: {turn.supplement or '없음'}",
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
            "- revisions: 발표 대본 문장만 대상으로 작성"
        )

    if has_script:
        return (
            "[자료 평가 범위]\n"
            "슬라이드가 제공되지 않았습니다.\n"
            "- content_feedback: 대본 자체의 내용 구조를 평가하되, "
            "슬라이드와의 일치 여부는 판단할 수 없다고 명시\n"
            "- delivery_feedback: 대본 문장의 명확성·용어 설명·설명 순서 평가\n"
            "- revisions: 발표 대본 문장만 대상으로 작성"
        )

    return (
        "[자료 평가 범위]\n"
        "발표 대본이 제공되지 않았습니다.\n"
        "- content_feedback: 대본이 없어 발표 내용 전달을 평가하지 못했다고 작성\n"
        "- delivery_feedback: 대본이 없어 문장 명확성·설명 순서를 평가하지 못했다고 작성\n"
        "- response_feedback: 질의응답 기록만 근거로 평가\n"
        "- revisions: 빈 배열\n"
        "슬라이드 내용을 발표자가 실제로 말한 것으로 간주하지 마세요."
    )


def build_report_prompt(
    script: str,
    slides: List[Slide],
    transcript: List[TranscriptTurn],
    *,
    language: str = "ko",
):
    """대본·슬라이드·질의응답 기반 텍스트 리포트 생성."""
    has_script = bool(script.strip())
    has_slides = bool(slides)
    material_rule = _build_material_rule(
        has_script=has_script,
        has_slides=has_slides,
    )
    output_language_rule = (
        "Write all report analysis, feedback, coaching, revision guidance, examples, missing-point explanations, "
        "and answer_structure_tip in natural Korean. Preserve submitted wording in observation fields and keep "
        "English technical terms exact only when needed for the explanation. Do not use raw source sentences, "
        "formulas, or unexplained notation as user-facing feedback. Only answer_coaching.reference_answer must be written "
        "in natural English."
        if language == "en"
        else "사용자에게 보이는 리포트 내용은 자연스러운 한국어로 작성하세요."
    )

    system = (
        "발표 대본, 슬라이드와 질의응답 기록만 근거로 평가하세요. "
        "음성 전달 코칭은 별도 단계에서 생성하므로 추측하거나 출력하지 마세요.\n\n"
        f"{_SOURCE_TERM_RULE}\n"
        f"{material_rule}\n\n"
        f"[출력 언어]\n{output_language_rule}\n\n"
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
        "- 참고 답변을 만드는 절차를 지키세요. 먼저 '자료 기준 기대 요소'와 "
        "'최종 보완점'을 확인해 학생 답변에서 빠졌거나 어긋난 부분을 파악하세요. "
        "그다음 그 부분을 발표 대본과 관련 슬라이드의 실제 내용으로 채운 답을 쓰세요.\n"
        "- 학생이 이미 말한 내용을 다른 표현으로 되풀이하기만 하면 안 됩니다. "
        "학생 답변에 없던 근거, 기준, 인과관계, 수치, 절차 중 보완점이 요구한 것을 "
        "반드시 새로 포함하세요. 학생 답변을 문장만 다듬은 결과는 실패로 간주합니다.\n"
        "- '최종 보완점'에 시간·비용·원인·조건처럼 여러 내용 축이 적혀 있으면 "
        "그 축을 하나도 빠뜨리지 말고 실제 답변 안에서 각각 설명하세요. "
        "최종 보완점의 핵심 명사를 참고 답변에도 직접 쓰고, 각 명사에 대응하는 "
        "자료 기준 기대 요소를 연결하세요. 보완점의 단어만 되풀이하지 말고 "
        "자료가 제시한 원인·절차·비교 기준과 그 결과를 함께 붙이세요.\n"
        "- '자료 기준 기대 요소'가 제시되면 그중 학생 답변에서 확인되지 않은 요소를 "
        "우선 채우세요. 다만 자료에 근거가 없으면 억지로 지어내지 말고, 자료로 "
        "설명할 수 있는 범위까지만 보충하세요.\n"
        "- 발표 자료에 없는 사실을 추가하지 말고 영문 기술 용어는 원문을 유지하세요.\n"
        "[공통 평가 규칙]\n"
        "response_feedback은 원질문과 쉬운 재질문을 포함한 질의응답 기록에서 "
        "질문 이해, 직접성, 근거 제시, 재학습 필요 항목을 요약하세요.\n"
        "content_feedback, delivery_feedback, response_feedback은 "
        "각각 출력 언어에 맞춰 2문장 이내로 작성하세요.\n"
        "질의응답 답변을 발표 대본으로 간주하지 마세요.\n"
        "answer_structure_tip은 질의응답 기록을 바탕으로 "
        "결론→근거→한계 또는 예외 순서의 답변 습관을 2~3문장으로 작성하세요.\n"
        "자료가 없어서 판단할 수 없는 항목을 추측하지 마세요.\n\n"
        'JSON만 반환: {'
        '"content_feedback": "<내용 또는 판단 불가 안내>", '
        '"delivery_feedback": "<대본 전달 또는 판단 불가 안내>", '
        '"response_feedback": "<질의응답 대응>", '
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
        "위 자료 유무와 평가 가능 범위를 지켜 JSON을 작성하세요. "
        "revisions는 발표 대본 원문만 대상으로 작성하세요. "
        "answer_coaching은 모든 평가 축이 우수하지 않은 질문의 "
        "참고 답변만 작성하세요. 영문 전공 용어와 고유 명칭은 원문 그대로 유지하세요."
    )

    return system, user


def build_slide_coverage_prompt(
    script: str,
    slides: List[Slide],
):
    """대본과 모든 슬라이드의 포함 여부만 짧게 판정."""
    system = (
        "발표 대본이 각 슬라이드의 핵심 내용을 실제로 설명했는지만 판정하세요. "
        "단순히 같은 단어가 있는지가 아니라 의미가 같은 설명인지 확인하세요. "
        "슬라이드와 대본의 언어가 달라도 의미가 같으면 covered=true입니다. "
        "모든 슬라이드를 번호순으로 정확히 한 번씩 포함하세요. "
        "covered=true이면 missing_point는 null입니다. covered=false이면 "
        "대본에서 빠진 핵심 개념·수치·조건·결과 하나를 자연스러운 한국어 한 문장으로 "
        "구체적으로 작성하되, 자료에 없는 내용을 만들지 마세요. "
        'JSON만 반환: {"slide_coverage": ['
        '{"index": 1, "covered": true, "missing_point": null}'
        "]}"
    )
    user = (
        f"[발표 대본]\n{_format_script(script)}\n\n"
        f"[슬라이드]\n{_format_slides(slides)}\n\n"
        "모든 슬라이드의 포함 여부를 판정하세요."
    )
    return system, user


def build_speech_coaching_prompt(
    transcript: List[TranscriptTurn],
    speech_context: str,
    *,
    draft: str = "",
    language: str = "ko",
):
    """품질이 낮은 음성 코칭을 실제 답변 맥락에 맞춰 다시 생성."""
    language_rule = "결과는 정확히 한국어 두 문장이어야 합니다."
    system = (
        "발표 질의응답의 음성 코칭 문구 하나만 작성하세요. "
        "검증된 음성 지표와 실제 질의응답 전사만 근거로 삼고, 제공되지 않은 "
        "억양, 피치, 강세, 자신감, 긴장, 감정 상태를 추측하지 마세요. "
        "화면에 별도로 표시되는 횟수와 속도 수치를 반복하지 마세요. "
        f"{language_rule} 첫 문장은 측정된 말하기 경향을 "
        "발표자가 바로 이해할 수 있는 일상어로 설명하세요. 두 번째 문장은 실제 답변 "
        "흐름과 함께 나타난 신호를 바탕으로 다음 답변의 어느 시점에 어떤 행동을 할지 "
        "구체적으로 제안하세요. 사용자에게 보이는 문장에는 '필러'라는 용어를 쓰지 말고, "
        "'줄이세요', '주의하세요', '연습하세요'만으로 끝나는 상투적인 조언도 피하세요. "
        "전사에 없는 특정 소리나 습관을 만들어 내지 마세요. "
        'JSON만 반환: {"speech_delivery_feedback": "<관찰 1문장. 행동 조언 1문장.>"}'
    )
    user = (
        "[검증된 음성 지표]\n"
        f"{speech_context.strip()}\n\n"
        "[실제 질의응답]\n"
        f"{_format_transcript(transcript)}\n\n"
        "[다시 작성할 기존 문구]\n"
        f"{draft.strip() or '(비어 있음)'}\n\n"
        "수치 요약을 되풀이하지 말고 발표자가 다음 답변에서 바로 적용할 수 있게 작성하세요."
    )
    return system, user
