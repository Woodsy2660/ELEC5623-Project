import type { LifecycleState } from './StateChip.tsx'
import type { RelationLabel } from './RelationChip.tsx'
import { AuthorityBadge } from './AuthorityBadge.tsx'
import { EvidenceQuote } from './EvidenceQuote.tsx'
import { RelationChip } from './RelationChip.tsx'
import { StateChip } from './StateChip.tsx'

export type ProposalEvidence = {
  speaker: string
  turnId: string
  before: string
  span: string
  after: string
}

export type RetrievedRow = {
  rank: number
  text: string
  state: LifecycleState
  chosen: boolean
}

export function ProposalCard({
  scopeLabel,
  statement,
  unresolved,
  relation,
  proposalStatus,
  toState,
  evidence,
  speakerName,
  speakerRole,
  speakerCanConfirm,
  authorityNote,
  rationale,
  retrieved,
  canConfirm,
  canConfirmReason,
  decided,
  busy,
  notice,
  editing,
  draft,
  onDraft,
  onConfirm,
  onReject,
  onEdit,
  onJump,
}: {
  scopeLabel: string
  statement: string
  unresolved: boolean
  relation: RelationLabel
  proposalStatus: LifecycleState
  toState: LifecycleState | null
  evidence: ProposalEvidence[]
  speakerName: string
  speakerRole: string
  speakerCanConfirm: boolean
  authorityNote?: string | null
  rationale: string
  retrieved: RetrievedRow[]
  canConfirm: boolean
  canConfirmReason: string
  decided: boolean
  busy?: boolean
  notice?: string | null
  editing?: boolean
  draft?: string
  onDraft?: (value: string) => void
  onConfirm: () => void
  onReject: () => void
  onEdit: () => void
  onJump?: () => void
}) {
  const words =
    authorityNote ??
    `${speakerName} (${speakerRole}) ${speakerCanConfirm ? 'can' : 'cannot'} confirm scope`
  const note = notice || (decided ? '' : canConfirm ? '' : canConfirmReason)
  return (
    <div className={unresolved ? 'cia-proposal cia-proposal--unresolved' : 'cia-proposal'} style={{ maxWidth: 760 }}>
      <div className="cia-proposal__head">
        <div>
          <p className="cia-proposal__statement">{statement}</p>
          <div className="cia-proposal__transition">
            <span className="cia-id">{scopeLabel}</span>
            <StateChip state={proposalStatus} />
            {toState ? (
              <>
                <span>→</span>
                <StateChip state={toState} />
              </>
            ) : null}
          </div>
        </div>
        <RelationChip relation={relation} />
      </div>
      <div className="cia-proposal__body">
        <div>
          <div className="cia-proposal__section-label">Evidence</div>
          {evidence.map((quote) => (
            <EvidenceQuote
              key={quote.turnId}
              speaker={quote.speaker}
              turnId={quote.turnId}
              before={quote.before}
              span={quote.span}
              after={quote.after}
              onJump={onJump}
            />
          ))}
          <div style={{ marginTop: 10 }}>
            <AuthorityBadge can={speakerCanConfirm}>{words}</AuthorityBadge>
          </div>
        </div>
        <div>
          <div className="cia-proposal__section-label">Model rationale</div>
          <p className="cia-rationale">{rationale}</p>
        </div>
        <div>
          <div className="cia-proposal__section-label">
            Retrieved alternatives ({retrieved.length} considered)
          </div>
          <div className="cia-alts">
            {retrieved.map((item) => (
              <div key={item.rank} className={item.chosen ? 'cia-alt cia-alt--chosen' : 'cia-alt'}>
                <span className="cia-alt__rank">{item.rank}</span>
                <span className="cia-alt__text">{item.text}</span>
                <StateChip state={item.state} />
              </div>
            ))}
          </div>
        </div>
      </div>
      <div className="cia-actions">
        {editing ? (
          <label style={{ flex: '1 1 100%' }}>
            <span className="cia-proposal__section-label">Replacement text</span>
            <textarea
              className="fld"
              rows={3}
              value={draft ?? ''}
              onChange={(event) => onDraft?.(event.target.value)}
            />
          </label>
        ) : null}
        <button type="button" className="cia-btn cia-btn--primary" disabled={!canConfirm || busy || decided} onClick={onConfirm}>
          Confirm
        </button>
        <button type="button" className="cia-btn" disabled={busy || decided} onClick={onEdit}>
          {editing ? 'Save edit' : 'Edit'}
        </button>
        <button type="button" className="cia-btn cia-btn--danger" disabled={busy || decided} onClick={onReject}>
          Reject
        </button>
        {note ? <span className="cia-actions__note">{note}</span> : null}
      </div>
    </div>
  )
}
