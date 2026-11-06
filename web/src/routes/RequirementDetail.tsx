import { Link, useParams } from 'react-router-dom'
import { useProject, useProposals, useRequirement, useRequirements } from '../api/queries.ts'
import type { Schemas } from '../api/client.ts'
import { AppShell } from '../components/AppShell.tsx'
import { EvidenceQuote } from '../components/EvidenceQuote.tsx'
import { RelationChip } from '../components/RelationChip.tsx'
import { ScopeBar } from '../components/ScopeBar.tsx'
import { StateChip } from '../components/StateChip.tsx'

const mainStyle = {
  flex: '999 1 560px',
  minWidth: 0,
  boxSizing: 'border-box' as const,
  padding: '40px 48px',
  display: 'flex',
  flexDirection: 'column' as const,
  gap: 28,
}

export function RequirementDetailRoute() {
  const { projectId = '', requirementId = '' } = useParams()
  const project = useProject(projectId)
  const requirements = useRequirements(projectId)
  const detail = useRequirement(projectId, requirementId)
  const proposals = useProposals(projectId)
  const name = project.data?.name ?? projectId
  const reviewCount = proposals.data?.proposals.length
  const waiting = project.isPending || requirements.isPending || detail.isPending || proposals.isPending
  const problem = project.error ?? requirements.error ?? detail.error ?? proposals.error

  if (waiting) {
    return (
      <AppShell projectId={projectId} projectName={name} active="register" reviewCount={reviewCount}>
        <main style={mainStyle}>
          <p style={{ margin: 0, color: 'var(--ink-meta)' }}>Loading…</p>
        </main>
      </AppShell>
    )
  }
  if (problem || !project.data || !requirements.data || !detail.data) {
    return (
      <AppShell projectId={projectId} projectName={name} active="register" reviewCount={reviewCount}>
        <main style={mainStyle}>
          <p style={{ margin: 0 }}>{problem instanceof Error ? problem.message : 'This requirement could not be loaded.'}</p>
        </main>
      </AppShell>
    )
  }

  const agreed = requirements.data.filter((row) => row.state === 'confirmed').length
  const item = detail.data
  const textColor = item.current_state === 'proposed' ? 'var(--ink-proposed)' : 'var(--ink)'

  return (
    <AppShell projectId={projectId} projectName={project.data.name} active="register" reviewCount={reviewCount}>
      <main style={mainStyle}>
        <ScopeBar client={project.data.client} projectName={project.data.name} count={`${agreed} agreed ${agreed === 1 ? 'requirement' : 'requirements'}`} />
        <div>
          <Link to={`/projects/${projectId}/register`} style={{ fontSize: 13 }}>
            ← Register
          </Link>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, marginTop: 10, flexWrap: 'wrap' }}>
            <h1 style={titleStyle}>{item.title ?? 'Requirement history'}</h1>
            <StateChip state={item.current_state} />
          </div>
          <p style={{ margin: '10px 0 0', fontSize: 18, lineHeight: '27px', color: textColor, maxWidth: '70ch' }}>{item.current_text}</p>
          <p style={{ margin: '6px 0 0', fontSize: 13, color: 'var(--ink-meta)' }}>{item.summary}</p>
        </div>
        <section style={{ display: 'flex', flexWrap: 'wrap', gap: 32 }}>
          <div style={{ flex: '999 1 420px', minWidth: 0 }}>
            <h2 style={sectionLabel}>History</h2>
            <div style={{ display: 'flex', flexDirection: 'column' }}>
              {item.timeline.map((entry, index) => (
                <TimelineItem key={`${entry.version}-${entry.when_label}-${index}`} entry={entry} last={index === item.timeline.length - 1} />
              ))}
            </div>
          </div>
          <aside style={{ flex: '1 1 280px', minWidth: 0 }}>
            {item.audit ? (
              <>
                <h2 style={sectionLabel}>Record</h2>
                <div
                  style={{
                    background: 'var(--surface-raised)',
                    border: '1px solid var(--border-subtle)',
                    borderRadius: 10,
                    padding: 16,
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 14,
                  }}
                >
                  <AuditLine label="First recorded" value={item.audit.family_created} />
                  <div>
                    <div style={{ fontSize: 12, color: 'var(--ink-meta)' }}>Changes</div>
                    {item.audit.events.map((event) => (
                      <div key={event} style={{ fontSize: 14, lineHeight: '21px', marginTop: 4 }}>
                        {event}
                      </div>
                    ))}
                  </div>
                  <details style={{ borderTop: '1px solid var(--border-subtle)', paddingTop: 12 }}>
                    <summary style={{ cursor: 'pointer', fontSize: 12, color: 'var(--ink-meta)' }}>Technical details</summary>
                    <div style={{ marginTop: 10, display: 'flex', flexDirection: 'column', gap: 10 }}>
                      <div>
                        <div style={{ fontSize: 12, color: 'var(--ink-meta)' }}>AI model</div>
                        <div className="cia-id">{item.audit.model}</div>
                      </div>
                      <div>
                        <div style={{ fontSize: 12, color: 'var(--ink-meta)' }}>Prompt version</div>
                        <div className="cia-id" style={{ wordBreak: 'break-all' }}>{item.audit.prompt_version}</div>
                      </div>
                    </div>
                  </details>
                </div>
              </>
            ) : null}
            <p style={{ margin: item.audit ? '14px 0 0' : 0, fontSize: 13, lineHeight: '20px', color: 'var(--ink-meta)' }}>
              Every version keeps the client’s words it came from, so anyone can see why scope changed.
            </p>
          </aside>
        </section>
      </main>
    </AppShell>
  )
}

