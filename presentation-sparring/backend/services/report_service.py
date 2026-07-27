"""종합 리포트, 커버리지, 대본 근거 검증 서비스."""

import logging
import math
import re
from difflib import SequenceMatcher
from typing import Dict, List

from fastapi import HTTPException

import llm_client
import material_context
import report_prompt
import speech_metrics
from schemas import (
    AnswerCoaching,
    ReportRequest,
    ReportResponse,
    Revision,
    Slide,
    SlideCoverage,
    TranscriptTurn,
)

logger = logging.getLogger(__name__)

_FILLER_PATTERN = re.compile(
    r"(?<![가-힣])(어+|음+|그+|저기|뭐|뭔가|약간|이제|막|좀)(?![가-힣])"
)
# Korean particles / trivial tokens to ignore when extracting slide keywords.
_STOPWORDS = {
    "그리고", "그러나", "하지만", "또한", "때문", "위해", "대한", "통해", "있는", "있다",
    "합니다", "입니다", "이다", "및", "등", "the", "and", "for", "with", "this", "that",
}


def _count_fillers(text: str) -> int:
    return len(_FILLER_PATTERN.findall(text))


def _word_count(text: str) -> int:
    return len([w for w in re.split(r"\s+", text.strip()) if w])


def _keywords(text: str) -> List[str]:
    """Extract candidate key terms (>=2 char alnum/Hangul tokens).

    Pure-digit tokens (slide page numbers like "02", "10") are never
    meaningful content, so they're dropped unconditionally.
    """
    tokens = re.findall(r"[A-Za-z0-9가-힣]{2,}", text)
    out = []
    for t in tokens:
        if t.isdigit():
            continue
        if t.lower() in _STOPWORDS:
            continue
        out.append(t)
    return out


def _boilerplate_tokens(slides: List[Slide]) -> set:
    """Tokens repeated across most slides are deck-wide template chrome
    (running headers, section labels like "KEY FINDING") rather than
    slide-specific content, and shouldn't be checked for per-slide coverage.

    Only kicks in for decks with enough slides to make "most slides" a
    meaningful signal; small decks skip this entirely.
    """
    if len(slides) < 4:
        return set()
    doc_freq: Dict[str, int] = {}
    for slide in slides:
        for kw in {k.lower() for k in _keywords(slide.text)}:
            doc_freq[kw] = doc_freq.get(kw, 0) + 1
    threshold = max(3, math.ceil(len(slides) / 2))
    return {kw for kw, freq in doc_freq.items() if freq >= threshold}


# Percentages, decimals, and multi-digit numbers — the data points an
# audience most notices when they go unmentioned. Bare single digits
# (often list/page markers) are excluded to avoid noise.
_FIGURE_PATTERN = re.compile(r"\d[\d,]*(?:\.\d+)?%?")


def _figures(text: str) -> List[str]:
    """Extract salient numeric figures from slide text.

    Keeps percentages and decimals, and multi-digit integers that don't look
    like page/section markers (a leading zero — "02", "07" — is treated as a
    marker and dropped).
    """
    out = []
    for raw in _FIGURE_PATTERN.findall(text):
        fig = raw.strip(",")
        core = fig.rstrip("%").replace(",", "")
        if not core:
            continue
        if "%" in fig or "." in core:
            out.append(fig)
        elif len(core) >= 2 and not core.startswith("0"):
            out.append(fig)
    return out


def _figure_rank(fig: str) -> int:
    """Order figures by how likely they are the slide's headline number:
    percentages first, then decimals, then plain counts, with year-like
    4-digit numbers (1900–2099) pushed last so "45%" wins over "2023"."""
    if "%" in fig:
        return 0
    if "." in fig:
        return 1
    core = fig.replace(",", "")
    if len(core) == 4 and core.isdigit() and 1900 <= int(core) <= 2099:
        return 3
    return 2


