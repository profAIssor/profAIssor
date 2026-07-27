"""답변별 음성 지표의 세션 집계와 결정론적 코칭 생성."""

from typing import List, Optional, Tuple

from schemas import (
    SpeechMetrics,
    SpeechSummary,
    TranscriptTurn,
)

PACE_VERY_SLOW_MAX_SPS = 4.0
PACE_NORMAL_MIN_SPS = 5.0
PACE_TYPICAL_MIN_SPS = 5.5
PACE_NORMAL_MAX_SPS = 7.5
PACE_VERY_FAST_MIN_SPS = 8.0
MIN_PACE_SYLLABLES = 20
MIN_PACE_ARTICULATION_MS = 5_000
LONG_PAUSE_MS = 4_000
VOLUME_LOW_MAX_DB = 4.0
VOLUME_HIGH_MIN_DB = 10.0
MIN_VOLUME_VOICED_MS = 8_000


def _round_optional(value: Optional[float], digits: int = 1) -> Optional[float]:
    """선택 수치의 제한 자릿수 반올림."""
    if value is None:
        return None
    return round(value, digits)


def _pace_status(pace_sps: Optional[float]):
    """세션 말 빠르기 상태 판정."""
    if pace_sps is None:
        return None
    if pace_sps < PACE_VERY_SLOW_MAX_SPS:
        return "slow"
    if pace_sps < PACE_NORMAL_MIN_SPS:
        return "slightly_slow"
    if pace_sps < PACE_TYPICAL_MIN_SPS:
        return "calm"
    if pace_sps <= PACE_NORMAL_MAX_SPS:
        return "balanced"
    if pace_sps <= PACE_VERY_FAST_MIN_SPS:
        return "slightly_fast"
    return "fast"


def _volume_status(volume_variation_db: Optional[float]):
    """세션 내 목소리 크기 변화 상태 판정."""
    if volume_variation_db is None:
        return None
    if volume_variation_db < VOLUME_LOW_MAX_DB:
        return "low"
    if volume_variation_db >= VOLUME_HIGH_MIN_DB:
        return "high"
    return "moderate"


def build_speech_summary(
    transcript: List[TranscriptTurn],
) -> Optional[SpeechSummary]:
    """원질문과 쉬운 재질문 답변을 포함한 세션 단위 가중 집계."""
    measured: List[SpeechMetrics] = []
    total_answer_count = 0

    for turn in transcript:
        total_answer_count += 1
        if turn.speech_metrics is not None:
            measured.append(turn.speech_metrics)

        if turn.retry_question:
            total_answer_count += 1
            if turn.retry_speech_metrics is not None:
                measured.append(turn.retry_speech_metrics)

    if not measured:
        return None

    reliable = [
        metric
        for metric in measured
        if metric.confidence != "low"
        and metric.voiced_duration_ms > 0
    ]
    pace_eligible = [
        metric
        for metric in reliable
        if metric.stt_syllable_count >= MIN_PACE_SYLLABLES
        and metric.articulation_duration_ms >= MIN_PACE_ARTICULATION_MS
    ]

    total_voiced_duration_ms = sum(
        metric.voiced_duration_ms for metric in reliable
    )
    total_captured_duration_ms = sum(
        metric.captured_duration_ms for metric in measured
    )
    pace_articulation_duration_ms = sum(
        metric.articulation_duration_ms for metric in pace_eligible
    )
    total_stt_word_count = sum(
        metric.stt_word_count for metric in pace_eligible
    )
    total_stt_syllable_count = sum(
        metric.stt_syllable_count for metric in pace_eligible
    )

    session_pace_wpm: Optional[float] = None
    if pace_articulation_duration_ms > 0 and total_stt_word_count > 0:
        session_pace_wpm = (
            total_stt_word_count
            / (pace_articulation_duration_ms / 60_000)
        )

    session_pace_sps: Optional[float] = None
    if pace_articulation_duration_ms > 0 and total_stt_syllable_count > 0:
        session_pace_sps = (
            total_stt_syllable_count
            / (pace_articulation_duration_ms / 1_000)
        )

    long_pause_count = sum(
        metric.long_pause_count for metric in reliable
    )
    longest_pause_values = [
        metric.longest_pause_ms
        for metric in reliable
        if metric.longest_pause_ms is not None
    ]

    latency_values = [
        metric.initial_response_latency_ms
        for metric in reliable
        if metric.initial_response_latency_ms is not None
    ]
    average_initial_latency_ms = (
        sum(latency_values) / len(latency_values)
        if latency_values
        else None
    )

    weighted_volume_sum = 0.0
    weighted_volume_duration = 0
    for metric in reliable:
        if metric.volume_variation_db is None:
            continue
        weighted_volume_sum += (
            metric.volume_variation_db
            * metric.voiced_duration_ms
        )
        weighted_volume_duration += metric.voiced_duration_ms

    volume_variation_db: Optional[float] = None
    if weighted_volume_duration >= MIN_VOLUME_VOICED_MS:
        volume_variation_db = (
            weighted_volume_sum / weighted_volume_duration
        )

    recognized_filler_count = sum(
        metric.recognized_filler_count for metric in measured
    )

    return SpeechSummary(
        measured_answer_count=len(measured),
        reliable_answer_count=len(reliable),
        pace_answer_count=len(pace_eligible),
        total_answer_count=total_answer_count,
        total_captured_duration_ms=total_captured_duration_ms,
        total_voiced_duration_ms=total_voiced_duration_ms,
        session_pace_wpm=_round_optional(session_pace_wpm),
        session_pace_sps=_round_optional(session_pace_sps),
        pace_status=_pace_status(session_pace_sps),
        long_pause_count=long_pause_count,
        longest_pause_ms=(
            max(longest_pause_values)
            if longest_pause_values
            else None
        ),
        recognized_filler_count=recognized_filler_count,
        filler_measurement="recognized_minimum",
        average_initial_latency_ms=_round_optional(
            average_initial_latency_ms
        ),
        volume_variation_db=_round_optional(volume_variation_db),
        volume_variation_status=_volume_status(
            volume_variation_db
        ),
    )


