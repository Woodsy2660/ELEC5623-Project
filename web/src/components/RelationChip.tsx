import type { CSSProperties } from 'react'

export type RelationLabel =
  | 'new'
  | 'refinement'
  | 'contradiction'
  | 'supersession'
  | 'restatement'
  | 'not_requirement'

const TINT: Partial<Record<RelationLabel, string>> = {
  contradiction: 'cia-relation--contradiction',
  supersession: 'cia-relation--supersession',
}

export function RelationChip({ relation, style }: { relation: RelationLabel; style?: CSSProperties }) {
  const tint = TINT[relation]
  return (
    <span className={tint ? `cia-relation ${tint}` : 'cia-relation'} style={style}>
      {relation}
    </span>
  )
}
