import { Link, useParams } from 'react-router-dom'
import { useMeetings, useProject, useProposals, useSettings } from '../api/queries.ts'
import type { Schemas } from '../api/client.ts'
import { AppShell } from '../components/AppShell.tsx'
import type { RelationLabel } from '../components/RelationChip.tsx'
import { ScopeBar } from '../components/ScopeBar.tsx'
import { StatusTag } from '../components/StatusTag.tsx'

const PLURAL: Record<RelationLabel, [string, string]> = {
  new: ['new', 'new'],
  refinement: ['refinement', 'refinements'],
  contradiction: ['contradiction', 'contradictions'],
  supersession: ['supersession', 'supersessions'],
  restatement: ['restatement', 'restatements'],
  not_requirement: ['not a requirement', 'not requirements'],
}

const mainStyle = {
  flex: '999 1 560px',
  minWidth: 0,
  boxSizing: 'border-box' as const,
  padding: '40px 48px',
  display: 'flex',
  flexDirection: 'column' as const,
  gap: 28,
}

export function MeetingsRoute() {
  const { projectId = '' } = useParams()
  const project = useProject(projectId)
  const meetings = useMeetings(projectId)
  const proposals = useProposals(projectId)
  const settings = useSettings(projectId)
  const name = project.data?.name ?? projectId
  const reviewCount = proposals.data?.proposals.length
  const waiting = project.isPending || meetings.isPending || proposals.isPending || settings.isPending
  const problem = project.error ?? meetings.error ?? proposals.error ?? settings.error

  if (waiting) {
    return (
      <AppShell projectId={projectId} projectName={name} active="meetings" reviewCount={reviewCount}>
        <main style={mainStyle}>
          <p style={{ margin: 0, color: 'var(--ink-meta)' }}>Loading…</p>
        </main>
      </AppShell>
    )
  }
  if (problem || !project.data || !meetings.data || !settings.data) {
    return (
      <AppShell projectId={projectId} projectName={name} active="meetings" reviewCount={reviewCount}>
        <main style={mainStyle}>
          <p style={{ margin: 0 }}>{problem instanceof Error ? problem.message : 'Meetings could not be loaded.'}</p>
        </main>
      </AppShell>
    )
  }

  const named = meetings.data.filter((meeting) => meeting.ordinal != null)
  const past = meetings.data.filter((meeting) => meeting.status === 'past')
  const upcoming = meetings.data.filter((meeting) => meeting.status === 'live' || meeting.status === 'upcoming')
  const calendarOn = settings.data.connections.some((item) => item.status === 'connected')
  const recent = past[0]

  return (
    <AppShell projectId={projectId} projectName={project.data.name} active="meetings" reviewCount={reviewCount}>
      <main style={mainStyle}>
        <ScopeBar
          client={project.data.client}
          projectName={project.data.name}
          count={`${named.length} meetings · ${past.length} processed`}
        />
        <header style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 24, flexWrap: 'wrap' }}>
          <div>
            <h1 style={titleStyle}>Meetings</h1>
            <p style={subtitleStyle}>
              {project.data.name} · {past.length} meetings · {past.length} processing runs
            </p>
          </div>
          <Link to={`/projects/${projectId}/import`} style={{ textDecoration: 'none' }}>
            <span className="cia-btn" style={{ display: 'inline-block' }}>
              Import a transcript
            </span>
          </Link>
        </header>
        <section>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 14 }}>
            <h2 style={{ margin: 0, fontSize: 11, fontWeight: 500, letterSpacing: '0.08em', textTransform: 'uppercase', color: 'var(--ink-meta)' }}>
              Upcoming
            </h2>
            <span style={{ fontSize: 12, color: 'var(--ink-meta)' }}>From the connected calendar</span>
            {calendarOn ? (
              <span style={{ marginLeft: 'auto' }}>
                <StatusTag tone="on">Calendar connected</StatusTag>
              </span>
            ) : null}
          </div>
          <div style={{ background: 'var(--surface-raised)', border: '1px solid var(--border-subtle)', borderRadius: 10 }}>
            {upcoming.map((meeting, index) => (
              <UpcomingRow key={meeting.id} meeting={meeting} projectId={projectId} last={index === upcoming.length - 1} />
            ))}
          </div>
          <p style={{ margin: '12px 0 0', fontSize: 13, lineHeight: '21px', color: 'var(--ink-meta)' }}>
            Capture is opt-in per meeting. The bot appears in the participant list, so nobody is recorded without seeing
            that it is there.
          </p>
        </section>
        <h2 style={{ margin: '12px 0 -8px', fontSize: 11, fontWeight: 500, letterSpacing: '0.08em', textTransform: 'uppercase', color: 'var(--ink-meta)' }}>
          Past
        </h2>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {past.map((meeting) => (
            <PastCard key={meeting.id} meeting={meeting} projectId={projectId} />
          ))}
        </div>
        <section style={{ marginTop: 8 }}>
          <h2 style={{ margin: '0 0 12px', fontSize: 11, fontWeight: 500, letterSpacing: '0.08em', textTransform: 'uppercase', color: 'var(--ink-meta)' }}>
            Run log · most recent
          </h2>
          <p style={{ margin: 0, fontSize: 13, lineHeight: '20px', color: 'var(--ink-meta)' }}>
            Latency, token and cost figures from the exported screen are not returned by the fixture API, so they are
            not shown.
            {recent?.discarded != null ? ` ${recent.discarded} discarded ${recent.discarded === 1 ? 'candidate is' : 'candidates are'} recorded on ${recent.id}.` : ''}
          </p>
          <p style={{ margin: '12px 0 0', fontSize: 13, lineHeight: '20px', color: 'var(--ink-meta)' }}>
            The discarded candidate is visible here as a number, never as content. A candidate whose evidence does not
            resolve is an extraction error, and showing its text would put unsupported wording in front of a reviewer.
          </p>
        </section>
      </main>
    </AppShell>
  )
}

