import type { LifecycleState } from './StateChip.tsx'
import type { RelationLabel } from './RelationChip.tsx'
import { AuthorityBadge } from './AuthorityBadge.tsx'
import { EvidenceQuote } from './EvidenceQuote.tsx'
import { RelationChip } from './RelationChip.tsx'
import { StateChip } from './StateChip.tsx'

const RELATION_LINE: Record<RelationLabel, string> = {
  new: 'New requirement from this meeting',
  refinement: 'Adds detail to an agreed requirement',
  contradiction: 'Conflicts with an agreed requirement',
  supersession: 'Would replace an agreed requirement',
  restatement: 'Repeats an agreed requirement',
  not_requirement: 'Not a requirement',
}

const CHANGE_WORD = { added: 'Added', changed: 'Changed', removed: 'Removed' } as const

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

export type ProjectChangeRow = {
  requirementId: string
  change: 'added' | 'changed' | 'removed'
  previousVersion: number | null
  previousState: LifecycleState | null
  currentVersion: number | null
  currentState: LifecycleState | null
  currentText: string | null
}

export function ProposalCard({
  statement,
  unresolved,
  relation,
  evidence,
  speakerName,
  speakerRole,
  speakerCanConfirm,
  authorityNote,
  rationale,
  retrieved,
  projectChanges,
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
  scopeLabel?: string
  statement: string
  unresolved: boolean
  relation: RelationLabel
  proposalStatus?: LifecycleState
  toState?: LifecycleState | null
  evidence: ProposalEvidence[]
  speakerName: string
  speakerRole: string
  speakerCanConfirm: boolean
  authorityNote?: string | null
  rationale: string
  retrieved: RetrievedRow[]
  projectChanges?: ProjectChangeRow[]
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
    `${speakerName} · ${speakerRole} · ${speakerCanConfirm ? 'can approve scope' : 'cannot approve scope'}`
  const note = notice || (decided ? '' : canConfirm ? '' : canConfirmReason)
  return (
    <div className={unresolved ? 'cia-proposal cia-proposal--unresolved' : 'cia-proposal'} style={{ maxWidth: 760 }}>
      <div className="cia-proposal__head">
        <div>
          <p className="cia-proposal__statement">{statement}</p>
          <div className="cia-proposal__transition">
            <span>{RELATION_LINE[relation] ?? ''}</span>
          </div>
        </div>
        <RelationChip relation={relation} />
      </div>
      <div className="cia-proposal__body">
        {projectChanges?.length ? (
          <section
            aria-label="Register changes since proposal"
            style={{
              padding: '14px 16px',
              border: '1px solid var(--border-strong)',
              background: 'var(--surface-sunken)',
              borderRadius: 8,
            }}
          >
            <div className="cia-proposal__section-label">Scope changed since this suggestion</div>
            <p style={{ margin: '8px 0 12px', fontSize: 13, lineHeight: '20px' }}>
              Scope has changed since this was suggested. Compare it with the entries below before you confirm.
            </p>
            <div style={{ display: 'grid', gap: 10 }}>
              {projectChanges.map((change) => (
                <div key={change.requirementId} style={{ borderTop: '1px solid var(--border-subtle)', paddingTop: 8 }}>
                  <div style={{ fontSize: 12, fontWeight: 600 }}>{CHANGE_WORD[change.change]}</div>
                  <div style={{ fontSize: 12, color: 'var(--ink-meta)', marginTop: 3 }}>
                    {change.previousState == null ? 'Not in scope when this was suggested' : `Was ${change.previousState}`}
                    {' → '}
                    {change.currentState == null ? 'no longer in scope' : `now ${change.currentState}`}
                  </div>
                  {change.currentText ? <div style={{ fontSize: 13, marginTop: 5 }}>{change.currentText}</div> : null}
                </div>
              ))}
            </div>
          </section>
        ) : null}
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
          <div className="cia-proposal__section-label">Why the AI suggested this</div>
          <p className="cia-rationale">{rationale}</p>
        </div>
        {retrieved.length ? (
          <div>
            <div className="cia-proposal__section-label">Related requirement history</div>
            <div className="cia-alts">
              {retrieved.map((item) => (
                <div key={item.rank} className={item.chosen ? 'cia-alt cia-alt--chosen' : 'cia-alt'}>
                  <span className="cia-alt__text">{item.text}</span>
                  {item.chosen ? <span style={{ fontSize: 12, color: 'var(--ink-meta)' }}>Matched</span> : null}
                  <StateChip state={item.state} />
                </div>
              ))}
            </div>
          </div>
        ) : null}
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
