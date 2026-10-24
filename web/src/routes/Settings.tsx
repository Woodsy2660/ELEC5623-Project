import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useProject, useProposals, useSettings, useUpdateSettings } from '../api/queries.ts'
import type { Schemas } from '../api/client.ts'
import { AppShell } from '../components/AppShell.tsx'
import { AuthorityBadge } from '../components/AuthorityBadge.tsx'
import { StatusTag } from '../components/StatusTag.tsx'

const ROLES = ['Product owner', 'Engineer', 'Observer', 'Lead consultant', 'Business analyst']

const mainStyle = {
  flex: '999 1 560px',
  minWidth: 0,
  boxSizing: 'border-box' as const,
  padding: '40px 48px',
}

export function SettingsRoute() {
  const { projectId = '' } = useParams()
  const project = useProject(projectId)
  const settings = useSettings(projectId)
  const proposals = useProposals(projectId)
  const save = useUpdateSettings(projectId)
  const [draft, setDraft] = useState<Schemas['ProjectSettings'] | null>(null)
  const [synced, setSynced] = useState<Schemas['ProjectSettings'] | null>(null)
  const name = project.data?.name ?? projectId
  const reviewCount = proposals.data?.proposals.length

  if (settings.data && settings.data !== synced) {
    setSynced(settings.data)
    setDraft(settings.data)
  }

  const waiting = project.isPending || settings.isPending || proposals.isPending
  const problem = project.error ?? settings.error ?? proposals.error
  if (waiting || !draft) {
    return (
      <AppShell projectId={projectId} projectName={name} active="settings" reviewCount={reviewCount}>
        <main style={mainStyle}>
          <p style={{ margin: 0, color: 'var(--ink-meta)' }}>
            {problem instanceof Error ? problem.message : 'Loading…'}
          </p>
        </main>
      </AppShell>
    )
  }
  if (problem || !project.data) {
    return (
      <AppShell projectId={projectId} projectName={name} active="settings" reviewCount={reviewCount}>
        <main style={mainStyle}>
          <p style={{ margin: 0 }}>{problem instanceof Error ? problem.message : 'Settings could not be loaded.'}</p>
        </main>
      </AppShell>
    )
  }

  function commit(next: Schemas['ProjectSettings']) {
    setDraft(next)
    save.mutate(next)
  }

  return (
    <AppShell projectId={projectId} projectName={project.data.name} active="settings" reviewCount={reviewCount}>
      <main style={mainStyle}>
        <div style={{ maxWidth: 760, display: 'flex', flexDirection: 'column', gap: 24 }}>
          <div>
            <h1 style={titleStyle}>Settings</h1>
            <p style={{ margin: '6px 0 0', fontSize: 14, color: 'var(--ink-meta)' }}>{project.data.name}</p>
          </div>
          <section className="sec">
            <h2 style={heading}>Connections</h2>
            <p style={lede}>How meetings reach the register.</p>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              {draft.connections.map((connection) => (
                <div
                  key={connection.id}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 16,
                    padding: '14px 0',
                    borderBottom: '1px solid var(--border-subtle)',
                  }}
                >
                  <span style={{ flex: '0 0 150px', fontSize: 14 }}>{connection.label}</span>
                  <span style={{ flex: '999 1 auto', minWidth: 0, fontSize: 13, color: 'var(--ink-meta)' }}>
                    {connection.description}
                  </span>
                  {connection.status === 'connected' ? (
                    <StatusTag tone="on">Connected</StatusTag>
                  ) : (
                    <button type="button" className="cia-btn" style={{ fontSize: 13, padding: '6px 14px' }}>
                      Connect
                    </button>
                  )}
                </div>
              ))}
              <div style={{ display: 'flex', alignItems: 'center', gap: 16, padding: '14px 0' }}>
                <span style={{ flex: '0 0 150px', fontSize: 14 }}>Capture default</span>
                <span style={{ flex: '999 1 auto', minWidth: 0, fontSize: 13, color: 'var(--ink-meta)' }}>
                  Whether the bot joins new meetings without being asked
                </span>
                <StatusTag tone="off">{draft.capture_default === 'ask' ? 'Ask each time' : 'Always'}</StatusTag>
              </div>
            </div>
            <p style={{ margin: '16px 0 0', fontSize: 13, lineHeight: '21px', color: 'var(--ink-meta)' }}>
              The default is to ask. A bot that joins silently records people who never agreed to it, and consent is not
              something this product should assume.
            </p>
          </section>
          <section className="sec">
            <h2 style={heading}>Scope authority</h2>
            <p style={{ ...lede, lineHeight: '20px' }}>
              Who can confirm a change to agreed scope. The agent never infers this from a transcript.
            </p>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              {draft.speakers.map((speaker, index) => (
                <div
                  key={speaker.speaker_label}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 12,
                    padding: '10px 0',
                    borderBottom: index === draft.speakers.length - 1 ? undefined : '1px solid var(--border-subtle)',
                  }}
                >
                  <span className="cia-id" style={{ flex: '0 0 130px' }}>
                    {speaker.speaker_label}
                  </span>
                  <span style={{ flex: '999 1 auto', minWidth: 0, fontSize: 14 }}>{speaker.name}</span>
                  <select
                    className="fld"
                    style={{ fontSize: 13 }}
                    value={speaker.role}
                    aria-label={`${speaker.name} role`}
                    onChange={(event) => {
                      const speakers = draft.speakers.map((item, itemIndex) =>
                        itemIndex === index ? { ...item, role: event.target.value } : item,
                      )
                      commit({ ...draft, speakers })
                    }}
                  >
                    {roleOptions(speaker.role).map((role) => (
                      <option key={role}>{role}</option>
                    ))}
                  </select>
                  <AuthorityBadge can={speaker.can_confirm_scope} style={{ flex: '0 0 150px' }}>
                    {speaker.can_confirm_scope ? 'Can confirm scope' : 'Cannot confirm'}
                  </AuthorityBadge>
                </div>
              ))}
            </div>
          </section>
          <section className="sec">
            <h2 style={heading}>Model</h2>
            <p style={{ ...lede, lineHeight: '20px' }}>
              Pinned for reproducibility. Changing any of these starts a new run series; earlier results are not
              comparable.
            </p>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 16 }}>
              <div style={{ flex: '1 1 240px', minWidth: 0 }}>
                <label htmlFor="dep" style={fieldLabel}>
                  Deployment
                </label>
                <input
                  className="fld"
                  id="dep"
                  style={{ width: '100%' }}
                  type="text"
                  value={draft.deployment}
                  onChange={(event) => setDraft({ ...draft, deployment: event.target.value })}
                  onBlur={() => save.mutate(draft)}
                />
              </div>
              <div style={{ flex: '0 1 120px', minWidth: 0 }}>
                <label htmlFor="tmp" style={fieldLabel}>
                  Temperature
                </label>
                <input
                  className="fld"
                  id="tmp"
                  style={{ width: '100%' }}
                  type="text"
                  value={String(draft.temperature)}
                  onChange={(event) => setDraft({ ...draft, temperature: Number(event.target.value) })}
                  onBlur={() => {
                    if (Number.isFinite(draft.temperature)) save.mutate(draft)
                  }}
                />
              </div>
              <div style={{ flex: '0 1 120px', minWidth: 0 }}>
                <label htmlFor="kk" style={fieldLabel}>
                  Retrieval k
                </label>
                <input
                  className="fld"
                  id="kk"
                  style={{ width: '100%' }}
                  type="text"
                  value={String(draft.retrieval_k)}
                  onChange={(event) => setDraft({ ...draft, retrieval_k: Number(event.target.value) })}
                  onBlur={() => {
                    if (Number.isFinite(draft.retrieval_k)) save.mutate(draft)
                  }}
                />
              </div>
            </div>
            <div style={{ marginTop: 16, paddingTop: 14, borderTop: '1px solid var(--border-subtle)', display: 'flex', gap: 24, flexWrap: 'wrap' }}>
              <div>
                <div style={{ fontSize: 12, color: 'var(--ink-meta)' }}>Extract prompt</div>
                <div className="cia-id">{draft.extract_prompt}</div>
              </div>
              <div>
                <div style={{ fontSize: 12, color: 'var(--ink-meta)' }}>Classify prompt</div>
                <div className="cia-id">{draft.classify_prompt}</div>
              </div>
              <div>
                <div style={{ fontSize: 12, color: 'var(--ink-meta)' }}>Status</div>
                <div style={{ fontSize: 13, fontWeight: 600 }}>{draft.prompt_status}</div>
              </div>
            </div>
          </section>
          <section className="sec" id="provider-retention">
            <h2 style={heading}>Data and retention</h2>
            <p style={{ ...lede, lineHeight: '20px' }}>
              Transcripts are sent to the model provider for processing. Deleting a project here removes its
              transcripts, register and embeddings from this application — it does not remove anything already held by
              the provider.
            </p>
            <div style={retentionRow}>
              <span style={{ flex: '999 1 auto', minWidth: 0, fontSize: 14 }}>Project isolation</span>
              <span style={{ fontSize: 13, color: 'var(--ink-meta)' }}>Retrieval never crosses projects</span>
              <StatusTag tone={draft.project_isolation ? 'on' : 'off'}>{draft.project_isolation ? 'On' : 'Off'}</StatusTag>
            </div>
            <div style={retentionRow}>
              <span style={{ flex: '999 1 auto', minWidth: 0, fontSize: 14 }}>Provider retention</span>
              <span style={{ fontSize: 13, color: 'var(--ink-meta)' }}>{draft.provider_retention_note}</span>
              <Link to={`/projects/${projectId}/settings`} style={{ fontSize: 13 }}>
                Review
              </Link>
            </div>
            <div style={retentionRow}>
              <span style={{ flex: '999 1 auto', minWidth: 0, fontSize: 14 }}>Delete project and all data</span>
              <button type="button" className="cia-btn cia-btn--danger" style={{ fontSize: 13, padding: '6px 12px' }}>
                Delete
              </button>
            </div>
          </section>
          {save.error ? (
            <p style={{ margin: 0, fontSize: 13, color: 'var(--ink)' }}>
              {save.error instanceof Error ? save.error.message : 'Settings were not saved.'}
            </p>
          ) : null}
        </div>
      </main>
    </AppShell>
  )
}

function roleOptions(current: string): string[] {
  return ROLES.includes(current) ? ROLES : [current, ...ROLES]
}

const titleStyle = {
  margin: 0,
  fontFamily: 'var(--font-display)',
  fontSize: 38,
  lineHeight: '44px',
  letterSpacing: '-0.01em',
}

const heading = { margin: '0 0 4px', fontSize: 15, fontWeight: 500 }
const lede = { margin: '0 0 18px', fontSize: 13, lineHeight: '21px', color: 'var(--ink-meta)' }
const fieldLabel = { display: 'block', fontSize: 12, color: 'var(--ink-meta)', marginBottom: 6 }
const retentionRow = {
  display: 'flex',
  alignItems: 'center',
  gap: 12,
  padding: '12px 0',
  borderTop: '1px solid var(--border-subtle)',
}