def _fallback_coverage(slide: Slide, script: str, boilerplate: set) -> SlideCoverage:
    """Deterministic keyword-overlap coverage when the LLM didn't judge a slide.

    A slide is 'covered' if a reasonable share of its key terms appear in the
    spoken script. Otherwise the missing point names the missing category —
    a key figure (수치) when a slide number/percent went unspoken, else a key
    term (용어) — so the feedback points at something concrete.
    """
    kws = [k for k in _keywords(slide.text) if k.lower() not in boilerplate]
    if not kws:
        return SlideCoverage(index=slide.index, covered=True, missing_point=None)
    script_low = script.lower()
    missing = [k for k in kws if k.lower() not in script_low]
    covered_ratio = 1 - (len(missing) / len(kws))
    covered = covered_ratio >= 0.5 and len(missing) < len(kws)
    missing_point = None
    if not covered:
        script_digits = re.sub(r"[,\s]", "", script)
        missing_figs = [
            f for f in _figures(slide.text) if f.rstrip("%").replace(",", "") not in script_digits
        ]
        if missing_figs:
            missing_figs.sort(key=_figure_rank)
            missing_point = f"핵심 수치({missing_figs[0]})가 대본에서 언급되지 않았습니다."
        else:
            example = ", ".join(dict.fromkeys(missing))[:60]
            missing_point = f"핵심 용어({example})가 대본에서 언급되지 않았습니다."
    return SlideCoverage(index=slide.index, covered=covered, missing_point=missing_point)



_PROHIBITED_SPEECH_INFERENCES = (
    "자신감",
    "긴장",
    "감정 상태",
    "억양",
    "피치",
    "단어별 강세",
)


def _parse_speech_delivery_feedback(
    raw,
    *,
    has_speech_summary: bool,
) -> str:
    """LLM 음성 코칭의 근거·표현·구체성 검증."""
    if not has_speech_summary:
        return ""

    if not isinstance(raw, str):
        return ""

    normalized = re.sub(r"\s+", " ", raw).strip()
    if not normalized or normalized.lower() in {
        "null",
        "none",
    }:
        return ""

    if any(
        prohibited in normalized
        for prohibited in _PROHIBITED_SPEECH_INFERENCES
    ):
        logger.warning(
            "Unsupported speech inference discarded: %s",
            normalized[:200],
        )
        return ""

    # 분석 용어가 그대로 노출되거나 짧은 상투어로 끝난 결과는
    # 실제 답변 맥락을 넣은 별도 생성 단계에서 다시 작성합니다.
    sentence_count = len(re.findall(r"[.!?](?=\s|$)", normalized))
    if (
        "필러" in normalized
        or len(normalized) < 45
        or sentence_count < 2
    ):
        return ""

    return normalized[:800]


def _generate_speech_delivery_feedback(
    transcript: List[TranscriptTurn],
    speech_context: str,
    *,
    draft: str,
) -> str:
    """측정값과 실제 답변을 근거로 음성 코칭만 집중 생성."""
    system, user = report_prompt.build_speech_coaching_prompt(
        transcript,
        speech_context,
        draft=draft,
    )
    try:
        data = llm_client.chat_json(
            system,
            user,
            kind="speech_coaching",
        )
    except Exception:  # noqa: BLE001
        logger.exception("Speech coaching generation failed")
        return ""

    return _parse_speech_delivery_feedback(
        data.get("speech_delivery_feedback"),
        has_speech_summary=True,
    )


_VALID_ACTION_TYPES = {
    "sentence_split",
    "signal_phrase",
    "emphasis_shift",
    "term_explanation",
    "other",
}


def _normalize_grounding_text(text: str) -> str:
    """대본 근거 비교용 문자 정규화."""
    return re.sub(
        r"[^0-9A-Za-z가-힣]+",
        "",
        text,
    ).lower()


def _grounding_tokens(text: str) -> set[str]:
    """대본 근거 비교용 핵심 토큰 추출."""
    return {
        token.lower()
        for token in re.findall(
            r"[0-9A-Za-z가-힣_+.-]{2,}",
            text,
        )
        if token.lower() not in _STOPWORDS
    }