def _seconds(milliseconds: Optional[float]) -> str:
    """밀리초의 사용자 표시용 초 변환."""
    if milliseconds is None:
        return "0초"
    return f"{milliseconds / 1000:.1f}초"


def build_speech_delivery_feedback(
    summary: Optional[SpeechSummary],
) -> str:
    """측정된 상태만 사용하는 실행 가능한 음성 코칭 생성."""
    if summary is None:
        return ""

    observations: List[str] = [
        (
            f"전체 {summary.total_answer_count}개 답변 중 "
            f"{summary.measured_answer_count}개에서 음성 지표를 수집했습니다."
        )
    ]
    actions: List[str] = []

    if summary.pace_status == "fast" and summary.session_pace_sps is not None:
        observations.append(
            f"평균 답변 속도는 초당 {summary.session_pace_sps:.1f}음절로 매우 빠른 편입니다."
        )
        actions.append(
            "핵심 결론이나 수치를 말한 뒤 0.5~1초 정도 쉬고 다음 근거로 넘어가세요."
        )
    elif (
        summary.pace_status == "slightly_fast"
        and summary.session_pace_sps is not None
    ):
        observations.append(
            f"평균 답변 속도는 초당 {summary.session_pace_sps:.1f}음절로 "
            "다소 빠른 편이지만, 속도만으로는 문제로 판단하지 않습니다."
        )
    elif summary.pace_status == "slow" and summary.session_pace_sps is not None:
        observations.append(
            f"평균 답변 속도는 초당 {summary.session_pace_sps:.1f}음절로 매우 느린 편입니다."
        )
        actions.append(
            "긴 머뭇거림도 함께 반복된다면 첫 문장에서 결론을 먼저 말하는 연습을 해보세요."
        )
    elif (
        summary.pace_status == "slightly_slow"
        and summary.session_pace_sps is not None
    ):
        observations.append(
            f"평균 답변 속도는 초당 {summary.session_pace_sps:.1f}음절로 "
            "다소 느린 편이지만, 속도만으로는 문제로 판단하지 않습니다."
        )
    elif summary.pace_status == "calm" and summary.session_pace_sps is not None:
        observations.append(
            f"평균 답변 속도는 초당 {summary.session_pace_sps:.1f}음절로 차분하고 무리 없는 범위입니다."
        )
    elif summary.pace_status == "balanced" and summary.session_pace_sps is not None:
        observations.append(
            f"평균 답변 속도는 초당 {summary.session_pace_sps:.1f}음절로 일반적인 범위입니다."
        )

    if summary.long_pause_count > 0:
        observations.append(
            f"발화 중 {LONG_PAUSE_MS / 1000:g}초 이상 멈춤이 "
            f"{summary.long_pause_count}회 있었고, 최장 멈춤은 "
            f"{_seconds(summary.longest_pause_ms)}였습니다."
        )
        actions.append(
            "답변을 시작하기 전에 결론과 근거 한 가지를 정한 뒤, 문장 사이에는 짧은 쉼만 남겨보세요."
        )

    if summary.recognized_filler_count > 0:
        observations.append(
            f"Chrome STT 처리 중 명확히 확인된 필러는 최소 {summary.recognized_filler_count}회입니다."
        )
        actions.append(
            "필러가 나오려는 순간에는 소리를 채우지 말고 짧게 멈춘 뒤 첫 문장을 시작하세요."
        )

    excluded_count = (
        summary.measured_answer_count
        - summary.reliable_answer_count
    )
    if excluded_count > 0:
        observations.append(
            f"측정 신뢰도가 낮은 답변 {excluded_count}개는 속도·멈춤 판정에서 제외했습니다."
        )

    if not actions:
        actions.append(
            "현재 측정에서는 뚜렷한 속도·멈춤 문제가 확인되지 않았습니다. 핵심 수치 뒤에 짧은 쉼을 넣는 연습을 유지하세요."
        )

    return " ".join([*observations, *actions[:3]])


