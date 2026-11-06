import type { CSSProperties } from 'react'

export type RelationLabel =
  | 'new'
  | 'refinement'
  | 'contradiction'
  | 'supersession'
  | 'restatement'
  | 'not_requirement'

const WORDS: Record<RelationLabel, string> = {
  new: 'New',
  refinement: 'Refinement',
  contradiction: 'Conflict',
  supersession: 'Replacement',
  restatement: 'Repeat',
  not_requirement: 'Not a requirement',
}

const TINT: Partial<Record<RelationLabel, string>> = {
  contradiction: 'cia-relation--contradiction',
  supersession: 'cia-relation--supersession',
}

export function RelationChip({ relation, style }: { relation: RelationLabel; style?: CSSProperties }) {
  const tint = TINT[relation]
  return (
    <span className={tint ? `cia-relation ${tint}` : 'cia-relation'} style={style}>
      {WORDS[relation] ?? relation}
    </span>
  )
}
