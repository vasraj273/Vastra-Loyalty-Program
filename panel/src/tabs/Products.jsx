import { useCallback, useEffect, useState } from 'react'
import { get, put } from '../api.js'
import GenerateQrModal from '../components/GenerateQrModal.jsx'
import { downloadCSV, today } from '../utils/csv.js'

export default function Products() {
  const [list, setList] = useState(null)
  const [editing, setEditing] = useState(null) // {external_id, points}
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const [showGenerate, setShowGenerate] = useState(false)

  const exportCsv = () => {
    downloadCSV(
      `products-${today()}.csv`,
      [
        { label: 'Product', key: 'name' },
        { label: 'SKU', key: 'sku' },
        { label: 'Points per scan', key: 'points' },
      ],
      list,
    )
  }

  const load = useCallback(() => {
    setError(null)
    get('/vastra/products').then(setList).catch((e) => setError(e.message))
  }, [])

  useEffect(load, [load])

  const savePoints = async () => {
    setBusy(true)
    setError(null)
    try {
      await put(`/vastra/products/${editing.external_id}/points`, {
        points: Number(editing.points),
      })
      setEditing(null)
      load()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  if (!list && !error) return <p className="loading">Loading…</p>

  return (
    <div className="products">
      <div className="schemes-head">
        <h2 className="page-title">
          Products <span className="count">{list?.length ?? 0}</span>
        </h2>
        <div className="btn-row">
          <button
            className="btn-secondary"
            onClick={() => setShowGenerate(true)}
            disabled={!list?.length}
          >
            Generate QR
          </button>
          <button
            className="btn-secondary"
            disabled={!list?.length}
            onClick={exportCsv}
          >
            ↓ Export CSV
          </button>
        </div>
      </div>
      <p className="hint">
        Product catalog syncs from Vastra. Points per scan are set by you and
        affect <strong>future batches only</strong> — already printed batches
        keep their promised points.
      </p>
      {error && <p className="error">{error}</p>}

      {list && (
        <div className="panel-card table-card">
          <table className="data-table">
            <thead>
              <tr>
                <th>Product</th>
                <th>SKU</th>
                <th className="num">Points / scan</th>
                <th className="actions-col">Actions</th>
              </tr>
            </thead>
            <tbody>
              {list.map((p) =>
                editing?.external_id === p.external_id ? (
                  <tr key={p.external_id} className="editing-row">
                    <td>{p.name}</td>
                    <td className="mono">{p.sku}</td>
                    <td className="num">
                      <input
                        className="inline-input num"
                        type="number"
                        min="0"
                        value={editing.points}
                        onChange={(e) =>
                          setEditing({ ...editing, points: e.target.value })
                        }
                      />
                    </td>
                    <td className="actions-col">
                      <button
                        className="btn-ghost small"
                        onClick={savePoints}
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
                  <tr key={p.external_id}>
                    <td>{p.name}</td>
                    <td className="mono">{p.sku}</td>
                    <td className="num">
                      <strong>{p.points}</strong>
                    </td>
                    <td className="actions-col">
                      <button
                        className="btn-ghost small"
                        onClick={() =>
                          setEditing({
                            external_id: p.external_id,
                            points: p.points,
                          })
                        }
                      >
                        Edit points
                      </button>
                    </td>
                  </tr>
                ),
              )}
            </tbody>
          </table>
        </div>
      )}

      {showGenerate && (
        <GenerateQrModal
          products={list}
          onClose={() => setShowGenerate(false)}
        />
      )}
    </div>
  )
}
