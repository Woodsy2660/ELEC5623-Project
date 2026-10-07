import { Link, useParams } from 'react-router-dom'
import { useLiveTranscript, useMeetings, useProject, useRequirements, useSettings } from '../api/queries.ts'
import type { Schemas } from '../api/client.ts'
import { AppShell } from '../components/AppShell.tsx'
import { AuthorityBadge } from '../components/AuthorityBadge.tsx'
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

export function CaptureRoute() {
  const { projectId = '' } = useParams()
  const project = useProject(projectId)
  const meetings = useMeetings(projectId)
  const requirements = useRequirements(projectId)
  const settings = useSettings(projectId)
  const live = meetings.data?.find((meeting) => meeting.status === 'live') ?? null
  const transcript = useLiveTranscript(live?.id ?? null)
  const name = project.data?.name ?? projectId
  const waiting = project.isPending || meetings.isPending || requirements.isPending || settings.isPending
  const problem = project.error ?? meetings.error ?? requirements.error ?? settings.error

  if (waiting) {
    return (
      <AppShell projectId={projectId} projectName={name} active="capture" showReviewCount={false}>
        <main style={mainStyle}>
          <p style={{ margin: 0, color: 'var(--ink-meta)' }}>Loading…</p>
        </main>
      </AppShell>
    )
  }
  if (problem || !project.data || !meetings.data || !requirements.data || !settings.data) {
    return (
      <AppShell projectId={projectId} projectName={name} active="capture" showReviewCount={false}>
        <main style={mainStyle}>
          <p style={{ margin: 0 }}>{problem instanceof Error ? problem.message : 'Capture could not be loaded.'}</p>
        </main>
      </AppShell>
    )
  }

  const scope = currentFamilies(requirements.data)

  return (
    <AppShell projectId={projectId} projectName={project.data.name} active="capture" showReviewCount={false}>
      <main style={mainStyle}>
        <ScopeBar
          client={project.data.client}
          projectName={project.data.name}
          count={`${project.data.requirement_count} requirement families`}
        />
        <header style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 24, flexWrap: 'wrap' }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
              <span className="cia-dot-live" />
              <span style={{ fontSize: 11, fontWeight: 500, letterSpacing: '0.08em', textTransform: 'uppercase', color: 'var(--state-live)' }}>
                Replay of a stored transcript
              </span>
            </div>
            <h1 style={titleStyle}>{live?.title ?? 'Live capture'}</h1>
            <p style={{ margin: '8px 0 0', fontSize: 14, color: 'var(--ink-meta)' }}>
              {project.data.name}
              {live?.ordinal != null ? ` · meeting ${live.ordinal}` : ''} · replay, not a live meeting capture
            </p>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button type="button" className="cia-btn">
              Pause capture
            </button>
            <Link to={`/projects/${projectId}/meetings`} style={{ textDecoration: 'none' }}>
              <span className="cia-btn cia-btn--primary" style={{ display: 'inline-block' }}>
                End and process
              </span>
            </Link>
          </div>
        </header>
        {!live ? <p style={{ margin: 0, color: 'var(--ink-meta)' }}>No stored meeting is marked live for this project.</p> : null}
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 32 }}>
          <section style={{ flex: '999 1 420px', minWidth: 0 }}>
            <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 14 }}>
              <h2 style={kicker}>Live transcript</h2>
              <span className="cia-id">
                {transcript.turns.length} {transcript.turns.length === 1 ? 'turn' : 'turns'}
              </span>
            </div>
            <div style={{ background: 'var(--surface-raised)', border: '1px solid var(--border-subtle)', borderRadius: 10, padding: '8px 24px 24px' }}>
              {transcript.turns.map((turn, index) => (
                <div
                  key={turn.turn_id}
                  className={turn.partial ? 'cia-turn cia-turn--partial' : 'cia-turn'}
                  style={turn.partial && index === transcript.turns.length - 1 ? { borderBottom: 'none' } : undefined}
                >
                  <span className="cia-turn__speaker">{turn.speaker}</span>
                  <p className="cia-turn__text">
                    {turn.before}
                    {turn.span}
                    {turn.after}
                    {turn.partial ? <span style={{ opacity: 0.45 }}>…</span> : null}
                  </p>
                </div>
              ))}
            </div>
            {transcript.error ? <p style={{ margin: '14px 0 0', fontSize: 13, color: 'var(--ink)' }}>{transcript.error}</p> : null}
            <p style={{ margin: '14px 0 0', fontSize: 13, lineHeight: '21px', color: 'var(--ink-meta)' }}>
              Turns arrive as the capture bot transcribes them. The last turn is still forming, so it sits in receded
              ink until it settles.
            </p>
          </section>
          <aside style={{ flex: '1 1 300px', minWidth: 0, display: 'flex', flexDirection: 'column', gap: 20 }}>
            <div style={{ background: 'var(--surface-sunken)', border: '1px solid var(--border-subtle)', borderRadius: 10, padding: 20 }}>
              <div style={kickerBlock}>Proposals</div>
              <p style={{ margin: 0, fontSize: 14, lineHeight: '22px', color: 'var(--ink-proposed)' }}>None yet, by design.</p>
              <p style={{ margin: '10px 0 0', fontSize: 13, lineHeight: '21px', color: 'var(--ink-meta)' }}>
                Matching runs against the register once the meeting ends. A decision made late can reverse one made
                early, so nothing is proposed from a partial transcript.
              </p>
            </div>
            <div>
              <div style={{ ...kickerBlock, marginBottom: 12 }}>Current scope · {scope.length} requirements</div>
              <div className="cia-alts">
                {scope.map((row) => (
                  <div key={row.requirement_id} className="cia-alt">
                    <span className="cia-alt__rank">{row.requirement_id}</span>
                    <span className="cia-alt__text">{row.text}</span>
                    <StateChip state={row.state} />
                  </div>
                ))}
              </div>
            </div>
            <div style={{ borderTop: '1px solid var(--border-subtle)', paddingTop: 16 }}>
              <div style={kickerBlock}>In the call</div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {settings.data.speakers.map((speaker) => (
                  <div key={speaker.speaker_label} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <span style={{ fontSize: 14, flex: 1 }}>{speaker.name}</span>
                    <AuthorityBadge can={speaker.can_confirm_scope}>
                      {speaker.can_confirm_scope ? 'Can confirm' : 'Cannot confirm'}
                    </AuthorityBadge>
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

function currentFamilies(rows: Schemas['RegisterRow'][]): Schemas['RegisterRow'][] {
  const best = new Map<string, Schemas['RegisterRow']>()
  for (const row of rows) {
    const existing = best.get(row.requirement_id)
    if (!existing || row.version > existing.version) best.set(row.requirement_id, row)
  }
  return [...best.values()].sort((a, b) => a.requirement_id.localeCompare(b.requirement_id))
}

const titleStyle = {
  margin: 0,
  fontFamily: 'var(--font-display)',
  fontSize: 38,
  lineHeight: '44px',
  letterSpacing: '-0.01em',
}

const kicker = {
  margin: 0,
  fontSize: 11,
  fontWeight: 500,
  letterSpacing: '0.08em',
  textTransform: 'uppercase' as const,
  color: 'var(--ink-meta)',
}

const kickerBlock = {
  fontSize: 11,
  fontWeight: 500,
  letterSpacing: '0.08em',
  textTransform: 'uppercase' as const,
  color: 'var(--ink-meta)',
  marginBottom: 10,
}
