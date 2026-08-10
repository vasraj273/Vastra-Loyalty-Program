// The one blank state used across the panel: a card that says what is missing
// and what to do about it, instead of an empty table with only headers.
// `action` takes buttons; `compact` is for small cards (dashboard tiles).
export default function EmptyState({
  icon = '📋',
  title,
  message,
  action,
  compact = false,
}) {
  return (
    <div className={compact ? 'empty-state compact' : 'empty-state'}>
      <span className="empty-icon" aria-hidden="true">{icon}</span>
      <p className="empty-title">{title}</p>
      {message && <p className="empty-msg">{message}</p>}
      {action && <div className="btn-row empty-actions">{action}</div>}
    </div>
  )
}
