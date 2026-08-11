import { useEffect, useRef, useState } from 'react'
import { IconDots, IconPlus } from './icons.jsx'

// A pill toolbar button: icon + label on white. `danger` turns it red.
export function ToolbarButton({ icon, children, danger, ...rest }) {
  return (
    <button className={danger ? 'toolbar-btn danger' : 'toolbar-btn'} {...rest}>
      {icon}
      {children}
    </button>
  )
}

// The ⋮ button at the extreme right of a toolbar. `items` are the actions that
// don't earn a permanent slot (export, sample, delete all); an item whose
// `show` is false is dropped, and the whole menu disappears when nothing is
// left — so an empty list never shows an empty menu.
export function OverflowMenu({ items }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)
  const visible = items.filter((it) => it && it.show !== false)

  useEffect(() => {
    if (!open) return undefined
    const onDoc = (e) => {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false)
    }
    const onEsc = (e) => e.key === 'Escape' && setOpen(false)
    document.addEventListener('mousedown', onDoc)
    document.addEventListener('keydown', onEsc)
    return () => {
      document.removeEventListener('mousedown', onDoc)
      document.removeEventListener('keydown', onEsc)
    }
  }, [open])

  if (visible.length === 0) return null

  return (
    <div className="overflow-menu" ref={ref}>
      <button
        className={open ? 'toolbar-btn icon-only open' : 'toolbar-btn icon-only'}
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="More actions"
        title="More actions"
      >
        <IconDots />
      </button>
      {open && (
        <div className="menu-pop" role="menu">
          {visible.map((it) => (
            <button
              key={it.label}
              role="menuitem"
              className={it.danger ? 'menu-item danger' : 'menu-item'}
              disabled={it.disabled}
              title={it.title}
              onClick={() => {
                setOpen(false)
                it.onClick()
              }}
            >
              {it.icon}
              {it.label}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

// The circular add button pinned to the bottom-right of a tab. Replaces the
// old "+ Add …" button that used to sit in the toolbar.
export function Fab({ label, onClick, close }) {
  return (
    <button
      className={close ? 'fab close' : 'fab'}
      onClick={onClick}
      aria-label={label}
      title={label}
    >
      <IconPlus />
    </button>
  )
}
