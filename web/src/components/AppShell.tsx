import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { CountBadge } from './CountBadge.tsx'

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
            <div style={{ padding: '12px 14px', borderTop: '1px solid var(--border-subtle)', marginTop: 8 }}>
              <div style={{ fontSize: 13 }}>Ben Wood</div>
              <div className="cia-authority" style={{ fontSize: 12 }}>
                Cannot confirm scope
              </div>
            </div>
          </div>
        </nav>
        {children}
      </div>
    </div>
  )
}

function NavLink({ to, current, children }: { to: string; current: boolean; children: ReactNode }) {
  return (
    <Link className="nav" to={to} aria-current={current ? 'page' : undefined}>
      {children}
    </Link>
  )
}