def _script_sentence_candidates(script: str) -> List[str]:
    """대본을 화면에 그대로 표시할 수 있는 문장 후보로 분리."""
    raw_parts = re.split(
        r"(?<=[.!?。！？])\s+|\n+",
        script.strip(),
    )
    candidates: List[str] = []

    for raw in raw_parts:
        normalized = re.sub(r"\s+", " ", raw).strip()
        if not normalized:
            continue

        if len(normalized) <= 450:
            candidates.append(normalized)
            continue

        words = normalized.split()
        chunk: List[str] = []
        chunk_length = 0
        for word in words:
            next_length = chunk_length + len(word) + (1 if chunk else 0)
            if chunk and next_length > 360:
                candidates.append(" ".join(chunk))
                chunk = [word]
                chunk_length = len(word)
            else:
                chunk.append(word)
                chunk_length = next_length
        if chunk:
            candidates.append(" ".join(chunk))

    return candidates


def _find_grounded_script_sentence(
    observation: str,
    script_sentences: List[str],
) -> str | None:
    """LLM 관찰과 가장 가까운 실제 대본 문장 조회."""
    observation_normalized = _normalize_grounding_text(
        observation
    )
    if len(observation_normalized) < 8:
        return None

    observation_tokens = _grounding_tokens(observation)
    best_sentence: str | None = None
    best_score = 0.0

    for sentence in script_sentences:
        sentence_normalized = _normalize_grounding_text(
            sentence
        )
        if not sentence_normalized:
            continue

        if (
            observation_normalized in sentence_normalized
            or sentence_normalized in observation_normalized
        ):
            return sentence

        sequence_score = SequenceMatcher(
            None,
            observation_normalized,
            sentence_normalized,
        ).ratio()

        sentence_tokens = _grounding_tokens(sentence)
        shared_tokens = observation_tokens & sentence_tokens
        token_score = (
            len(shared_tokens)
            / max(
                1,
                min(
                    len(observation_tokens),
                    len(sentence_tokens),
                ),
            )
        )

        score = max(sequence_score, token_score)
        if score > best_score:
            best_score = score
            best_sentence = sentence

    return best_sentence if best_score >= 0.58 else None


def _parse_revisions(
    raw,
    *,
    script: str,
    valid_slide_indices: set[int],
    limit: int = 4,
) -> List[Revision]:
    """실제 발표 대본에 근거한 수정 제안만 보존."""
    if not isinstance(raw, list) or not script.strip():
        return []

    script_sentences = _script_sentence_candidates(
        script
    )
    if not script_sentences:
        return []

    result: List[Revision] = []

    for item in raw:
        if not isinstance(item, dict):
            continue

        observation = str(
            item.get("observation", "")
        ).strip()
        impact = str(item.get("impact", "")).strip()
        action = str(item.get("action", "")).strip()
        example = str(item.get("example", "")).strip()

        if not (observation and impact and action and example):
            continue

        grounded_sentence = _find_grounded_script_sentence(
            observation,
            script_sentences,
        )
        if grounded_sentence is None:
            logger.warning(
                "Ungrounded script revision discarded: %s",
                observation[:160],
            )
            continue

        grounded_tokens = _grounding_tokens(
            grounded_sentence
        )
        example_tokens = _grounding_tokens(example)
        if (
            grounded_tokens
            and not grounded_tokens & example_tokens
        ):
            logger.warning(
                "Unrelated script revision example discarded: %s",
                example[:160],
            )
            continue

        action_type = item.get("action_type")
        if action_type not in _VALID_ACTION_TYPES:
            action_type = "other"

        slide_index = item.get("slide_index")
        if (
            isinstance(slide_index, str)
            and slide_index.strip().isdigit()
        ):
            slide_index = int(slide_index.strip())
        if (
            not isinstance(slide_index, int)
            or slide_index not in valid_slide_indices
        ):
            slide_index = None

        result.append(
            Revision(
                slide_index=slide_index,
                observation=grounded_sentence[:450],
                impact=impact[:300],
                action_type=action_type,
                action=action[:300],
                example=example[:450],
            )
        )

        if len(result) >= limit:
            break

    return result


def _normalized_optional_text(
    value,
    *,
    limit: int,
) -> str | None:
    """LLM 선택 문자열의 null·빈 값 정규화."""
    if not isinstance(value, str):
        return None

    normalized = re.sub(r"\s+", " ", value).strip()
    if not normalized or normalized.lower() in {
        "null",
        "none",
    }:
        return None
    return normalized[:limit]


