import type { ReactNode } from 'react'

type Tone = 'on' | 'off' | 'live'

export function StatusTag({ tone = 'off', children }: { tone?: Tone; children: ReactNode }) {
  const modifier = tone === 'on' ? ' cia-tag--on' : tone === 'live' ? ' cia-tag--live' : ''
  return <span className={`cia-tag${modifier}`}>{children}</span>
}
