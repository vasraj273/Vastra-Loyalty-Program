// Which of the manufacturer's own CSV headers each field was read from. The
// server matches headers rather than dictating them, so showing the resolved
// mapping is the only way a wrong or missed guess is visible — otherwise a
// dropped phone column looks exactly like a successful import.
//
// `result.columns` is a list of free-form column names on the products import
// but a {field: matched header} mapping on the others; only a mapping renders.
export function ColumnMap({ columns }) {
  if (!columns || Array.isArray(columns)) return null
  return (
    <p className="hint" style={{ marginTop: 0 }}>
      Read from your file:{' '}
      {Object.entries(columns).map(([field, header], i) => (
        <span key={field}>
          {i > 0 && ' · '}
          {field} ← {header ? <strong>{header}</strong> : <em>not found</em>}
        </span>
      ))}
    </p>
  )
}

// Compact summary of a CSV bulk-import (created / skipped / first few errors).
// Shared by the Products, Distributors and Gifts tabs. Customers builds its own
// card because it also has to show the generated logins once.
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
      <ColumnMap columns={result.columns} />
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
