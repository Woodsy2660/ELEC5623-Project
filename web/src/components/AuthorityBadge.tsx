import type { CSSProperties, ReactNode } from 'react'

export function AuthorityBadge({
  can,
  children,
  style,
}: {
  can: boolean
  children: ReactNode
  style?: CSSProperties
}) {
  return (
    <span className={can ? 'cia-authority cia-authority--can' : 'cia-authority'} style={style}>
      {can ? '●' : '○'} {children}
    </span>
  )
}
