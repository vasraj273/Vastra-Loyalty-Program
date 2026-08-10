// Search input with a clear (×) button. Shared by every searchable tab so the
// clear affordance behaves and looks the same everywhere. `type` stays "text"
// on purpose — type="search" would add WebKit's own × next to ours.
export default function SearchBox({ value, onChange, placeholder, ...rest }) {
  return (
    <div className="search-box">
      <input
        className="search"
        type="text"
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => e.key === 'Escape' && onChange('')}
        {...rest}
      />
      {value && (
        <button
          type="button"
          className="search-clear"
          aria-label="Clear search"
          title="Clear search"
          onClick={() => onChange('')}
        >
          ×
        </button>
      )}
    </div>
  )
}
