"""슬라이드와 발표 대본의 내부 정렬 및 질문용 자료 구성 모듈."""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from typing import Sequence

from schemas import Slide


_SENTENCE_SPLIT_PATTERN = re.compile(r"(?<=[.!?。！？])\s+|\n+")
_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9가-힣]+")


@dataclass(frozen=True)
class SlideAlignment:
    """슬라이드와 해당 슬라이드에서 설명할 것으로 추정되는 대본 구간."""

    slide_index: int
    slide_text: str
    script_segment: str
    confidence: float


def normalize_text(text: str) -> str:
    """비교와 프롬프트 전달을 위한 공백·유니코드 정규화."""
    normalized = unicodedata.normalize("NFKC", text or "")
    normalized = normalized.replace("\u200b", "").replace("\ufeff", "")
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"[ \t]+", " ", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()


def _split_script(script: str) -> list[str]:
    """발표 대본의 의미 단위 후보 분리."""
    normalized = normalize_text(script)
    if not normalized:
        return []

    parts = _SENTENCE_SPLIT_PATTERN.split(normalized)
    return [re.sub(r"\s+", " ", part).strip() for part in parts if part.strip()]


def _feature_counter(text: str, *, title_weight: float = 1.0) -> Counter[str]:
    """한국어·영문 혼합 자료의 비교용 특징 생성."""
    normalized = normalize_text(text).lower()
    lines = [line.strip() for line in normalized.splitlines() if line.strip()]
    counter: Counter[str] = Counter()

    for line_index, line in enumerate(lines or [normalized]):
        weight = title_weight if line_index == 0 else 1.0
        for token in _TOKEN_PATTERN.findall(line):
            if len(token) < 2:
                continue
            counter[token] += weight

            # 조사 차이와 추출 줄바꿈에 덜 민감한 한국어 부분 문자열 특징
            if re.fullmatch(r"[가-힣]+", token) and len(token) >= 4:
                for size in (2, 3):
                    for start in range(0, len(token) - size + 1):
                        counter[f"ko:{token[start:start + size]}"] += 0.18 * weight

            # 모델명·약어의 대소문자 및 구두점 차이 완화
            if re.search(r"[a-z]", token):
                simplified = re.sub(r"[^a-z0-9]", "", token)
                if simplified:
                    counter[f"en:{simplified}"] += 0.45 * weight

    return counter


def _cosine_similarity(left: Counter[str], right: Counter[str]) -> float:
    """희소 특징 벡터의 코사인 유사도 계산."""
    if not left or not right:
        return 0.0

    common = left.keys() & right.keys()
    numerator = sum(left[key] * right[key] for key in common)
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return numerator / (left_norm * right_norm)


def _emission_score(
    sentence_features: Counter[str],
    slide_features: Counter[str],
    sentence_position: int,
    sentence_count: int,
    slide_position: int,
    slide_count: int,
) -> float:
    """내용 유사도와 발표 순서 사전값을 합친 배정 점수 계산."""
    lexical = _cosine_similarity(sentence_features, slide_features)
    sentence_ratio = sentence_position / max(sentence_count - 1, 1)
    slide_ratio = slide_position / max(slide_count - 1, 1)
    order_penalty = abs(sentence_ratio - slide_ratio) * 0.22
    return lexical - order_penalty


