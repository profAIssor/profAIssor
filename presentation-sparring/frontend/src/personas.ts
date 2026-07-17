import type { Persona } from './types'

export const PERSONAS: Persona[] = [
  {
    id: 'professor',
    name: '까다로운 교수',
    emoji: '🎓',
    blurb: '근거와 정의를 파고듭니다',
  },
  {
    id: 'peer',
    name: '디테일 파는 동료',
    emoji: '🧐',
    blurb: '반례와 예외 상황을 던집니다',
  },
  {
    id: 'layperson',
    name: '배경지식 없는 청중',
    emoji: '🙋',
    blurb: '이해 안 되는 지점을 짚어냅니다',
  },
]

export function getPersona(id: string): Persona {
  return PERSONAS.find((p) => p.id === id) ?? PERSONAS[0]
}
