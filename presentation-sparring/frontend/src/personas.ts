import type { Persona } from './types'

export const PERSONAS: Persona[] = [
  {
    id: 'professor',
    name: '까다로운 교수',
    emoji: '🎓',
    blurb: '근거와 정의를 파고듭니다. "그 주장의 근거는?", "그 용어를 정확히 정의하면?"',
  },
  {
    id: 'peer',
    name: '디테일 파는 동료',
    emoji: '🧐',
    blurb: '반례와 예외 상황을 던집니다. "이 경우엔 성립 안 하지 않나?"',
  },
  {
    id: 'layperson',
    name: '배경지식 없는 청중',
    emoji: '🙋',
    blurb: '"그게 무슨 뜻이죠?" 이해 안 되는 지점을 드러내 전달력 약점을 노출합니다.',
  },
]

export function getPersona(id: string): Persona {
  return PERSONAS.find((p) => p.id === id) ?? PERSONAS[0]
}
