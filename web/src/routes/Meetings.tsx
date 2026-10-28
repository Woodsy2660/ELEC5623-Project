import { Link, useParams } from 'react-router-dom'
import { useMeetings, useProject, useProposals, useRequirements, useSettings } from '../api/queries.ts'
import type { Schemas } from '../api/client.ts'
import { AppShell } from '../components/AppShell.tsx'
import type { RelationLabel } from '../components/RelationChip.tsx'
import { RelationChip } from '../components/RelationChip.tsx'
import { StateChip } from '../components/StateChip.tsx'
import { StatusTag } from '../components/StatusTag.tsx'

const PLURAL: Record<RelationLabel, [string, string]> = {
  new: ['new', 'new'],
  refinement: ['refinement', 'refinements'],
  contradiction: ['contradiction', 'contradictions'],
  supersession: ['supersession', 'supersessions'],
  restatement: ['restatement', 'restatements'],
  not_requirement: ['not a requirement', 'not requirements'],
}

export function MeetingsRoute() {
  const { projectId = '' } = useParams()
  const project = useProject(projectId)
  const meetings = useMeetings(projectId)
  const proposals = useProposals(projectId)
  const requirements = useRequirements(projectId)
  const settings = useSettings(projectId)
  const name = project.data?.name ?? projectId
  const reviewCount = proposals.data?.proposals.length
  const waiting = project.isPending || meetings.isPending || proposals.isPending || requirements.isPending || settings.isPending
  const problem = project.error ?? meetings.error ?? proposals.error ?? requirements.error ?? settings.error

  if (waiting) {
    return (
      <AppShell projectId={projectId} projectName={name} active="meetings" reviewCount={reviewCount}>
        <main style={mainStyle}>
          <p style={{ margin: 0, color: 'var(--ink-meta)' }}>Loading…</p>
        </main>
      </AppShell>
    )
  }
  if (problem || !project.data || !meetings.data || !settings.data || !requirements.data || !proposals.data) {
    return (
      <AppShell projectId={projectId} projectName={name} active="meetings" reviewCount={reviewCount}>
        <main style={mainStyle}>
          <p style={{ margin: 0 }}>{problem instanceof Error ? problem.message : 'Meetings could not be loaded.'}</p>
        </main>
      </AppShell>
    )
  }

  const past = meetings.data.filter((meeting) => meeting.status === 'past')
  const upcoming = meetings.data.filter((meeting) => meeting.status === 'live' || meeting.status === 'upcoming')
  const calendarOn = settings.data.connections.some((item) => item.status === 'connected')

  // Sort meetings oldest to newest
  const sortedPast = [...past].sort((a, b) => (a.ordinal ?? 0) - (b.ordinal ?? 0))

  // Get current requirements (latest version of each family)
  const currentReqs = getCurrentRequirements(requirements.data)

  // Pending proposals that need attention
  const pendingProposals = proposals.data.proposals.filter(p => !p.decision)

  return (
    <AppShell projectId={projectId} projectName={project.data.name} active="meetings" reviewCount={reviewCount}>
      <main style={mainStyle}>
        {/* Header with project context */}
        <header style={{ marginBottom: 8 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 8 }}>
            <span style={{ fontSize: 13, color: 'var(--ink-meta)' }}>{project.data.client}</span>
            <span style={{ color: 'var(--border-strong)' }}>·</span>
            <span style={{ fontSize: 13, fontWeight: 500, color: 'var(--ink)' }}>{project.data.name}</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 24, flexWrap: 'wrap' }}>
            <div>
              <h1 style={titleStyle}>Meetings</h1>
              <p style={subtitleStyle}>
                {sortedPast.length} processed · {currentReqs.length} requirements tracked
              </p>
            </div>
            <Link to={`/projects/${projectId}/import`} style={{ textDecoration: 'none' }}>
              <span className="cia-btn" style={{ display: 'inline-block' }}>
                Import transcript
              </span>
            </Link>
          </div>
        </header>

        {/* Two column layout */}
        <div style={{ display: 'flex', gap: 32, flexWrap: 'wrap' }}>
          {/* Left column: Attention + Meetings */}
          <div style={{ flex: '1 1 480px', minWidth: 0, display: 'flex', flexDirection: 'column', gap: 24 }}>

            {/* Attention Needed Section */}
            {pendingProposals.length > 0 && (
              <section>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
                  <div style={attentionDot} />
                  <h2 style={sectionTitle}>Attention needed</h2>
                  <span style={{
                    background: 'var(--state-contradicted)',
                    color: 'white',
                    fontSize: 11,
                    fontWeight: 600,
                    padding: '2px 8px',
                    borderRadius: 'var(--radius-pill)'
                  }}>
                    {pendingProposals.length}
                  </span>
                </div>
                <div style={{
                  background: 'var(--surface-raised)',
                  border: '1px solid var(--border-subtle)',
                  borderRadius: 'var(--radius-md)',
                  overflow: 'hidden'
                }}>
                  {pendingProposals.slice(0, 5).map((proposal, index) => (
                    <Link
                      key={proposal.id}
                      to={`/projects/${projectId}/review`}
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: 12,
                        padding: '14px 16px',
                        borderBottom: index === Math.min(pendingProposals.length - 1, 4) ? undefined : '1px solid var(--border-subtle)',
                        textDecoration: 'none',
                        color: 'inherit',
                        transition: 'background 0.15s ease',
                      }}
                      className="proposal-row"
                    >
                      <span className="cia-id" style={{ flex: '0 0 48px' }}>
                        {proposal.requirement_id ?? 'NEW'}
                      </span>
                      <span style={{
                        flex: '1 1 auto',
                        minWidth: 0,
                        fontSize: 14,
                        color: 'var(--ink-proposed)',
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap'
                      }}>
                        {proposal.queue_text}
                      </span>
                      <RelationChip relation={proposal.classification.relation} style={{ fontSize: 11, padding: '1px 8px' }} />
                    </Link>
                  ))}
                  {pendingProposals.length > 5 && (
                    <Link
                      to={`/projects/${projectId}/review`}
                      style={{
                        display: 'block',
                        padding: '12px 16px',
                        fontSize: 13,
                        color: 'var(--ink)',
                        textAlign: 'center',
                        background: 'var(--surface-sunken)',
                        textDecoration: 'none',
                      }}
                    >
                      View all {pendingProposals.length} proposals →
                    </Link>
                  )}
                </div>
              </section>
            )}

            {/* Upcoming Meetings */}
            {upcoming.length > 0 && (
              <section>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
                  <h2 style={sectionTitle}>Upcoming</h2>
                  {calendarOn && <StatusTag tone="on">Calendar connected</StatusTag>}
                </div>
                <div style={{
                  background: 'var(--surface-raised)',
                  border: '1px solid var(--border-subtle)',
                  borderRadius: 'var(--radius-md)'
                }}>
                  {upcoming.map((meeting, index) => (
                    <UpcomingRow key={meeting.id} meeting={meeting} projectId={projectId} last={index === upcoming.length - 1} />
                  ))}
                </div>
              </section>
            )}

            {/* Meeting History */}
            <section>
              <h2 style={{ ...sectionTitle, marginBottom: 12 }}>Meeting history</h2>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                {sortedPast.length === 0 ? (
                  <div style={{
                    padding: '24px',
                    background: 'var(--surface-sunken)',
                    borderRadius: 'var(--radius-md)',
                    textAlign: 'center'
                  }}>
                    <p style={{ margin: 0, fontSize: 14, color: 'var(--ink-meta)' }}>
                      No meetings processed yet. Import a transcript to get started.
                    </p>
                  </div>
                ) : (
                  sortedPast.map((meeting) => (
                    <PastCard key={meeting.id} meeting={meeting} projectId={projectId} />
                  ))
                )}
              </div>
            </section>
          </div>

          {/* Right column: Requirements Preview */}
          <aside style={{ flex: '0 1 340px', minWidth: 280 }}>
            <div style={{ position: 'sticky', top: 24 }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
                <h2 style={sectionTitle}>Requirements</h2>
                <Link to={`/projects/${projectId}/register`} style={{ fontSize: 12, color: 'var(--ink-meta)' }}>
                  View full register →
                </Link>
              </div>
              <div style={{
                background: 'var(--surface-raised)',
                border: '1px solid var(--border-subtle)',
                borderRadius: 'var(--radius-md)',
                maxHeight: 'calc(100vh - 180px)',
                overflow: 'auto',
              }}>
                {currentReqs.length === 0 ? (
                  <div style={{ padding: '20px', textAlign: 'center' }}>
                    <p style={{ margin: 0, fontSize: 13, color: 'var(--ink-meta)' }}>
                      No requirements yet.
                    </p>
                  </div>
                ) : (
                  <div style={{ padding: '16px 20px' }}>
                    {currentReqs.map((req, index) => (
                      <div
                        key={req.requirement_id}
                        style={{
                          paddingBottom: index === currentReqs.length - 1 ? 0 : 14,
                          marginBottom: index === currentReqs.length - 1 ? 0 : 14,
                          borderBottom: index === currentReqs.length - 1 ? undefined : '1px solid var(--border-subtle)',
                        }}
                      >
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                          <span className="cia-id">{req.requirement_id}</span>
                          <StateChip state={req.state} />
                        </div>
                        <p style={{
                          margin: 0,
                          fontSize: 14,
                          lineHeight: '21px',
                          color: req.state === 'confirmed' ? 'var(--ink)' :
                                 req.state === 'proposed' ? 'var(--ink-proposed)' :
                                 'var(--ink-historical)',
                          fontFamily: 'var(--font-sans)',
                        }}>
                          {req.text}
                        </p>
                        {req.note && (
                          <p style={{
                            margin: '6px 0 0',
                            fontSize: 12,
                            color: 'var(--ink-meta)',
                            fontStyle: 'italic'
                          }}>
                            {req.note}
                          </p>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Quick stats */}
              <div style={{
                marginTop: 12,
                padding: '12px 16px',
                background: 'var(--surface-sunken)',
                borderRadius: 'var(--radius-md)',
                display: 'flex',
                gap: 16,
                flexWrap: 'wrap'
              }}>
                {[
                  { label: 'Confirmed', count: currentReqs.filter(r => r.state === 'confirmed').length, color: 'var(--state-confirmed)' },
                  { label: 'Proposed', count: currentReqs.filter(r => r.state === 'proposed').length, color: 'var(--ink-proposed)' },
                  { label: 'Superseded', count: currentReqs.filter(r => r.state === 'superseded').length, color: 'var(--state-superseded)' },
                ].filter(s => s.count > 0).map(stat => (
                  <div key={stat.label} style={{ textAlign: 'center' }}>
                    <div style={{ fontSize: 18, fontWeight: 600, color: stat.color }}>{stat.count}</div>
                    <div style={{ fontSize: 11, color: 'var(--ink-meta)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>{stat.label}</div>
                  </div>
                ))}
              </div>
            </div>
          </aside>
        </div>
      </main>
    </AppShell>
  )
}

function getCurrentRequirements(rows: Schemas['RegisterRow'][]): Schemas['RegisterRow'][] {
  const best = new Map<string, Schemas['RegisterRow']>()
  for (const row of rows) {
    const existing = best.get(row.requirement_id)
    if (!existing || row.version > existing.version) {
      best.set(row.requirement_id, row)
    }
  }
  return [...best.values()].sort((a, b) => a.requirement_id.localeCompare(b.requirement_id))
}

function UpcomingRow({ meeting, projectId, last }: { meeting: Schemas['MeetingOut']; projectId: string; last: boolean }) {
  const live = meeting.status === 'live'
  const joining = meeting.capture_label === 'Bot will join'
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 16,
        padding: '14px 16px',
        borderBottom: last ? undefined : '1px solid var(--border-subtle)',
      }}
    >
      {live && <span className="cia-dot-live" />}
      <span className="cia-id" style={{ flex: '0 0 80px' }}>
        {meeting.when_label}
      </span>
      <span style={{ flex: '1 1 auto', minWidth: 0, fontSize: 14 }}>{meeting.title}</span>
      {meeting.capture_label && (
        <StatusTag tone={live ? 'live' : joining ? 'on' : 'off'}>
          {live ? `${meeting.turn_count} turns` : meeting.capture_label}
        </StatusTag>
      )}
      {live && (
        <Link to={`/projects/${projectId}/capture`} className="cia-btn" style={{ fontSize: 12, padding: '5px 12px' }}>
          Open
        </Link>
      )}
    </div>
  )
}

function PastCard({ meeting, projectId }: { meeting: Schemas['MeetingOut']; projectId: string }) {
  const openReview = (meeting.proposals ?? 0) > (meeting.confirmed ?? 0)
  return (
    <Link
      className="mcard"
      to={openReview ? `/projects/${projectId}/review` : `/projects/${projectId}/register`}
      style={{
        display: 'block',
        background: 'var(--surface-raised)',
        border: '1px solid var(--border-subtle)',
        borderRadius: 'var(--radius-md)',
        padding: '16px 18px',
        textDecoration: 'none',
        color: 'inherit',
        transition: 'border-color 0.15s ease, box-shadow 0.15s ease',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: 10 }}>
        <span className="cia-id">{meeting.id}</span>
        <span style={{ fontSize: 15, fontWeight: 500, color: 'var(--ink)' }}>{meeting.title}</span>
        <span style={{ marginLeft: 'auto', fontSize: 12, color: 'var(--ink-meta)' }}>
          {meeting.when_label}
        </span>
      </div>

      {/* Stats row */}
      <div style={{ display: 'flex', gap: 16, marginBottom: 10, flexWrap: 'wrap' }}>
        <Stat label="Turns" value={meeting.turn_count} />
        <Stat label="Candidates" value={meeting.candidates} />
        <Stat label="Proposals" value={meeting.proposals} />
        <Stat label="Confirmed" value={meeting.confirmed} highlight />
      </div>

      {/* Relation chips */}
      {(meeting.relation_counts ?? []).length > 0 && (
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          {(meeting.relation_counts ?? []).map((item) => {
            const tint =
              item.relation === 'contradiction'
                ? 'cia-relation--contradiction'
                : item.relation === 'supersession'
                  ? 'cia-relation--supersession'
                  : ''
            const [one, many] = PLURAL[item.relation]
            return (
              <span key={item.relation} className={tint ? `cia-relation ${tint}` : 'cia-relation'} style={{ fontSize: 11, padding: '1px 6px' }}>
                {item.count} {item.count === 1 ? one : many}
              </span>
            )
          })}
        </div>
      )}
    </Link>
  )
}

function Stat({ label, value, highlight }: { label: string; value?: number | null; highlight?: boolean }) {
  if (value == null) return null
  return (
    <div>
      <div style={{ fontSize: 11, color: 'var(--ink-meta)', marginBottom: 2 }}>{label}</div>
      <div style={{ fontSize: 14, fontWeight: highlight ? 600 : 400, color: highlight ? 'var(--state-confirmed)' : 'var(--ink)' }}>
        {value}
      </div>
    </div>
  )
}

const mainStyle = {
  flex: '999 1 560px',
  minWidth: 0,
  boxSizing: 'border-box' as const,
  padding: '32px 40px',
  display: 'flex',
  flexDirection: 'column' as const,
  gap: 20,
}

const titleStyle = {
  margin: 0,
  fontFamily: 'var(--font-display)',
  fontSize: 36,
  lineHeight: '42px',
  letterSpacing: '-0.01em',
}

const subtitleStyle = { margin: '4px 0 0', fontSize: 14, color: 'var(--ink-meta)' }

const sectionTitle = {
  margin: 0,
  fontSize: 11,
  fontWeight: 500,
  letterSpacing: '0.08em',
  textTransform: 'uppercase' as const,
  color: 'var(--ink-meta)',
}

const attentionDot = {
  width: 8,
  height: 8,
  borderRadius: '50%',
  background: 'var(--state-contradicted)',
  flexShrink: 0,
}
