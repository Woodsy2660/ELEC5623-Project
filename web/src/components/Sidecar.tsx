import type { ReactNode } from 'react'
import { StateChip, type LifecycleState } from './StateChip.tsx'

export type SidecarTurn = {
  speaker: string
  text: string
  partial?: boolean
}

export type SidecarScope = {
  id: string
  text: string
  state: LifecycleState
}

export function Sidecar({
  pillLabel,
  turnCount,
  title,
  clock,
  turns,
  scope,
  endHref,
  registerHref,
}: {
  pillLabel: string
  turnCount: string
  title: string
  clock: string
  turns: SidecarTurn[]
  scope: SidecarScope[]
  endHref: string
  registerHref: string
}) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20, alignItems: 'center' }}>
      <div className="cia-pill">
        <span className="cia-dot-live" />
        <span>{pillLabel}</span>
        <span className="cia-counter">{turnCount}</span>
      </div>
      <div className="cia-sidecar">
        <div className="cia-sidecar__head">
          <span className="cia-dot-live" />
          <span className="cia-sidecar__title">{title}</span>
          <span className="cia-id" style={{ marginLeft: 'auto' }}>
            {clock}
          </span>
        </div>
        <div className="cia-sidecar__body" style={{ paddingBottom: 16 }}>
          <div
            style={{
              fontSize: 11,
              fontWeight: 500,
              letterSpacing: '0.08em',
              textTransform: 'uppercase',
              color: 'var(--ink-meta)',
              marginBottom: 4,
            }}
          >
            Live transcript
          </div>
          {turns.map((turn, index) => (
            <TurnLine key={`${turn.speaker}-${index}`} turn={turn} last={index === turns.length - 1 && turn.partial} />
          ))}
        </div>
        <div style={{ height: 1, background: 'var(--border-subtle)' }} />
        <div
          className="cia-sidecar__body"
          style={{ paddingTop: 16, paddingBottom: 16, background: 'var(--surface-sunken)' }}
        >
          <p className="cia-sidecar__empty">
            <b style={{ fontWeight: 500, color: 'var(--ink)' }}>No proposals yet.</b> Matching runs when the meeting
            ends — a decision made late can reverse one made early.
          </p>
        </div>
        <div className="cia-sidecar__body" style={{ paddingTop: 16 }}>
          <div
            style={{
              fontSize: 11,
              fontWeight: 500,
              letterSpacing: '0.08em',
              textTransform: 'uppercase',
              color: 'var(--ink-meta)',
              marginBottom: 10,
            }}
          >
            Current scope
          </div>
          <div className="cia-alts">
            {scope.map((item) => (
              <div key={item.id} className="cia-alt">
                <span className="cia-alt__rank">{item.id}</span>
                <span className="cia-alt__text">{item.text}</span>
                <StateChip state={item.state} />
              </div>
            ))}
          </div>
          <div style={{ display: 'flex', gap: 8, marginTop: 18 }}>
            <a href={endHref} style={{ textDecoration: 'none' }}>
              <span className="cia-btn cia-btn--primary" style={{ display: 'inline-block', fontSize: 13, padding: '8px 16px' }}>
                End and process
              </span>
            </a>
            <a href={registerHref} style={{ textDecoration: 'none', alignSelf: 'center', fontSize: 13 }}>
              Open register
            </a>
          </div>
        </div>
      </div>
    </div>
  )
}

function TurnLine({ turn, last }: { turn: SidecarTurn; last?: boolean }) {
  return (
    <div className={turn.partial ? 'cia-turn cia-turn--partial' : 'cia-turn'} style={last ? { borderBottom: 'none' } : undefined}>
      <span className="cia-turn__speaker">{turn.speaker}</span>
      <p className="cia-turn__text">
        {turn.text}
        {turn.partial ? <span style={{ opacity: 0.45 }}>…</span> : null}
      </p>
    </div>
  )
}

export function SidecarFrame({ children }: { children: ReactNode }) {
  return (
    <div
      style={{
        width: 480,
        boxSizing: 'border-box',
        padding: 24,
        background: 'var(--surface-sunken)',
        display: 'flex',
        flexDirection: 'column',
        gap: 20,
      }}
    >
      {children}
    </div>
  )
}
