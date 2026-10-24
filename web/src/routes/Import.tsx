import { Link, useParams } from 'react-router-dom'
import { useMeetings, useProject, useProjects, useProposals, useSettings } from '../api/queries.ts'
import { AppShell } from '../components/AppShell.tsx'
import { AuthorityBadge } from '../components/AuthorityBadge.tsx'

const mainStyle = {
  flex: '999 1 560px',
  minWidth: 0,
  boxSizing: 'border-box' as const,
  padding: '40px 48px',
}

export function ImportRoute() {
  const { projectId = '' } = useParams()
  const project = useProject(projectId)
  const projects = useProjects()
  const settings = useSettings(projectId)
  const meetings = useMeetings(projectId)
  const proposals = useProposals(projectId)
  const name = project.data?.name ?? projectId
  const reviewCount = proposals.data?.proposals.length
  const waiting = project.isPending || projects.isPending || settings.isPending || meetings.isPending || proposals.isPending
  const problem = project.error ?? projects.error ?? settings.error ?? meetings.error ?? proposals.error

  if (waiting) {
    return (
      <AppShell projectId={projectId} projectName={name} active="meetings" reviewCount={reviewCount}>
        <main style={mainStyle}>
          <p style={{ margin: 0, color: 'var(--ink-meta)' }}>Loading…</p>
        </main>
      </AppShell>
    )
  }
  if (problem || !project.data || !projects.data || !settings.data || !meetings.data) {
    return (
      <AppShell projectId={projectId} projectName={name} active="meetings" reviewCount={reviewCount}>
        <main style={mainStyle}>
          <p style={{ margin: 0 }}>{problem instanceof Error ? problem.message : 'Import could not be loaded.'}</p>
        </main>
      </AppShell>
    )
  }

  const past = meetings.data.filter((meeting) => meeting.status === 'past')
  const recentPast = past[0]
  const maxOrdinal = meetings.data.reduce((max, meeting) => Math.max(max, meeting.ordinal ?? 0), 0)
  const orderValue = recentPast ? `${maxOrdinal} — after ${recentPast.when_label}` : String(maxOrdinal || '')

  return (
    <AppShell projectId={projectId} projectName={project.data.name} active="meetings" reviewCount={reviewCount}>
      <main style={mainStyle}>
        <div style={{ maxWidth: 680, display: 'flex', flexDirection: 'column', gap: 28 }}>
          <div>
            <h1 style={titleStyle}>Import a transcript</h1>
            <p style={{ margin: '10px 0 0', fontSize: 14, lineHeight: '22px', color: 'var(--ink-meta)' }}>
              For past meetings, calls captured elsewhere, or anything the bot did not join. Live capture is the normal
              path — <Link to={`/projects/${projectId}/capture`}>connect a calendar</Link> and the transcript arrives on
              its own.
            </p>
          </div>
          <div
            style={{
              background: 'var(--surface-sunken)',
              border: '1px solid var(--border-subtle)',
              borderRadius: 10,
              padding: '16px 20px',
              fontSize: 13,
              lineHeight: '21px',
              color: 'var(--ink-meta)',
            }}
          >
            Turn order is load-bearing. Once imported, a meeting’s turns are never renumbered, because every piece of
            evidence points at one by position.
          </div>
          <div
            style={{
              border: '1px dashed var(--border-strong)',
              borderRadius: 10,
              background: 'var(--surface-raised)',
              padding: '40px 24px',
              textAlign: 'center',
            }}
          >
            <div style={{ fontFamily: 'var(--font-display)', fontSize: 21 }}>Drop a transcript file</div>
            <p style={{ margin: '6px 0 16px', fontSize: 13, color: 'var(--ink-meta)' }}>
              Plain text with speaker labels, or an export from a meeting tool
            </p>
            <button type="button" className="cia-btn">
              Choose file
            </button>
          </div>
          <div
            style={{
              background: 'var(--surface-raised)',
              border: '1px solid var(--border-subtle)',
              borderRadius: 10,
              padding: 20,
              display: 'flex',
              flexDirection: 'column',
              gap: 18,
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <span className="cia-id">D1-M03.txt</span>
              <span style={{ fontSize: 13, color: 'var(--ink-meta)' }}>62 turns parsed · 4 speakers found</span>
              <span style={{ marginLeft: 'auto', fontSize: 13, color: 'var(--ink)', fontWeight: 600 }}>Ready</span>
            </div>
            <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
              <div style={{ flex: '1 1 220px', minWidth: 0 }}>
                <label htmlFor="proj" style={fieldLabel}>
                  Project
                </label>
                <select className="fld" id="proj" defaultValue={project.data.id}>
                  {projects.data.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.name}
                    </option>
                  ))}
                </select>
              </div>
              <div style={{ flex: '1 1 160px', minWidth: 0 }}>
                <label htmlFor="ord" style={fieldLabel}>
                  Meeting order
                </label>
                <input className="fld" id="ord" type="text" defaultValue={orderValue} />
              </div>
            </div>
            <div>
              <div style={{ fontSize: 11, fontWeight: 500, letterSpacing: '0.08em', textTransform: 'uppercase', color: 'var(--ink-meta)', marginBottom: 10 }}>
                Speakers and scope authority
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                {settings.data.speakers.map((speaker) => (
                  <div
                    key={speaker.speaker_label}
                    style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '8px 0', borderBottom: '1px solid var(--border-subtle)' }}
                  >
                    <span className="cia-id" style={{ flex: '0 0 130px' }}>
                      {speaker.speaker_label}
                    </span>
                    <span style={{ flex: '999 1 auto', minWidth: 0, fontSize: 14 }}>
                      {speaker.name} · {speaker.role}
                    </span>
                    <AuthorityBadge can={speaker.can_confirm_scope}>
                      {speaker.can_confirm_scope ? 'Can confirm scope' : 'Cannot confirm scope'}
                    </AuthorityBadge>
                  </div>
                ))}
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 12,
                    padding: '8px 12px 8px 12px',
                    background: 'var(--surface-sunken)',
                    borderLeft: '2px solid var(--ink)',
                    borderRadius: '0 6px 6px 0',
                  }}
                >
                  <span className="cia-id" style={{ flex: '0 0 130px' }}>
                    CLIENT_CFO
                  </span>
                  <span style={{ flex: '999 1 auto', minWidth: 0, fontSize: 14, color: 'var(--ink)' }}>
                    New speaker — assign a role before importing
                  </span>
                  <button type="button" className="cia-btn" style={{ fontSize: 13, padding: '5px 12px' }}>
                    Assign
                  </button>
                </div>
              </div>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, paddingTop: 4 }}>
              <button type="button" className="cia-btn cia-btn--primary" disabled>
                Import and process
              </button>
              <span style={{ fontSize: 13, color: 'var(--ink-meta)' }}>Blocked: one speaker has no role</span>
            </div>
          </div>
          <p style={{ margin: 0, fontSize: 13, lineHeight: '20px', color: 'var(--ink-meta)' }}>
            Authority is configuration, not something the agent reads out of the conversation. A speaker&apos;s name or
            tone never establishes who can change agreed scope, so an unmapped speaker blocks the import rather than
            defaulting to anything.
          </p>
        </div>
      </main>
    </AppShell>
  )
}

const titleStyle = {
  margin: 0,
  fontFamily: 'var(--font-display)',
  fontSize: 38,
  lineHeight: '44px',
  letterSpacing: '-0.01em',
}

const fieldLabel = { display: 'block', fontSize: 12, color: 'var(--ink-meta)', marginBottom: 6 }
