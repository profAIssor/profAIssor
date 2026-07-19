import type { Persona } from './types'

export const PERSONAS: Persona[] = [
  {
    id: 'standard',
    name: '기본 발표 평가자',
    emoji: '💡',
    blurb: '발표 목적과 핵심 메시지를 확인하는 기본 질문으로 질의응답을 먼저 연습합니다.',
  },
  {
    id: 'professor',
    name: '까다로운 교수',
    emoji: '🎓',
    blurb: '발표의 근거, 정의와 논리적 타당성을 검증합니다.',
  },
  {
    id: 'peer',
    name: '디테일 파는 동료',
    emoji: '🧐',
    blurb: '반례 및 예외 상황과 놓친 조건을 점검합니다.',
  },
  {
    id: 'layperson',
    name: '배경지식 없는 청중',
    emoji: '🙋',
    blurb: '이해하기 어려운 개념과 설명이 부족한 지점을 짚어냅니다.',
  },
]

export function getPersona(id: string): Persona {
  return PERSONAS.find((p) => p.id === id) ?? PERSONAS[0]
}