def _parse_answer_coaching(
    raw,
    transcript,
) -> List[AnswerCoaching]:
    """모든 평가 축이 우수하지 않은 질문의 참고 답변 연결."""
    raw_by_index: Dict[int, dict] = {}
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue

            index = item.get("turn_index")
            if isinstance(index, str) and index.isdigit():
                index = int(index)
            if isinstance(index, int):
                raw_by_index[index] = item

    result: List[AnswerCoaching] = []

    for index, turn in enumerate(transcript):
        rubric_values = list(turn.rubric.values())
        all_excellent = (
            turn.answer_status == "answered"
            and bool(rubric_values)
            and all(
                value == "우수"
                for value in rubric_values
            )
        )

        # 모든 평가 축이 우수하면 보완 카드 미표시
        if all_excellent:
            continue

        item = raw_by_index.get(index, {})
        reference_answer = _normalized_optional_text(
            item.get("reference_answer"),
            limit=900,
        )

        # 재질문에도 답하지 못한 경우 기존 개념 설명 폴백
        if (
            reference_answer is None
            and turn.final_explanation
        ):
            reference_answer = re.sub(
                r"\s+",
                " ",
                turn.final_explanation,
            ).strip()[:900]

        # 재질문 흐름의 자료 기반 힌트 최후 폴백
        if (
            reference_answer is None
            and turn.retry_question
            and turn.supplement
        ):
            reference_answer = re.sub(
                r"\s+",
                " ",
                turn.supplement,
            ).strip()[:900]

        if reference_answer:
            result.append(
                AnswerCoaching(
                    turn_index=index,
                    reference_answer=reference_answer,
                )
            )

    return result


def _needs_reference_answer(turn) -> bool:
    """별도 참고 답변이 필요한 질문 슬롯 판정."""
    rubric_values = list(turn.rubric.values())
    return not (
        turn.answer_status == "answered"
        and bool(rubric_values)
        and all(
            value == "우수"
            for value in rubric_values
        )
    )


def _missing_reference_indices(
    transcript,
    answer_coaching: List[AnswerCoaching],
) -> List[int]:
    """참고 답변이 필요한데 결과에서 누락된 질문 순번 조회."""
    completed_indices = {
        item.turn_index
        for item in answer_coaching
        if item.reference_answer
    }
    return [
        index
        for index, turn in enumerate(transcript)
        if (
            _needs_reference_answer(turn)
            and index not in completed_indices
        )
    ]


def _format_reference_repair_material(
    req: ReportRequest,
    missing_indices: List[int],
) -> str:
    """누락 질문별 관련 발표 자료의 최소 문맥 구성."""
    prompt_slides = material_context.build_prompt_slides(
        req.script,
        req.slides,
    )
    blocks: List[str] = []

    for index in missing_indices:
        turn = req.transcript[index]
        target_question = (
            turn.retry_question
            if turn.retry_question
            else turn.question
        )
        target_answer = (
            turn.retry_answer
            if turn.retry_question
            else turn.answer
        ) or ""

        selected_slides = material_context.select_context_slides(
            prompt_slides,
            turn.related_slides,
            query=target_question,
        )
        slide_context = "\n".join(
            (
                f"[슬라이드 {slide.index}] "
                f"{slide.text[:1600]}"
            )
            for slide in selected_slides[:3]
        ) or "(관련 슬라이드 없음)"

        rubric_context = ", ".join(
            f"{axis}={value}"
            for axis, value in turn.rubric.items()
        ) or "평가 축 없음"

        blocks.append(
            "\n".join(
                [
                    f"[turn_index={index}]",
                    f"질문: {target_question}",
                    f"학생 답변: {target_answer or '(답변 없음)'}",
                    f"최종 평가: {rubric_context}",
                    f"보완점: {turn.gaps}",
                    "관련 발표 자료:",
                    slide_context,
                ]
            )
        )

    return "\n\n".join(blocks)


