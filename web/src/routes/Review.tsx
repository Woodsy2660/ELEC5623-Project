import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import type { CSSProperties } from 'react'
import { useDecide, useProject, useProposals, useRequirements } from '../api/queries.ts'
import type { Schemas } from '../api/client.ts'
import { AppShell } from '../components/AppShell.tsx'
import { ProposalCard } from '../components/ProposalCard.tsx'
import { RelationChip } from '../components/RelationChip.tsx'
import { ScopeBar } from '../components/ScopeBar.tsx'

const queueChip: CSSProperties = { fontSize: 11, padding: '1px 6px' }

export function ReviewRoute() {
  const { projectId = '' } = useParams()
  const navigate = useNavigate()
  const project = useProject(projectId)
  const proposals = useProposals(projectId)
  const requirements = useRequirements(projectId)
  const decide = useDecide(projectId)
  const [picked, setPicked] = useState<string | null>(null)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')
  const [notice, setNotice] = useState<string | null>(null)

  const name = project.data?.name ?? projectId
  const reviewCount = proposals.data?.proposals.length
  const waiting = project.isPending || proposals.isPending || requirements.isPending
  const problem = project.error ?? proposals.error ?? requirements.error

  if (waiting) {
    return (
      <AppShell projectId={projectId} projectName={name} active="review" reviewCount={reviewCount}>
        <main style={{ flex: '999 1 520px', padding: '32px 40px' }}>
          <p style={{ margin: 0, color: 'var(--ink-meta)' }}>Loading…</p>
        </main>
      </AppShell>
    )
  }
  if (problem || !project.data || !proposals.data || !requirements.data) {
    return (
      <AppShell projectId={projectId} projectName={name} active="review" reviewCount={reviewCount}>
        <main style={{ flex: '999 1 520px', padding: '32px 40px' }}>
          <p style={{ margin: 0 }}>{problem instanceof Error ? problem.message : 'The queue could not be loaded.'}</p>
        </main>
      </AppShell>
    )
  }

  const list = proposals.data
  const unresolved = list.proposals.find((item) => item.unresolved)
  const selected = list.proposals.find((item) => item.id === picked) ?? unresolved ?? list.proposals[0]
  const discarded = list.discarded_candidates
  const discardedNoun = discarded === 1 ? 'suggestion was' : 'suggestions were'

  function choose(id: string) {
    setPicked(id)
    setEditing(false)
    setNotice(null)
  }

  function onDecide(action: 'confirm' | 'reject' | 'edit') {
    if (!selected) return
    setNotice(null)
    decide.mutate(
      {
        proposalId: selected.id,
        body: {
          ...(action === 'edit' ? { action, edited_text: draft } : { action }),
          ...(action !== 'reject' && selected.project_snapshot_token
            ? { project_snapshot_token: selected.project_snapshot_token }
            : {}),
        },
      },
      {
        onSuccess: () => setEditing(false),
        onError: (error) => setNotice(error instanceof Error ? error.message : 'The decision was refused'),
      },
    )
  }

  return (
    <AppShell projectId={projectId} projectName={project.data.name} active="review" reviewCount={list.proposals.length}>
      <div
        style={{
          flex: '0 0 300px',
          boxSizing: 'border-box',
          padding: '32px 12px',
          borderRight: '1px solid var(--border-subtle)',
          display: 'flex',
          flexDirection: 'column',
          gap: 4,
        }}
      >
        <div style={{ padding: '0 12px 12px' }}>
          <div style={{ fontSize: 15, fontWeight: 500 }}>
            {list.proposals.length} {list.proposals.length === 1 ? 'suggestion' : 'suggestions'} to review
          </div>
        </div>
        {list.proposals.map((item) => (
          <button
            key={item.id}
            type="button"
            className="qitem"
            aria-current={selected?.id === item.id ? 'true' : undefined}
            onClick={() => choose(item.id)}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
              <RelationChip relation={item.classification.relation} style={queueChip} />
            </div>
            <div
              style={{
                fontSize: 13,
                lineHeight: '19px',
                color: selected?.id === item.id ? 'var(--ink)' : 'var(--ink-proposed)',
              }}
            >
              {preview(item.statement)}
            </div>
          </button>
        ))}
        {discarded > 0 ? (
          <div style={{ marginTop: 12, padding: 12, borderTop: '1px solid var(--border-subtle)', fontSize: 12, lineHeight: '18px', color: 'var(--ink-meta)' }}>
            {discarded} {discardedNoun} left out because the quote could not be found in the transcript.
          </div>
        ) : null}
      </div>
      <main style={{ flex: '999 1 520px', minWidth: 0, boxSizing: 'border-box', padding: '32px 40px' }}>
        <ScopeBar
          client={project.data.client}
          projectName={project.data.name}
          count={inScope(requirements.data)}
        />
        {selected ? (
          <div style={{ marginTop: 18 }}>
            <ProposalCard
              statement={selected.statement}
              unresolved={selected.unresolved}
              relation={selected.classification.relation}
              proposalStatus={selected.proposal_status}
              toState={selected.to_state}
              evidence={selected.evidence.map((quote) => ({
                speaker: quote.speaker,
                turnId: quote.turn_id,
                before: quote.before,
                span: quote.span,
                after: quote.after,
              }))}
              speakerName={selected.speaker_name}
              speakerRole={selected.speaker_role}
              speakerCanConfirm={selected.speaker_can_confirm}
              authorityNote={selected.authority_note}
              rationale={selected.classification.rationale}
              retrieved={selected.retrieved.map((item) => ({
                rank: item.rank,
                text: item.text,
                state: item.state,
                chosen: item.chosen,
              }))}
              projectChanges={(selected.project_changes ?? []).map((change) => ({
                requirementId: change.requirement_id,
                change: change.change,
                previousVersion: change.previous_version ?? null,
                previousState: change.previous_state ?? null,
                currentVersion: change.current_version ?? null,
                currentState: change.current_state ?? null,
                currentText: change.current_text ?? null,
              }))}
              canConfirm={selected.can_confirm}
              canConfirmReason={selected.can_confirm_reason}
              decided={selected.decision != null}
              busy={decide.isPending}
              notice={notice ?? selected.decision?.reason}
              editing={editing}
              draft={draft}
              onDraft={setDraft}
              onConfirm={() => onDecide('confirm')}
              onReject={() => onDecide('reject')}
              onEdit={() => {
                if (!editing) {
                  setEditing(true)
                  setDraft(selected.statement)
                  return
                }
                onDecide('edit')
              }}
              onJump={
                selected.requirement_id
                  ? () => navigate(`/projects/${projectId}/requirements/${selected.requirement_id}`)
                  : undefined
              }
            />
          </div>
        ) : (
          <p style={{ margin: '28px 0 0', color: 'var(--ink-meta)' }}>No proposals in this queue.</p>
        )}
        <p style={{ margin: '20px 0 0', maxWidth: 760, fontSize: 13, lineHeight: '20px', color: 'var(--ink-meta)' }}>
          The AI only suggests. Nothing changes in the agreed scope until a reviewer confirms it.
        </p>
      </main>
    </AppShell>
  )
}

function preview(text: string): string {
  return text.length > 90 ? `${text.slice(0, 88).trimEnd()}…` : text
}

function inScope(rows: Schemas['RegisterRow'][]): string {
  const agreed = rows.filter((row) => row.state === 'confirmed').length
  return `${agreed} agreed ${agreed === 1 ? 'requirement' : 'requirements'}`
}
