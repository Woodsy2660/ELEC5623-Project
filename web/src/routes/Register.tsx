import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useMeetings, useProject, useProposals, useRequirements } from '../api/queries.ts'
import { api, type Schemas } from '../api/client.ts'
import { AppShell } from '../components/AppShell.tsx'
import { RegisterTable } from '../components/RegisterTable.tsx'
import { ScopeBar } from '../components/ScopeBar.tsx'
import type { LifecycleState } from '../components/StateChip.tsx'

type Filter = 'all' | 'confirmed' | 'proposed' | 'contradicted' | 'history'

const STATE_ORDER: LifecycleState[] = ['confirmed', 'proposed', 'contradicted', 'superseded', 'withdrawn']

const mainStyle = {
  flex: '999 1 560px',
  minWidth: 0,
  boxSizing: 'border-box' as const,
  padding: '40px 48px',
  display: 'flex',
  flexDirection: 'column' as const,
  gap: 28,
}

export function RegisterRoute() {
  const { projectId = '' } = useParams()
  const project = useProject(projectId)
  const requirements = useRequirements(projectId)
  const proposals = useProposals(projectId)
  const meetings = useMeetings(projectId)
  const [filter, setFilter] = useState<Filter>('all')

  const name = project.data?.name ?? projectId
  const reviewCount = proposals.data?.proposals.length
  const waiting = project.isPending || requirements.isPending || proposals.isPending || meetings.isPending
  const problem = project.error ?? requirements.error ?? proposals.error ?? meetings.error

  if (waiting) {
    return (
      <AppShell projectId={projectId} projectName={name} active="register" reviewCount={reviewCount}>
        <main style={mainStyle}>
          <p style={{ margin: 0, color: 'var(--ink-meta)' }}>Loading…</p>
        </main>
      </AppShell>
    )
  }
  if (problem || !project.data || !requirements.data || !proposals.data || !meetings.data) {
    return (
      <AppShell projectId={projectId} projectName={name} active="register" reviewCount={reviewCount}>
        <main style={mainStyle}>
          <p style={{ margin: 0 }}>{problem instanceof Error ? problem.message : 'This project could not be loaded.'}</p>
        </main>
      </AppShell>
    )
  }

  const rows = [...requirements.data].sort(byStateThenId)
  const families = new Set(rows.map((row) => row.requirement_id)).size
  const past = meetings.data.filter((meeting) => meeting.status === 'past').length
  const counts: Record<Filter, number> = {
    all: rows.length,
    confirmed: rows.filter((row) => row.state === 'confirmed').length,
    proposed: rows.filter((row) => row.state === 'proposed').length,
    contradicted: rows.filter((row) => row.state === 'contradicted').length,
    history: rows.filter((row) => row.state === 'superseded' || row.state === 'withdrawn').length,
  }
  const replaced = rows.filter((row) => row.state === 'superseded').length
  const visible = rows.filter((row) => matches(row, filter))
  const snapshot = past > 0 ? ` · after ${past} ${past === 1 ? 'meeting' : 'meetings'}` : ''

  return (
    <AppShell projectId={projectId} projectName={project.data.name} active="register" reviewCount={reviewCount}>
      <main style={mainStyle}>
        <ScopeBar
          client={project.data.client}
          projectName={project.data.name}
          count={`${counts.confirmed} agreed · ${replaced} replaced`}
        />
        <header style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 24, flexWrap: 'wrap' }}>
          <div>
            <h1 style={titleStyle}>Register</h1>
            <p style={subtitleStyle}>
              {families} {families === 1 ? 'requirement' : 'requirements'}
              {snapshot}
            </p>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button type="button" className="cia-btn" onClick={() => { window.location.href = api.exportUrl(projectId) }}>
              Export
            </button>
            <Link to={`/projects/${projectId}/review`} style={{ textDecoration: 'none' }}>
              <span className="cia-btn cia-btn--primary" style={{ display: 'inline-block' }}>
                {reviewCount ? `Review ${reviewCount} ${reviewCount === 1 ? 'suggestion' : 'suggestions'}` : 'Review queue'}
              </span>
            </Link>
          </div>
        </header>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
          <FilterButton label={`All ${counts.all}`} on={filter === 'all'} onClick={() => setFilter('all')} />
          <FilterButton label={`Confirmed ${counts.confirmed}`} on={filter === 'confirmed'} onClick={() => setFilter('confirmed')} />
          {counts.proposed || filter === 'proposed' ? (
            <FilterButton label={`Proposed ${counts.proposed}`} on={filter === 'proposed'} onClick={() => setFilter('proposed')} />
          ) : null}
          {counts.contradicted || filter === 'contradicted' ? (
            <FilterButton
              label={`In conflict ${counts.contradicted}`}
              on={filter === 'contradicted'}
              onClick={() => setFilter('contradicted')}
            />
          ) : null}
          {counts.history || filter === 'history' ? (
            <FilterButton label={`History ${counts.history}`} on={filter === 'history'} onClick={() => setFilter('history')} />
          ) : null}
        </div>
        <div style={{ background: 'var(--surface-raised)', border: '1px solid var(--border-subtle)', borderRadius: 10, overflow: 'hidden' }}>
          <RegisterTable
            rows={visible.map((row) => ({
              key: `${row.requirement_id}-v${row.version}`,
              versionLabel: row.version_label,
              text: row.text,
              state: row.state,
              changedLabel: row.changed_label,
              note: row.note,
              href: rowHref(projectId, row, proposals.data.proposals),
            }))}
          />
        </div>
        <p style={{ margin: 0, fontSize: 13, lineHeight: '20px', color: 'var(--ink-meta)', maxWidth: '78ch' }}>
          Replaced and withdrawn requirements remain available in history, with their original evidence.
        </p>
      </main>
    </AppShell>
  )
}

function matches(row: Schemas['RegisterRow'], filter: Filter): boolean {
  if (filter === 'all') return true
  if (filter === 'history') return row.state === 'superseded' || row.state === 'withdrawn'
  return row.state === filter
}

function byStateThenId(a: Schemas['RegisterRow'], b: Schemas['RegisterRow']): number {
  const byState = STATE_ORDER.indexOf(a.state) - STATE_ORDER.indexOf(b.state)
  if (byState !== 0) return byState
  const byId = a.requirement_id.localeCompare(b.requirement_id)
  if (byId !== 0) return byId
  return b.version - a.version
}

function rowHref(projectId: string, row: Schemas['RegisterRow'], proposals: Schemas['ProposalOut'][]): string {
  const related = proposals.filter((proposal) => proposal.requirement_id === row.requirement_id)
  if (row.state === 'proposed' || related.some((proposal) => proposal.unresolved)) {
    return `/projects/${projectId}/review`
  }
  return `/projects/${projectId}/requirements/${row.requirement_id}`
}

function FilterButton({ label, on, onClick }: { label: string; on: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      className="cia-btn"
      style={
        on
          ? { fontSize: 13, padding: '6px 12px', background: 'var(--ink)', color: 'var(--surface-raised)', borderColor: 'var(--ink)' }
          : { fontSize: 13, padding: '6px 12px' }
      }
      onClick={onClick}
    >
      {label}
    </button>
  )
}

const titleStyle = {
  margin: 0,
  fontFamily: 'var(--font-display)',
  fontSize: 38,
  lineHeight: '44px',
  letterSpacing: '-0.01em',
}

const subtitleStyle = { margin: '6px 0 0', fontSize: 14, color: 'var(--ink-meta)' }
