import { Link } from 'react-router-dom'
import { StateChip, type LifecycleState } from './StateChip.tsx'

export type RegisterTableRow = {
  key: string
  versionLabel: string
  text: string
  state: LifecycleState
  changedLabel: string
  note?: string | null
  href: string
}

export function RegisterTable({ rows }: { rows: RegisterTableRow[] }) {
  return (
    <table className="cia-register">
      <thead>
        <tr>
          <th style={{ width: 110 }}>ID</th>
          <th>Requirement</th>
          <th style={{ width: 150 }}>State</th>
          <th style={{ width: 130 }}>Last changed</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.key} data-state={row.state}>
            <td>
              <span className="cia-id">{row.versionLabel}</span>
            </td>
            <td>
              <Link className="rowlink" to={row.href}>
                <span className="cia-register__text">{row.text}</span>
              </Link>
              {row.note ? (
                <div
                  style={{
                    marginTop: 4,
                    fontSize: 13,
                    color: row.state === 'contradicted' ? 'var(--state-contradicted)' : 'var(--ink-meta)',
                  }}
                >
                  {row.note}
                </div>
              ) : null}
            </td>
            <td>
              <StateChip state={row.state} />
            </td>
            <td>
              <span style={{ fontSize: 13, color: 'var(--ink-meta)' }}>{row.changedLabel}</span>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