function UpcomingRow({ meeting, projectId, last }: { meeting: Schemas['MeetingOut']; projectId: string; last: boolean }) {
  const live = meeting.status === 'live'
  const joining = meeting.capture_label === 'Bot will join'
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 20,
        padding: '16px 24px',
        borderBottom: last ? undefined : '1px solid var(--border-subtle)',
      }}
    >
      {live ? <span className="cia-dot-live" /> : null}
      <span className="cia-id" style={{ flex: live ? '0 0 90px' : '0 0 120px' }}>
        {meeting.when_label}
      </span>
      <span style={{ flex: '999 1 auto', minWidth: 0, fontSize: 15 }}>{meeting.title}</span>
      {meeting.capture_label ? (
        <StatusTag tone={live ? 'live' : joining ? 'on' : 'off'}>
          {live ? `${meeting.capture_label} · ${meeting.turn_count} ${meeting.turn_count === 1 ? 'turn' : 'turns'}` : meeting.capture_label}
        </StatusTag>
      ) : null}
      {live ? (
        <Link to={`/projects/${projectId}/capture`} style={{ fontSize: 13 }}>
          Open
        </Link>
      ) : null}
      {!live && meeting.capture_label && !joining ? (
        <button type="button" className="cia-btn" style={{ fontSize: 13, padding: '6px 14px' }}>
          Capture this
        </button>
      ) : null}
    </div>
  )
}

function PastCard({ meeting, projectId }: { meeting: Schemas['MeetingOut']; projectId: string }) {
  const openReview = (meeting.proposals ?? 0) > (meeting.confirmed ?? 0)
  const stats = [
    ['Candidates', meeting.candidates],
    ['Discarded', meeting.discarded],
    ['Proposals', meeting.proposals],
    ['Confirmed', meeting.confirmed],
  ] as const
  return (
    <Link className="mcard" to={openReview ? `/projects/${projectId}/review` : `/projects/${projectId}/register`}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, flexWrap: 'wrap' }}>
        <span className="cia-id">{meeting.id}</span>
        <span style={{ fontSize: 17, fontWeight: 600 }}>{meeting.title}</span>
        <span style={{ marginLeft: 'auto', fontSize: 13, color: 'var(--ink-meta)' }}>
          {meeting.when_label} · {meeting.turn_count} {meeting.turn_count === 1 ? 'turn' : 'turns'}
        </span>
      </div>
      <div style={{ display: 'flex', gap: 20, marginTop: 14, flexWrap: 'wrap' }}>
        {stats.map(([label, value]) =>
          value == null ? null : (
            <div key={label}>
              <div style={{ fontSize: 12, color: 'var(--ink-meta)' }}>{label}</div>
              <div style={{ fontSize: 15, fontWeight: 500, color: label === 'Discarded' ? 'var(--ink)' : undefined }}>{value}</div>
            </div>
          ),
        )}
      </div>
      <div style={{ marginTop: 14, paddingTop: 12, borderTop: '1px solid var(--border-subtle)', display: 'flex', gap: 6, flexWrap: 'wrap' }}>
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
        {meeting.not_requirement_count ? (
          <span style={{ fontSize: 12, color: 'var(--ink-meta)', alignSelf: 'center', marginLeft: 4 }}>
            {meeting.not_requirement_count === 1
              ? '1 utterance classified as not a requirement'
              : `${meeting.not_requirement_count} utterances classified as not a requirement`}
          </span>
        ) : null}
        {meeting.footer ? (
          <span style={{ fontSize: 12, color: 'var(--ink-meta)', alignSelf: 'center', marginLeft: 4 }}>{meeting.footer}</span>
        ) : null}
      </div>
    </Link>
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
