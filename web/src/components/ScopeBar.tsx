export function ScopeBar({
  client,
  projectName,
  count,
}: {
  client: string
  projectName: string
  count: string
}) {
  return (
    <div className="cia-scope">
      <span className="cia-scope__client">{client}</span>
      <span className="cia-scope__sep">/</span>
      <button type="button" className="cia-scope__project">
        {projectName} ▾
      </button>
      <span className="cia-id">{count}</span>
      <span className="cia-scope__note">Scoped to this project — retrieval never crosses projects</span>
    </div>
  )
}