def _repair_missing_reference_answers(
    req: ReportRequest,
    answer_coaching: List[AnswerCoaching],
) -> List[AnswerCoaching]:
    """리포트 LLM이 누락한 참고 답변을 한 번의 보완 호출로 생성."""
    missing_indices = _missing_reference_indices(
        req.transcript,
        answer_coaching,
    )
    if not missing_indices:
        return answer_coaching

    logger.warning(
        "Missing reference answers detected: indices=%s",
        missing_indices,
    )

    system = (
        "당신은 발표 질의응답 리포트에서 누락된 참고 답변만 보완합니다. "
        "각 항목의 질문과 발표 자료를 근거로 질문에 직접 답하는 "
        "한국어 1~3문장의 완결된 참고 답변을 작성하세요. "
        "학생 답변을 평가하거나 '부족했다'고 언급하지 마세요. "
        "쉬운 재질문이 제시된 항목은 원질문이 아니라 쉬운 재질문에 답하세요. "
        "발표 자료에 없는 사실을 만들지 마세요. "
        "영문 기술 용어, 고유 명칭, 약어는 자료의 원문 표기를 유지하세요. "
        "입력에 있는 turn_index를 그대로 반환하세요. "
        'JSON만 반환: {"answer_coaching": ['
        '{"turn_index": 0, "reference_answer": "<참고 답변>"}'
        "]}"
    )
    user = (
        "[발표 대본]\n"
        f"{req.script.strip() or '(발표 대본 없음)'}\n\n"
        "[참고 답변이 누락된 질문]\n"
        f"{_format_reference_repair_material(req, missing_indices)}\n\n"
        "모든 turn_index에 대해 reference_answer를 빠짐없이 작성하세요."
    )

    repair_data: dict = {}
    try:
        repair_data = llm_client.chat_json(
            system,
            user,
            kind="reference_repair",
        )
    except Exception:  # noqa: BLE001
        logger.exception(
            "Reference answer repair call failed"
        )
        return answer_coaching

    repaired_by_index: Dict[int, str] = {}
    raw_items = repair_data.get("answer_coaching")
    if isinstance(raw_items, list):
        for item in raw_items:
            if not isinstance(item, dict):
                continue

            index = item.get("turn_index")
            if isinstance(index, str) and index.isdigit():
                index = int(index)

            if (
                not isinstance(index, int)
                or index not in missing_indices
            ):
                continue

            reference_answer = _normalized_optional_text(
                item.get("reference_answer"),
                limit=900,
            )
            if reference_answer:
                repaired_by_index[index] = reference_answer

    merged = {
        item.turn_index: item
        for item in answer_coaching
        if item.reference_answer
    }
    for index, reference_answer in repaired_by_index.items():
        merged[index] = AnswerCoaching(
            turn_index=index,
            reference_answer=reference_answer,
        )

    remaining = [
        index
        for index in missing_indices
        if index not in merged
    ]
    if remaining:
        logger.warning(
            "Reference answers still missing after repair: indices=%s",
            remaining,
        )

    return [
        merged[index]
        for index in sorted(merged)
    ]



_SCRIPT_MISSING_CONTENT = (
    "발표 대본이 제공되지 않아 발표자가 실제로 전달한 내용의 "
    "구조·근거·누락을 평가하지 못했습니다."
)
_SCRIPT_MISSING_DELIVERY = (
    "발표 대본이 제공되지 않아 문장 명확성, 용어 설명, 설명 순서를 "
    "평가하지 못했습니다. 질의응답 대응은 별도 항목에서 확인해 주세요."
)
_SLIDES_MISSING_CONTENT_NOTICE = (
    "슬라이드가 제공되지 않아 대본과 시각 자료의 일치 여부나 "
    "슬라이드 핵심 누락은 판단하지 못했습니다."
)


def _append_feedback_notice(
    feedback: str,
    notice: str,
) -> str:
    """기존 피드백에 자료 부재 안내 중복 없이 추가."""
    normalized = re.sub(r"\s+", " ", feedback).strip()
    if not normalized:
        return notice
    if notice in normalized:
        return normalized
    return f"{normalized} {notice}"



