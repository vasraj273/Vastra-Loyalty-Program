// Compact summary of a CSV bulk-import (created / skipped / first few errors).
// Shared by the Products and Distributors tabs.
//
// `result.columns` is a list of free-form column names on the products import,
// but a {field: matched header} mapping on the distributors import — only the
// mapping is rendered, so the manufacturer can see which of their own columns
// we read (a wrong guess is otherwise invisible until they scan the table).
export default function ImportResult({ result, onDismiss }) {
  if (!result) return null
  const mapping =
    result.columns && !Array.isArray(result.columns) ? result.columns : null
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
      {mapping && (
        <p className="hint" style={{ marginTop: 0 }}>
          Read from your file:{' '}
          {Object.entries(mapping).map(([field, header], i) => (
            <span key={field}>
              {i > 0 && ' · '}
              {field} ←{' '}
              {header ? <strong>{header}</strong> : <em>not found</em>}
            </span>
          ))}
        </p>
      )}
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
