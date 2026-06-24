import { useEffect, useState } from 'react'
import { get, post, printUrl } from '../api.js'

// In-panel QR generation — replaces the old standalone /web/generate webview so
// the manufacturer never leaves the Products page. Backend contract unchanged:
// POST /qr/generate, then the returned actions (save / print / discard).
export default function GenerateQrModal({ products, onClose }) {
  const [productId, setProductId] = useState(products[0]?.id ?? '')
  const [quantity, setQuantity] = useState(10)
  const [itemsPerBox, setItemsPerBox] = useState('')
  const [batch, setBatch] = useState(null) // generation result
  const [saved, setSaved] = useState(false)
  const [showSaved, setShowSaved] = useState(false)
  const [savedBatches, setSavedBatches] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  // Close on Escape, matching the other panel modals.
  useEffect(() => {
    const onEsc = (e) => e.key === 'Escape' && onClose()
    document.addEventListener('keydown', onEsc)
    return () => document.removeEventListener('keydown', onEsc)
  }, [onClose])

  const generate = async () => {
    setBusy(true)
    setError(null)
    try {
      const ipb = Number(itemsPerBox)
      const payload = {
        product_id: Number(productId),
        quantity: Number(quantity),
      }
      if (ipb >= 2) payload.items_per_box = ipb
      const res = await post('/qr/generate', payload)
      setBatch(res)
      setSaved(false)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const saveBatch = async () => {
    setError(null)
    try {
      await post(batch.actions.save)
      setSaved(true)
      if (showSaved) loadSaved()
    } catch (err) {
      setError(err.message)
    }
  }

  const printBatch = (batchId) => {
    window.open(printUrl(batchId), '_blank')
  }

  const newBatch = () => {
    setBatch(null)
    setSaved(false)
    setError(null)
  }

  const loadSaved = () => {
    get('/qr/batches?status=saved').then(setSavedBatches).catch(() => {})
  }

  const toggleSaved = () => {
    const next = !showSaved
    setShowSaved(next)
    if (next && savedBatches === null) loadSaved()
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h3>Generate loyalty QR</h3>

        {!batch ? (
          <>
            <p className="hint" style={{ margin: 0 }}>
              Points are frozen at generation — already-printed batches keep
              their value even if the product points change later.
            </p>
            <label>
              Product
              <select
                value={productId}
                onChange={(e) => setProductId(e.target.value)}
              >
                {products.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name} — {p.loyalty_points} pts
                  </option>
                ))}
              </select>
            </label>
            <label>
              Quantity
              <input
                type="number"
                min="1"
                max="10000"
                value={quantity}
                onChange={(e) => setQuantity(e.target.value)}
              />
            </label>
            <label>
              Items per box{' '}
              <span className="hint">(optional — makes box QR codes)</span>
              <input
                type="number"
                min="2"
                max="1000"
                value={itemsPerBox}
                onChange={(e) => setItemsPerBox(e.target.value)}
                placeholder="leave blank for none"
              />
            </label>
            {error && <p className="error">{error}</p>}
            <div className="btn-row">
              <button
                className="btn-primary"
                disabled={busy || !productId}
                onClick={generate}
              >
                {busy ? 'Generating…' : 'Generate QR codes'}
              </button>
              <button className="btn-ghost" onClick={toggleSaved}>
                {showSaved ? 'Hide saved batches' : 'Saved batches'}
              </button>
              <button className="btn-ghost" onClick={onClose}>
                Close
              </button>
            </div>
          </>
        ) : (
          <>
            <p style={{ margin: '4px 0' }}>
              <strong>{batch.quantity}</strong> codes for{' '}
              <strong>{batch.product_name}</strong>
            </p>
            <p style={{ margin: '4px 0' }}>
              {batch.points_per_code} points per scan
            </p>
            {batch.boxes ? (
              <p style={{ margin: '4px 0', color: 'var(--leaf)' }}>
                + {batch.boxes} box QR codes ({batch.items_per_box} items each)
                — print includes them
              </p>
            ) : null}
            <p className="mono sub" style={{ margin: '4px 0' }}>
              batch #{batch.batch_id}
            </p>
            {error && <p className="error">{error}</p>}
            <div className="btn-row">
              <button
                className="btn-primary"
                onClick={() => printBatch(batch.batch_id)}
              >
                Print stickers (PDF)
              </button>
              <button
                className="btn-secondary"
                disabled={saved}
                onClick={saveBatch}
              >
                {saved ? 'Saved ✓' : 'Save for later'}
              </button>
              <button className="btn-ghost" onClick={newBatch}>
                New batch
              </button>
            </div>
          </>
        )}

        {showSaved && (
          <div className="panel-card" style={{ marginTop: 14 }}>
            <strong style={{ fontFamily: "'Helvetica Neue', Helvetica, Arial, sans-serif" }}>
              Saved batches
            </strong>
            {savedBatches === null ? (
              <p className="hint" style={{ margin: '8px 0 0' }}>
                Loading…
              </p>
            ) : savedBatches.length === 0 ? (
              <p className="hint" style={{ margin: '8px 0 0' }}>
                No saved batches yet.
              </p>
            ) : (
              <table className="data-table" style={{ marginTop: 8 }}>
                <tbody>
                  {savedBatches.map((b) => (
                    <tr key={b.id}>
                      <td>
                        {b.product_name}
                        <span className="sub">
                          {' '}
                          · {b.quantity} codes · {b.points_per_code} pts ·{' '}
                          {b.created_at?.slice(0, 10)} · #{b.id}
                        </span>
                      </td>
                      <td className="actions-col">
                        <button
                          className="btn-ghost small"
                          onClick={() => printBatch(b.id)}
                        >
                          Print
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
