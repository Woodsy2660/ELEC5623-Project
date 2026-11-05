export type LifecycleState = 'confirmed' | 'proposed' | 'contradicted' | 'superseded' | 'withdrawn'

const LABEL: Record<LifecycleState, string> = {
  confirmed: 'Confirmed',
  proposed: 'Proposed',
  contradicted: 'In conflict',
  superseded: 'Replaced',
  withdrawn: 'Withdrawn',
}

export function StateChip({ state }: { state: LifecycleState }) {
  return <span className={`cia-chip cia-chip--${state}`}>{LABEL[state]}</span>
}
