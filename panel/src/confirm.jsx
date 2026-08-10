import {
  createContext, useCallback, useContext, useEffect, useRef, useState,
} from 'react'

// Promise-based confirmation dialog. Call `const confirm = useConfirm()` then
// `if (!(await confirm({ title, message, confirmLabel, danger }))) return`
// before any action that changes a points balance, deletes a list, or ends the
// session.
const ConfirmContext = createContext(() => Promise.resolve(false))

export const useConfirm = () => useContext(ConfirmContext)

export function ConfirmProvider({ children }) {
  const [opts, setOpts] = useState(null)
  const resolver = useRef(null)

  const confirm = useCallback(
    (options) =>
      new Promise((resolve) => {
        resolver.current = resolve
        setOpts({ confirmLabel: 'Confirm', ...options })
      }),
    [],
  )

  const close = useCallback((result) => {
    setOpts(null)
    const r = resolver.current
    resolver.current = null
    r?.(result)
  }, [])

  // Escape cancels, so the dialog is never a dead end for keyboard users.
  useEffect(() => {
    if (!opts) return undefined
    const onKey = (e) => e.key === 'Escape' && close(false)
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [opts, close])

  return (
    <ConfirmContext.Provider value={confirm}>
      {children}
      {opts && (
        <div
          className="modal-backdrop confirm-backdrop"
          onClick={() => close(false)}
        >
          <div
            className="modal confirm-modal"
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="confirm-title"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Body wrapper owns the padding, so a dialog with no message
                keeps the same breathing room around its title. */}
            <div className="confirm-body">
              <div className="confirm-head">
                <span
                  className={opts.danger ? 'confirm-icon danger' : 'confirm-icon'}
                  aria-hidden="true"
                >
                  {opts.danger ? '!' : '?'}
                </span>
                <h3 id="confirm-title">{opts.title}</h3>
              </div>
              {opts.message && <p className="confirm-msg">{opts.message}</p>}
            </div>
            {/* Cancel first, confirm last: the destructive button is the one
                furthest from an accidental click on the message. */}
            <div className="confirm-actions">
              <button className="btn-ghost" onClick={() => close(false)}>
                Cancel
              </button>
              <button
                className={opts.danger ? 'btn-danger' : 'btn-primary'}
                onClick={() => close(true)}
                autoFocus
              >
                {opts.confirmLabel}
              </button>
            </div>
          </div>
        </div>
      )}
    </ConfirmContext.Provider>
  )
}