def build_report(req: ReportRequest) -> ReportResponse:
    has_script = bool(req.script.strip())
    has_slides = bool(req.slides)
    coverage_available = has_script and has_slides

    speech_summary = speech_metrics.build_speech_summary(
        req.transcript
    )
    speech_prompt_context = (
        speech_metrics.build_speech_prompt_context(
            speech_summary,
            req.transcript,
        )
    )
    system, user = report_prompt.build_report_prompt(
        req.script,
        req.slides,
        req.transcript,
        speech_context=speech_prompt_context,
    )
    try:
        data = llm_client.chat_json(
            system,
            user,
            kind="report",
        )
    except Exception:  # noqa: BLE001
        logger.exception("LLM call failed in /api/report")
        raise HTTPException(status_code=502, detail="리포트 생성 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.")

    # Merge LLM coverage (if any) with a deterministic fallback so EVERY slide
    # is represented and coverage always shows in the report.
    llm_cov: Dict[int, dict] = {}
    for c in data.get("slide_coverage", []) or []:
        try:
            llm_cov[int(c.get("index"))] = c
        except (TypeError, ValueError):
            continue

    coverage: List[SlideCoverage] = []
    if coverage_available:
        boilerplate = _boilerplate_tokens(req.slides)
        for slide in sorted(req.slides, key=lambda s: s.index):
            if slide.index in llm_cov:
                c = llm_cov[slide.index]
                covered = bool(c.get("covered", True))
                mp = c.get("missing_point")
                if (
                    isinstance(mp, str)
                    and mp.strip().lower()
                    in ("null", "none", "")
                ):
                    mp = None
                coverage.append(
                    SlideCoverage(
                        index=slide.index,
                        covered=covered,
                        missing_point=(
                            None
                            if covered
                            else (
                                mp
                                or "핵심 내용이 대본에서 충분히 언급되지 않았습니다."
                            )
                        ),
                    )
                )
            else:
                coverage.append(
                    _fallback_coverage(
                        slide,
                        req.script,
                        boilerplate,
                    )
                )

    valid_slide_indices = {slide.index for slide in req.slides}
    revisions = (
        _parse_revisions(
            data.get("revisions"),
            script=req.script,
            valid_slide_indices=valid_slide_indices,
        )
        if has_script
        else []
    )
    answer_coaching = _parse_answer_coaching(
        data.get("answer_coaching"),
        req.transcript,
    )
    answer_coaching = _repair_missing_reference_answers(
        req,
        answer_coaching,
    )

    raw_speech_feedback = data.get("speech_delivery_feedback")
    speech_delivery_feedback = _parse_speech_delivery_feedback(
        raw_speech_feedback,
        has_speech_summary=speech_summary is not None,
    )
    if speech_summary is not None and not speech_delivery_feedback:
        speech_delivery_feedback = _generate_speech_delivery_feedback(
            req.transcript,
            speech_prompt_context,
            draft=(
                raw_speech_feedback
                if isinstance(raw_speech_feedback, str)
                else ""
            ),
        )

    content_feedback = str(
        data.get("content_feedback", "")
    ).strip()
    delivery_feedback = str(
        data.get("delivery_feedback", "")
    ).strip()
    response_feedback = str(
        data.get("response_feedback", "")
    ).strip()

    if not has_script:
        content_feedback = _SCRIPT_MISSING_CONTENT
        delivery_feedback = _SCRIPT_MISSING_DELIVERY
    elif not has_slides:
        content_feedback = _append_feedback_notice(
            content_feedback,
            _SLIDES_MISSING_CONTENT_NOTICE,
        )

    if not response_feedback:
        response_feedback = (
            "질의응답 기록이 없어 질문 대응을 평가하지 못했습니다."
            if not req.transcript
            else "질문에 대한 직접성과 근거 제시를 다시 확인해 주세요."
        )

    return ReportResponse(
        content_feedback=content_feedback,
        delivery_feedback=delivery_feedback,
        response_feedback=response_feedback,
        slide_coverage=coverage,
        filler_count=(
            speech_summary.recognized_filler_count
            if speech_summary is not None
            else 0
        ),
        filler_count_mode=(
            "recognized_minimum"
            if speech_summary is not None
            else "unavailable"
        ),
        word_count=_word_count(req.script),
        speech_summary=speech_summary,
        speech_delivery_feedback=speech_delivery_feedback,
        revisions=revisions,
        answer_coaching=answer_coaching,
        answer_structure_tip=str(
            data.get("answer_structure_tip", "")
        ).strip(),
        script_available=has_script,
        slides_available=has_slides,
        slide_coverage_available=coverage_available,
    )
