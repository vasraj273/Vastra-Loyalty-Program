import { useCallback, useEffect, useState } from 'react'
import { get, post, patch, del } from '../api.js'

const EMPTY = { name: '', phone: '', region: '' }
const fmt = (n) => (n ?? 0).toLocaleString('en-IN')

export default function Distributors() {
  const [list, setList] = useState(null)
  const [form, setForm] = useState(EMPTY)
  const [showForm, setShowForm] = useState(false)
  const [editing, setEditing] = useState(null) // {id, name, phone, region}
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback(() => {
    get('/distributors').then(setList).catch((e) => setError(e.message))
  }, [])

  useEffect(load, [load])

  const add = async (e) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await post('/distributors', {
        name: form.name,
        phone: form.phone || null,
        region: form.region || null,
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
      await patch(`/distributors/${editing.id}`, {
        name: editing.name,
        phone: editing.phone || null,
        region: editing.region || null,
      })
      setEditing(null)
      load()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const remove = async (d) => {
    if (
      !window.confirm(
        `Delete distributor "${d.name}"? Its ${d.retailers} retailer(s) will be ` +
          'unassigned (not deleted). Past scans keep their record.',
      )
    )
      return
    setError(null)
    try {
      await del(`/distributors/${d.id}`)
      load()
    } catch (err) {
      setError(err.message)
    }
  }

  if (!list) return <p className="loading">Loading…</p>

  return (
    <div className="distributors">
      <div className="schemes-head">
        <h2 className="page-title">
          Distributors <span className="count">{list.length}</span>
        </h2>
        <button className="btn-primary" onClick={() => setShowForm((s) => !s)}>
          {showForm ? 'Close' : '+ Add distributor'}
        </button>
      </div>
      <p className="hint">
        Distributors sit between you and your retailers (you → distributor →
        retailer). Assign retailers to a distributor in the Customers tab, or via
        the <strong>distributor</strong> column when importing a CSV.
      </p>
      {error && <p className="error">{error}</p>}

      {showForm && (
        <form className="panel-card scheme-form" onSubmit={add}>
          <div className="form-grid three">
            <label>
              Distributor name
              <input
                required
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                placeholder="Vansh Distributors"
              />
            </label>
            <label>
              Phone <span className="hint">(optional)</span>
              <input
                value={form.phone}
                onChange={(e) => setForm({ ...form, phone: e.target.value })}
                placeholder="98XXXXXXXX"
              />
            </label>
            <label>
              Region <span className="hint">(optional)</span>
              <input
                value={form.region}
                onChange={(e) => setForm({ ...form, region: e.target.value })}
                placeholder="Gujarat"
              />
            </label>
          </div>
          <button className="btn-primary" disabled={busy}>
            {busy ? 'Adding…' : 'Add distributor'}
          </button>
        </form>
      )}

      <div className="panel-card table-card">
        <table className="data-table">
          <thead>
            <tr>
              <th>Distributor</th>
              <th>Phone</th>
              <th>Region</th>
              <th className="num">Retailers</th>
              <th className="num">Scans</th>
              <th className="actions-col">Actions</th>
            </tr>
          </thead>
          <tbody>
            {list.map((d) =>
              editing?.id === d.id ? (
                <tr key={d.id} className="editing-row">
                  <td>
                    <input
                      className="inline-input"
                      value={editing.name}
                      onChange={(e) =>
                        setEditing({ ...editing, name: e.target.value })
                      }
                    />
                  </td>
                  <td>
                    <input
                      className="inline-input"
                      value={editing.phone}
                      onChange={(e) =>
                        setEditing({ ...editing, phone: e.target.value })
                      }
                    />
                  </td>
                  <td>
                    <input
                      className="inline-input"
                      value={editing.region}
                      onChange={(e) =>
                        setEditing({ ...editing, region: e.target.value })
                      }
                    />
                  </td>
                  <td className="num">{fmt(d.retailers)}</td>
                  <td className="num">{fmt(d.scans)}</td>
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
                <tr key={d.id}>
                  <td>{d.name}</td>
                  <td className="mono">{d.phone ?? '—'}</td>
                  <td>{d.region ?? '—'}</td>
                  <td className="num">{fmt(d.retailers)}</td>
                  <td className="num">{fmt(d.scans)}</td>
                  <td className="actions-col">
                    <button
                      className="btn-ghost small"
                      onClick={() =>
                        setEditing({
                          id: d.id,
                          name: d.name,
                          phone: d.phone ?? '',
                          region: d.region ?? '',
                        })
                      }
                    >
                      Edit
                    </button>
                    <button
                      className="btn-ghost small danger"
                      onClick={() => remove(d)}
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
