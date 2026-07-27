"""공통 LLM 프롬프트 제약."""

SOURCE_TERM_PRESERVATION = (
    "\n\n[원문 용어 보존]\n"
    "슬라이드나 대본에 영어로 적힌 기술 용어, 프로토콜명, 모드명, "
    "알고리즘명, API·표준 명칭, 약어, 코드, 수식은 원문 철자와 "
    "대소문자를 그대로 유지하세요. 한국어 번역어·음역어·의역어로 "
    "바꾸지 마세요. 질문 문장 전체는 한국어 존댓말로 작성하되 "
    "핵심 영문 용어는 슬라이드 원문 그대로 사용하세요. "
    "question_focus, expected_answer_points, supplement, retry_question, "
    "followup에도 같은 규칙을 적용하세요."
)


def get_source_term_preservation(language: str = "ko") -> str:
    """세션 언어에 맞춰 원문 용어 보존과 출력 언어를 함께 고정합니다."""
    if language == "en":
        return (
            "\n\n[Source terminology and output language]\n"
            "Preserve the spelling and capitalization of technical terms, protocol names, modes, algorithms, "
            "APIs, standards, abbreviations, code, and formulas exactly as written in the script or slides. "
            "Write questions, retry questions, and follow-up questions in natural English. "
            "For feedback, hints, explanations, and coaching, follow the field-specific output-language rule."
        )
    return SOURCE_TERM_PRESERVATION
