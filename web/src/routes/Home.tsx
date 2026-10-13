import { Link } from 'react-router-dom'
import { useMeetings, useProjects, useProposals } from '../api/queries.ts'
import type { Schemas } from '../api/client.ts'
import { AppShell } from '../components/AppShell.tsx'
import { StatusTag } from '../components/StatusTag.tsx'

const WORDS = ['No', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine', 'Ten']

export function HomeRoute() {
  const projects = useProjects()
  if (projects.isPending) {
    return (
      <AppShell projectId="" projectName="" active="home">
        <main style={mainStyle}>
          <p style={{ margin: 0, color: 'var(--ink-meta)' }}>Loading…</p>
        </main>
      </AppShell>
    )
  }
  if (projects.error || !projects.data) {
    return (
      <AppShell projectId="" projectName="" active="home">
        <main style={mainStyle}>
          <p style={{ margin: 0 }}>{projects.error instanceof Error ? projects.error.message : 'Projects could not be loaded.'}</p>
        </main>
      </AppShell>
    )
  }
  const portal = projects.data.find((project) => project.live_title) ?? projects.data[0]
  if (!portal) {
    return (
      <AppShell projectId="" projectName="" active="home">
        <main style={mainStyle}>
          <p style={{ margin: 0 }}>No projects.</p>
        </main>
      </AppShell>
    )
  }
  return <HomeBody projects={projects.data} portal={portal} />
}

function HomeBody({ projects, portal }: { projects: Schemas['ProjectOut'][]; portal: Schemas['ProjectOut'] }) {
  const proposals = useProposals(portal.id)
  const meetings = useMeetings(portal.id)
  const live = projects.filter((project) => project.live_title)
  const waiting = projects.reduce((sum, project) => sum + project.proposal_count, 0)
  const upcoming = (meetings.data ?? []).filter((meeting) => meeting.status === 'upcoming')

  return (
    <AppShell projectId={portal.id} projectName={portal.name} active="home" reviewCount={proposals.data?.proposals.length}>
      <main style={mainStyle}>
        <header>
          <h1 style={{ margin: 0, fontFamily: 'var(--font-display)', fontSize: 44, lineHeight: '50px', letterSpacing: '-0.01em' }}>
            Good afternoon, Ben
          </h1>
          <p style={{ margin: '10px 0 0', fontSize: 15, color: 'var(--ink-meta)' }}>
            {counted(live.length, 'call', 'calls')} in progress. {counted(waiting, 'proposal', 'proposals')} waiting on a
            decision.
          </p>
        </header>
        {live.map((project) => (
          <section
            key={project.id}
            style={{
              background: 'var(--ink)',
              color: 'var(--surface-page)',
              borderRadius: 16,
              padding: '28px 32px',
              display: 'flex',
              alignItems: 'center',
              gap: 28,
              flexWrap: 'wrap',
            }}
          >
            <div style={{ flex: '999 1 320px', minWidth: 0 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
                <span className="cia-dot-live" />
                <span style={{ fontSize: 11, fontWeight: 500, letterSpacing: '0.08em', textTransform: 'uppercase', opacity: 0.85 }}>
                  Recording now
                </span>
              </div>
              <div style={{ fontFamily: 'var(--font-display)', fontSize: 27, lineHeight: '34px' }}>{project.live_title}</div>
              {project.live_detail ? <div style={{ marginTop: 8, fontSize: 14, opacity: 0.75 }}>{project.live_detail}</div> : null}
            </div>
            <Link to={`/projects/${project.id}/capture`} style={{ textDecoration: 'none' }}>
              <span className="cia-btn" style={{ display: 'inline-block', background: 'var(--surface-page)', borderColor: 'var(--surface-page)' }}>
                Open capture
              </span>
            </Link>
          </section>
        ))}
        <section>
          <h2 style={kicker}>Next up</h2>
          <div style={{ background: 'var(--surface-raised)', border: '1px solid var(--border-subtle)', borderRadius: 10 }}>
            {upcoming.length === 0 ? (
              <div style={{ padding: '16px 24px', fontSize: 14, color: 'var(--ink-meta)' }}>Nothing scheduled.</div>
            ) : (
              upcoming.map((meeting, index) => (
                <div
                  key={meeting.id}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 20,
                    padding: '16px 24px',
                    borderBottom: index === upcoming.length - 1 ? undefined : '1px solid var(--border-subtle)',
                  }}
                >
                  <span className="cia-id" style={{ flex: '0 0 110px' }}>
                    {meeting.when_label}
                  </span>
                  <span style={{ flex: '999 1 auto', minWidth: 0, fontSize: 15 }}>{meeting.home_title ?? meeting.title}</span>
                  {meeting.capture_label ? (
                    <StatusTag tone={meeting.capture_label === 'Bot will join' ? 'on' : 'off'}>{meeting.capture_label}</StatusTag>
                  ) : null}
                </div>
              ))
            )}
          </div>
        </section>
        <section>
          <h2 style={kicker}>Projects</h2>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 16 }}>
            {projects.map((project) => (
              <ProjectCard key={project.id} project={project} />
            ))}
          </div>
        </section>
      </main>
    </AppShell>
  )
}

