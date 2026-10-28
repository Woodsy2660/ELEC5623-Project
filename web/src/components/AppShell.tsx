import { useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { CountBadge } from './CountBadge.tsx'
import { setReviewerToken } from '../api/client.ts'

export type NavKey = 'home' | 'meetings' | 'register' | 'review' | 'capture' | 'settings'

export function AppShell({
  projectId,
  projectName,
  active,
  reviewCount,
  showReviewCount = true,
  children,
}: {
  projectId: string
  projectName: string
  active: NavKey
  reviewCount?: number
  showReviewCount?: boolean
  children: ReactNode
}) {
  const base = `/projects/${projectId}`
  return (
    <div
      style={{
        minHeight: 900,
        background: 'var(--surface-page)',
        fontFamily: 'var(--font-sans)',
        color: 'var(--ink)',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      <header
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'flex-start',
          padding: '18px 30px',
          borderBottom: '1px solid var(--border-subtle)',
        }}
      >
        <img src="/assets/consultsi.png" alt="Consult SI" style={{ height: 19, width: 'auto', display: 'block' }} />
      </header>
      <div style={{ display: 'flex', flexWrap: 'wrap', flex: '1 1 auto' }}>
        <nav
          style={{
            flex: '0 0 248px',
            boxSizing: 'border-box',
            padding: '24px 16px',
            borderRight: '1px solid var(--border-subtle)',
            display: 'flex',
            flexDirection: 'column',
            gap: 24,
          }}
        >
          <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            <NavLink to="/" current={active === 'home'}>
              Home
            </NavLink>
            <NavLink to={`${base}/meetings`} current={active === 'meetings'}>
              Meetings
            </NavLink>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            <div
              style={{
                padding: '0 14px 8px',
                fontSize: 11,
                fontWeight: 500,
                letterSpacing: '0.08em',
                textTransform: 'uppercase',
                color: 'var(--ink-meta)',
              }}
            >
              {projectName}
            </div>
            <NavLink to={`${base}/register`} current={active === 'register'}>
              Register
            </NavLink>
            <NavLink to={`${base}/review`} current={active === 'review'}>
              Review queue
              {showReviewCount && reviewCount != null ? (
                <>
                  {' '}
                  <CountBadge count={reviewCount} />
                </>
              ) : null}
            </NavLink>
            <NavLink to={`${base}/capture`} current={active === 'capture'}>
              Live capture
            </NavLink>
          </div>
          <div style={{ marginTop: 'auto', display: 'flex', flexDirection: 'column', gap: 2 }}>
            <NavLink to={`${base}/settings`} current={active === 'settings'}>
              Settings
            </NavLink>
          </div>
        </nav>
        {children}
      </div>
    </div>
  )
}

export function ReviewerAccess() {
  const [token, setToken] = useState('')
  const [notice, setNotice] = useState('')
  return (
    <details style={{ width: '100%', maxWidth: 320 }}>
      <summary style={{ cursor: 'pointer', fontSize: 13, textAlign: 'right' }}>Reviewer access</summary>
      <div
        style={{
          marginTop: 8,
          padding: 14,
          border: '1px solid var(--border-subtle)',
          borderRadius: 'var(--radius-md)',
          background: 'var(--surface-raised)',
        }}
      >
        <label htmlFor="reviewer-token" style={{ display: 'block', marginBottom: 6, fontSize: 12 }}>
          Access token
        </label>
        <input
          id="reviewer-token"
          className="fld"
          type="password"
          autoComplete="off"
          value={token}
          onChange={(event) => setToken(event.target.value)}
          style={{ width: '100%' }}
        />
        <button
          type="button"
          className="cia-btn"
          style={{ marginTop: 8 }}
          onClick={() => {
            setReviewerToken(token)
            setNotice(token ? 'Token set for this tab. The server checks each save.' : 'Reviewer token cleared.')
            setToken('')
          }}
        >
          Apply
        </button>
        {notice && <p role="status" style={{ margin: '8px 0 0', fontSize: 12 }}>{notice}</p>}
      </div>
    </details>
  )
}

function NavLink({ to, current, children }: { to: string; current: boolean; children: ReactNode }) {
  return (
    <Link className="nav" to={to} aria-current={current ? 'page' : undefined}>
      {children}
    </Link>
  )
}
