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
      {client ? (
        <>
          <span className="cia-scope__client">{client}</span>
          <span className="cia-scope__sep">/</span>
        </>
      ) : null}
      <button type="button" className="cia-scope__project">
        {projectName} ▾
      </button>
      <span className="cia-scope__note">{count}</span>
    </div>
  )
}
