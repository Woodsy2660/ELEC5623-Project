import type { CSSProperties } from 'react'

export function EvidenceQuote({
  speaker,
  turnId,
  before,
  span,
  after,
  onJump,
  style,
}: {
  speaker: string
  turnId: string
  before: string
  span: string
  after: string
  onJump?: () => void
  style?: CSSProperties
}) {
  return (
    <div className="cia-evidence" style={style}>
      <div className="cia-evidence__meta">
        <span className="cia-evidence__speaker">{speaker}</span>
        <span className="cia-id">{turnId}</span>
      </div>
      <p className="cia-evidence__quote">
        {before ? <span className="cia-evidence__context">{before}</span> : null}
        {span ? <span className="cia-evidence__span">{span}</span> : null}
        {after ? <span className="cia-evidence__context">{after}</span> : null}
      </p>
      {onJump ? (
        <a
          className="cia-evidence__link"
          href="#transcript"
          onClick={(event) => {
            event.preventDefault()
            onJump()
          }}
        >
          Open in transcript
        </a>
      ) : null}
    </div>
  )
}