function ProjectCard({ project }: { project: Schemas['ProjectOut'] }) {
  const meetings = project.meeting_count === 0 ? 'no meetings yet' : `${project.meeting_count} meeting${project.meeting_count === 1 ? '' : 's'}`
  const importPhrase = 'import a transcript'
  const splitAt = project.review_note.indexOf(importPhrase)
  const body = (
    <>
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 12 }}>
        <span style={{ fontFamily: 'var(--font-display)', fontSize: 21 }}>{project.name}</span>
        <span className="cia-id">{project.requirement_count} reqs</span>
      </div>
      <p style={{ margin: '10px 0 18px', fontSize: 13, lineHeight: '20px', color: 'var(--ink-meta)' }}>
        {project.client} · {meetings}
      </p>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        {project.empty ? (
          <span className="cia-chip cia-chip--empty">Empty</span>
        ) : (
          project.state_counts.map((item) => (
            <span key={item.state} className={`cia-chip cia-chip--${item.state}`}>
              {item.count} {item.state}
            </span>
          ))
        )}
      </div>
    </>
  )
  const footerStyle = {
    marginTop: 18,
    paddingTop: 14,
    borderTop: '1px solid var(--border-subtle)',
    fontSize: 13,
    color: project.proposal_count > 0 ? 'var(--ink)' : 'var(--ink-meta)',
  }
  if (splitAt >= 0) {
    return (
      <div className="card">
        <Link to={`/projects/${project.id}/register`} style={{ textDecoration: 'none', color: 'inherit' }}>
          {body}
        </Link>
        <div style={footerStyle}>
          {project.review_note.slice(0, splitAt)}
          <Link to={`/projects/${project.id}/import`}>{importPhrase}</Link>
          {project.review_note.slice(splitAt + importPhrase.length)}
        </div>
      </div>
    )
  }
  return (
    <Link className="card" to={`/projects/${project.id}/register`}>
      {body}
      <div style={footerStyle}>{project.review_note}</div>
    </Link>
  )
}

function counted(count: number, singular: string, plural: string): string {
  const head = WORDS[count] ?? String(count)
  return `${head} ${count === 1 ? singular : plural}`
}

const mainStyle = {
  flex: '999 1 560px',
  minWidth: 0,
  boxSizing: 'border-box' as const,
  padding: '40px 48px',
  display: 'flex',
  flexDirection: 'column' as const,
  gap: 36,
}

const kicker = {
  margin: '0 0 16px',
  fontSize: 11,
  fontWeight: 500,
  letterSpacing: '0.08em',
  textTransform: 'uppercase' as const,
  color: 'var(--ink-meta)',
}