def align_script_to_slides(script: str, slides: Sequence[Slide]) -> list[SlideAlignment]:
    """슬라이드 순서를 역행하지 않는 대본 구간 추정."""
    ordered_slides = sorted(slides, key=lambda item: item.index)
    if not ordered_slides:
        return []

    sentences = _split_script(script)
    if not sentences:
        return [
            SlideAlignment(
                slide_index=slide.index,
                slide_text=normalize_text(slide.text),
                script_segment="",
                confidence=0.0,
            )
            for slide in ordered_slides
        ]

    slide_features = [
        _feature_counter(slide.text, title_weight=1.45)
        for slide in ordered_slides
    ]
    sentence_features = [_feature_counter(sentence) for sentence in sentences]

    sentence_count = len(sentences)
    slide_count = len(ordered_slides)
    negative_infinity = float("-inf")

    # 문장별 슬라이드 위치의 최대 누적 점수 테이블
    dp = [[negative_infinity] * slide_count for _ in range(sentence_count)]
    previous = [[0] * slide_count for _ in range(sentence_count)]

    for slide_position in range(slide_count):
        start_penalty = slide_position * 0.045
        dp[0][slide_position] = _emission_score(
            sentence_features[0],
            slide_features[slide_position],
            0,
            sentence_count,
            slide_position,
            slide_count,
        ) - start_penalty

    for sentence_position in range(1, sentence_count):
        for slide_position in range(slide_count):
            best_score = negative_infinity
            best_previous = 0

            # 슬라이드 순서 역행 방지 및 큰 건너뛰기 완화
            for previous_position in range(slide_position + 1):
                jump = slide_position - previous_position
                transition_penalty = max(0, jump - 1) * 0.055
                candidate = dp[sentence_position - 1][previous_position] - transition_penalty
                if candidate > best_score:
                    best_score = candidate
                    best_previous = previous_position

            dp[sentence_position][slide_position] = best_score + _emission_score(
                sentence_features[sentence_position],
                slide_features[slide_position],
                sentence_position,
                sentence_count,
                slide_position,
                slide_count,
            )
            previous[sentence_position][slide_position] = best_previous

    final_position = max(range(slide_count), key=lambda item: dp[-1][item])
    assignments = [0] * sentence_count
    assignments[-1] = final_position
    for sentence_position in range(sentence_count - 1, 0, -1):
        assignments[sentence_position - 1] = previous[
            sentence_position
        ][assignments[sentence_position]]

    grouped: dict[int, list[str]] = {position: [] for position in range(slide_count)}
    similarities: dict[int, list[float]] = {
        position: [] for position in range(slide_count)
    }
    for sentence_position, slide_position in enumerate(assignments):
        grouped[slide_position].append(sentences[sentence_position])
        similarities[slide_position].append(
            _cosine_similarity(
                sentence_features[sentence_position],
                slide_features[slide_position],
            )
        )

    result: list[SlideAlignment] = []
    for slide_position, slide in enumerate(ordered_slides):
        scores = similarities[slide_position]
        confidence = sum(scores) / len(scores) if scores else 0.0
        result.append(
            SlideAlignment(
                slide_index=slide.index,
                slide_text=normalize_text(slide.text),
                script_segment=" ".join(grouped[slide_position]).strip(),
                confidence=round(confidence, 4),
            )
        )
    return result


def build_prompt_slides(
    script: str,
    slides: Sequence[Slide],
    *,
    max_slide_chars: int = 1400,
    max_segment_chars: int = 700,
) -> list[Slide]:
    """질문 생성용 슬라이드 원문과 추정 대본 구간의 내부 결합."""
    alignments = align_script_to_slides(script, slides)
    result: list[Slide] = []

    for alignment in alignments:
        text = alignment.slide_text[:max_slide_chars].rstrip()
        if alignment.script_segment:
            segment = alignment.script_segment[:max_segment_chars].rstrip()
            text = (
                f"{text}\n\n"
                "[이 슬라이드에서 설명한 것으로 추정되는 발표 대본 구간]\n"
                f"{segment}"
            )
        result.append(Slide(index=alignment.slide_index, text=text))

    return result


def compact_script(script: str, *, max_chars: int = 16000) -> str:
    """과도한 프롬프트 중복을 줄이기 위한 전체 대본 길이 제한."""
    normalized = normalize_text(script)
    if len(normalized) <= max_chars:
        return normalized

    head_size = int(max_chars * 0.65)
    tail_size = max_chars - head_size
    return (
        normalized[:head_size].rstrip()
        + "\n\n[중간 대본 일부 생략]\n\n"
        + normalized[-tail_size:].lstrip()
    )


def select_context_slides(
    slides: Sequence[Slide],
    context_indices: Sequence[int],
    *,
    query: str = "",
    limit: int = 3,
) -> list[Slide]:
    """명시된 슬라이드 또는 질문 초점과 가까운 슬라이드 선택."""
    requested = {index for index in context_indices if isinstance(index, int)}
    selected = [slide for slide in slides if slide.index in requested]
    if selected:
        return selected[:limit]

    if query.strip():
        query_features = _feature_counter(query)
        ranked = sorted(
            slides,
            key=lambda slide: _cosine_similarity(
                query_features,
                _feature_counter(slide.text),
            ),
            reverse=True,
        )
        return ranked[:limit]

    return list(slides)[:limit]