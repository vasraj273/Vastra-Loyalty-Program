// Compact summary of a CSV bulk-import (created / skipped / first few errors).
// Shared by the Products and Distributors tabs.
export default function ImportResult({ result, onDismiss }) {
  if (!result) return null
  return (
    <div className="panel-card" style={{ marginBottom: 14 }}>
      <div className="schemes-head" style={{ marginBottom: 6 }}>
        <strong>
          Imported {result.created}
          {result.updated ? ` · updated ${result.updated}` : ''} · skipped{' '}
          {result.skipped}
          {result.errors?.length ? ` · ${result.errors.length} error(s)` : ''}
        </strong>
        <button className="btn-ghost small" onClick={onDismiss}>
          Dismiss
        </button>
      </div>
      {result.errors?.length > 0 && (
        <ul className="hint" style={{ marginTop: 0 }}>
          {result.errors.slice(0, 8).map((er, i) => (
            <li key={i}>{er}</li>
          ))}
        </ul>
      )}
    </div>
  )
}