function TimelineItem({ entry, last }: { entry: Schemas['TimelineEntry']; last: boolean }) {
  const color = entry.historical ? 'var(--ink-historical)' : entry.relation || entry.state === 'proposed' ? 'var(--ink-proposed)' : 'var(--ink)'
  return (
    <div style={{ display: 'flex', gap: 16 }}>
      <div style={{ flex: '0 0 10px', display: 'flex', flexDirection: 'column', alignItems: 'center', paddingTop: 6 }}>
        <span
          style={
            entry.historical
              ? { width: 10, height: 10, borderRadius: '50%', border: '1px solid var(--ink-historical)', boxSizing: 'border-box', display: 'block' }
              : { width: 10, height: 10, borderRadius: '50%', background: 'var(--ink-proposed)', display: 'block' }
          }
        />
        {last ? null : <span style={{ width: 1, flex: 1, background: 'var(--border-strong)', display: 'block' }} />}
      </div>
      <div style={{ flex: '999 1 auto', minWidth: 0, paddingBottom: last ? 0 : 28 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <span style={{ fontSize: 13, fontWeight: 500 }}>Version {entry.version}</span>
          {entry.relation ? <RelationChip relation={entry.relation} /> : null}
          {entry.state ? <StateChip state={entry.state} /> : null}
          <span style={{ fontSize: 13, color: 'var(--ink-meta)' }}>{entry.when_label}</span>
        </div>
        <p
          style={{
            margin: '8px 0',
            fontSize: 15,
            lineHeight: '23px',
            color,
            textDecoration: entry.struck ? 'line-through' : undefined,
            textDecorationThickness: entry.struck ? '1px' : undefined,
          }}
        >
          {entry.text}
        </p>
        {entry.evidence?.map((quote) => (
          <EvidenceQuote
            key={quote.turn_id}
            speaker={quote.speaker}
            turnId={quote.turn_id}
            before={quote.before}
            span={quote.span}
            after={quote.after}
            style={{ marginTop: 10 }}
          />
        ))}
        {entry.footer ? <div style={{ marginTop: 10, fontSize: 13, color: 'var(--ink-meta)' }}>{entry.footer}</div> : null}
      </div>
    </div>
  )
}

function AuditLine({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div style={{ fontSize: 12, color: 'var(--ink-meta)' }}>{label}</div>
      <div style={{ fontSize: 14 }}>{value}</div>
    </div>
  )
}

const titleStyle = {
  margin: 0,
  fontFamily: 'var(--font-display)',
  fontSize: 38,
  lineHeight: '44px',
  letterSpacing: '-0.01em',
}

const sectionLabel = {
  margin: '0 0 14px',
  fontSize: 11,
  fontWeight: 500,
  letterSpacing: '0.08em',
  textTransform: 'uppercase' as const,
  color: 'var(--ink-meta)',
}
