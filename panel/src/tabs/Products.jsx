import { useCallback, useEffect, useRef, useState } from 'react'
import { get, post, patch, del } from '../api.js'
import ImportResult from '../components/ImportResult.jsx'

const EMPTY = { name: '', sku: '', loyalty_points: 10 }
const fmt = (n) => (n ?? 0).toLocaleString('en-IN')

export default function Products() {
  const [list, setList] = useState(null)
  const [form, setForm] = useState(EMPTY)
  const [showForm, setShowForm] = useState(false)
  const [editing, setEditing] = useState(null) // {id, name, loyalty_points}
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const [importResult, setImportResult] = useState(null)
  const fileRef = useRef(null)

  // Bulk import products from a CSV file (name, sku, loyalty_points).
  const onImportFile = async (e) => {
    const file = e.target.files?.[0]
    if (file) e.target.value = '' // allow re-importing the same filename
    if (!file) return
    setBusy(true)
    setError(null)
    setImportResult(null)
    try {
      const csv = await file.text()
      setImportResult(await post('/products/import', { csv }))
      load()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const load = useCallback(() => {
    get('/products').then(setList).catch((e) => setError(e.message))
  }, [])

  useEffect(load, [load])

  const add = async (e) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await post('/products', {
        ...form,
        loyalty_points: Number(form.loyalty_points),
      })
      setForm(EMPTY)
      setShowForm(false)
      load()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const saveEdit = async () => {
    setBusy(true)
    setError(null)
    try {
      await patch(`/products/${editing.id}`, {
        name: editing.name,
        loyalty_points: Number(editing.loyalty_points),
      })
      setEditing(null)
      load()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const remove = async (p) => {
    if (!window.confirm(`Delete "${p.name}"? This cannot be undone.`)) return
    setError(null)
    try {
      await del(`/products/${p.id}`)
      load()
    } catch (err) {
      setError(err.message)
    }
  }

  if (!list) return <p className="loading">Loading…</p>

  return (
    <div className="products">
      <div className="schemes-head">
        <h2 className="page-title">
          Products <span className="count">{list.length}</span>
        </h2>
        <div className="btn-row">
          <a
            className="btn-secondary"
            href={import.meta.env.DEV
              ? 'http://127.0.0.1:8000/web/generate'
              : '/web/generate'}
            target="_blank"
            rel="noreferrer"
          >
            Generate QR ↗
          </a>
          <input
            ref={fileRef}
            type="file"
            accept=".csv,text/csv"
            style={{ display: 'none' }}
            onChange={onImportFile}
          />
          <button
            className="btn-secondary"
            disabled={busy}
            onClick={() => fileRef.current?.click()}
            title="CSV columns: name, sku, loyalty_points"
          >
            Import CSV
          </button>
          <button
            className="btn-primary"
            onClick={() => setShowForm((s) => !s)}
          >
            {showForm ? 'Close' : '+ Add product'}
          </button>
        </div>
      </div>
      <p className="hint">
        Demo catalog — in the live version products sync from the Vastra ERP.
        Changing points affects <strong>future batches only</strong>; already
        printed batches keep their promised points.
      </p>
      {error && <p className="error">{error}</p>}
      <ImportResult result={importResult} onDismiss={() => setImportResult(null)} />

      {showForm && (
        <form className="panel-card scheme-form" onSubmit={add}>
          <div className="form-grid three">
            <label>
              Product name
              <input
                required
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                placeholder="Banarasi Brocade"
              />
            </label>
            <label>
              SKU
              <input
                required
                value={form.sku}
                onChange={(e) => setForm({ ...form, sku: e.target.value })}
                placeholder="SUR-BB-03"
              />
            </label>
            <label>
              Points per scan
              <input
                required
                type="number"
                min="0"
                value={form.loyalty_points}
                onChange={(e) =>
                  setForm({ ...form, loyalty_points: e.target.value })
                }
              />
            </label>
          </div>
          <button className="btn-primary" disabled={busy}>
            {busy ? 'Adding…' : 'Add product'}
          </button>
        </form>
      )}

      <div className="panel-card table-card">
        <table className="data-table">
          <thead>
            <tr>
              <th>Product</th>
              <th>SKU</th>
              <th className="num">Points / scan</th>
              <th className="num">Scans</th>
              <th className="actions-col">Actions</th>
            </tr>
          </thead>
          <tbody>
            {list.map((p) =>
              editing?.id === p.id ? (
                <tr key={p.id} className="editing-row">
                  <td>
                    <input
                      className="inline-input"
                      value={editing.name}
                      onChange={(e) =>
                        setEditing({ ...editing, name: e.target.value })
                      }
                    />
                  </td>
                  <td className="mono">{p.sku}</td>
                  <td className="num">
                    <input
                      className="inline-input num"
                      type="number"
                      min="0"
                      value={editing.loyalty_points}
                      onChange={(e) =>
                        setEditing({
                          ...editing,
                          loyalty_points: e.target.value,
                        })
                      }
                    />
                  </td>
                  <td className="num">{fmt(p.scans)}</td>
                  <td className="actions-col">
                    <button
                      className="btn-ghost small"
                      onClick={saveEdit}
                      disabled={busy}
                    >
                      Save
                    </button>
                    <button
                      className="btn-ghost small"
                      onClick={() => setEditing(null)}
                    >
                      Cancel
                    </button>
                  </td>
                </tr>
              ) : (
                <tr key={p.id}>
                  <td>{p.name}</td>
                  <td className="mono">{p.sku}</td>
                  <td className="num">
                    <strong>{p.loyalty_points}</strong>
                  </td>
                  <td className="num">{fmt(p.scans)}</td>
                  <td className="actions-col">
                    <button
                      className="btn-ghost small"
                      onClick={() =>
                        setEditing({
                          id: p.id,
                          name: p.name,
                          loyalty_points: p.loyalty_points,
                        })
                      }
                    >
                      Edit
                    </button>
                    <button
                      className="btn-ghost small danger"
                      onClick={() => remove(p)}
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ),
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