def build_speech_report(
    transcript: List[TranscriptTurn],
) -> Tuple[Optional[SpeechSummary], str]:
    """세션 음성 요약과 결정론적 코칭 동시 생성."""
    summary = build_speech_summary(transcript)
    return summary, build_speech_delivery_feedback(summary)

def build_speech_prompt_context(
    summary: Optional[SpeechSummary],
) -> str:
    """LLM에 전달할 검증된 음성 판정 신호 생성."""
    if summary is None:
        return ""

    lines: List[str] = [
        "[측정 범위]",
        (
            f"- 전체 {summary.total_answer_count}개 답변 중 "
            f"{summary.measured_answer_count}개에서 음성 지표 수집"
        ),
        (
            f"- 답변 속도 판정 포함: {summary.pace_answer_count}개 "
            f"({MIN_PACE_SYLLABLES}음절 이상, 조음 시간 "
            f"{MIN_PACE_ARTICULATION_MS / 1000:g}초 이상)"
        ),
    ]

    if summary.reliable_answer_count < summary.measured_answer_count:
        excluded_count = (
            summary.measured_answer_count
            - summary.reliable_answer_count
        )
        lines.append(
            f"- 신뢰도 낮아 속도·멈춤 판정에서 제외된 답변: {excluded_count}개"
        )

    actionable_signal_count = 0

    if (
        summary.pace_status is not None
        and summary.session_pace_sps is not None
    ):
        pace_labels = {
            "slow": "매우 느린 편",
            "slightly_slow": "다소 느린 편",
            "calm": "차분한 정상 범위",
            "balanced": "일반적인 정상 범위",
            "slightly_fast": "다소 빠른 편",
            "fast": "매우 빠른 편",
        }
        lines.extend(
            [
                "[말 빠르기]",
                f"- 판정: {pace_labels[summary.pace_status]}",
                (
                    "- 근거: 0.25초 이상 무음 휴지를 제외한 조음 시간 기준 "
                    f"{summary.session_pace_sps:.1f}음절/초"
                ),
            ]
        )
        if summary.pace_status in {"slow", "fast"}:
            actionable_signal_count += 1
        else:
            lines.append(
                "- 처리: 이 속도만으로는 개선점이나 경고에 포함하지 않음"
            )

    if summary.long_pause_count > 0:
        lines.extend(
            [
                "[발화 중 긴 멈춤]",
                f"- {LONG_PAUSE_MS / 1000:g}초 이상 내부 멈춤: {summary.long_pause_count}회",
                f"- 최장 멈춤: {_seconds(summary.longest_pause_ms)}",
            ]
        )
        actionable_signal_count += 1

    if summary.recognized_filler_count > 0:
        lines.extend(
            [
                "[명확히 인식된 필러]",
                (
                    "- Chrome STT 처리 중 확인된 최소 횟수: "
                    f"{summary.recognized_filler_count}회"
                ),
                "- 주의: 실제 전체 필러 횟수가 아닌 인식 하한선",
            ]
        )
        actionable_signal_count += 1

    if actionable_signal_count == 0:
        lines.extend(
            [
                "[종합 판정]",
                "- 현재 신뢰 가능한 측정에서 뚜렷한 개선 신호 미확인",
            ]
        )

    return "\n".join(lines)
