import { createContext, useCallback, useContext, useRef, useState } from 'react'

// Promise-based confirmation dialog. Call `const confirm = useConfirm()` then
// `if (!(await confirm({ title, message, confirmLabel, danger }))) return`
// before any action that changes a points balance.
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

  const close = (result) => {
    setOpts(null)
    const r = resolver.current
    resolver.current = null
    r?.(result)
  }

  return (
    <ConfirmContext.Provider value={confirm}>
      {children}
      {opts && (
        <div
          className="modal-backdrop confirm-backdrop"
          onClick={() => close(false)}
        >
          <div className="modal confirm-modal" onClick={(e) => e.stopPropagation()}>
            <h3>{opts.title}</h3>
            {opts.message && (
              <p className="confirm-msg">{opts.message}</p>
            )}
            <div className="btn-row">
              <button
                className={opts.danger ? 'btn-danger' : 'btn-primary'}
                onClick={() => close(true)}
                autoFocus
              >
                {opts.confirmLabel}
              </button>
              <button className="btn-ghost" onClick={() => close(false)}>
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </ConfirmContext.Provider>
  )
}
