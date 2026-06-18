import { useCallback, useEffect, useState } from 'react'
import { get, post, patch, del } from '../api.js'

const EMPTY = { name: '', shop_name: '', region: '', phone: '' }
const fmt = (n) => (n ?? 0).toLocaleString('en-IN')

export default function Customers() {
  const [list, setList] = useState(null)
  const [form, setForm] = useState(EMPTY)
  const [showForm, setShowForm] = useState(false)
  const [error, setError] = useState(null)
  const [notice, setNotice] = useState(null)
  const [busy, setBusy] = useState(false)
  const [query, setQuery] = useState('')
  const [editing, setEditing] = useState(null)
  const [modal, setModal] = useState(null) // {type:'adjust', r} | {type:'transfer'}
  const [pts, setPts] = useState('')
  const [note, setNote] = useState('')
  const [fromId, setFromId] = useState('')
  const [toId, setToId] = useState('')

  const [cities, setCities] = useState([])

  const load = useCallback(() => {
    get('/retailers').then(setList).catch((e) => setError(e.message))
  }, [])

  useEffect(load, [load])
  useEffect(() => {
    get('/public/cities').then(setCities).catch(() => {})
  }, [])

  const submit = async (e) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      const out = await post('/retailers', {
        ...form,
        phone: form.phone || null,
      })
      const place =
        out.lat != null
          ? `Placed on the map at ${out.region}.`
          : !out.region
            ? "No city set — it'll be detected from the first scan location."
            : `City "${out.region}" not in the map lookup; pinned by GPS on first scan.`
      const creds = out.login_username
        ? ` Login → ${out.login_username} / ${out.login_password}`
        : ''
      setNotice(`${out.shop_name} added. ${place}${creds}`)
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
      await patch(`/retailers/${editing.id}`, {
        name: editing.name,
        shop_name: editing.shop_name,
        region: editing.region,
        phone: editing.phone || null,
      })
      setEditing(null)
      load()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const remove = async (r) => {
    if (!window.confirm(`Remove "${r.shop_name}"? This cannot be undone.`))
      return
    setError(null)
    try {
      await del(`/retailers/${r.id}`)
      load()
    } catch (err) {
      setError(err.message)
    }
  }

  const doAdjust = async () => {
    setBusy(true)
    setError(null)
    try {
      await post(`/retailers/${modal.r.id}/adjust`, {
        points: Number(pts),
        note,
      })
      setModal(null)
      load()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const doTransfer = async () => {
    setBusy(true)
    setError(null)
    try {
      await post('/retailers/transfer', {
        from_retailer_id: Number(fromId),
        to_retailer_id: Number(toId),
        points: Number(pts),
        note,
      })
      setModal(null)
      load()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  if (!list) return <p className="loading">Loading…</p>

  const q = query.trim().toLowerCase()
  const filtered = q
    ? list.filter((r) =>
        [r.name, r.shop_name, r.region, r.phone ?? '']
          .join(' ')
          .toLowerCase()
          .includes(q),
      )
    : list

  return (
    <div className="customers">
      <div className="schemes-head">
        <h2 className="page-title">
          Customers <span className="count">{list.length}</span>
        </h2>
        <div className="btn-row">
          <button
            className="btn-secondary"
            onClick={() => {
              setPts('')
              setNote('')
              setFromId('')
              setToId('')
              setModal({ type: 'transfer' })
            }}
          >
            Transfer points
          </button>
          <button className="btn-primary" onClick={() => setShowForm((s) => !s)}>
            {showForm ? 'Close' : '+ Add customer'}
          </button>
        </div>
      </div>
      {error && <p className="error">{error}</p>}
      {notice && <p className="created-note">{notice}</p>}

      {showForm && (
        <form className="panel-card scheme-form" onSubmit={submit}>
          <div className="form-grid">
            <label>
              Owner name
              <input
                required
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                placeholder="Ramesh Kumar"
              />
            </label>
            <label>
              Shop name
              <input
                required
                value={form.shop_name}
                onChange={(e) =>
                  setForm({ ...form, shop_name: e.target.value })
                }
                placeholder="Kumar Sarees"
              />
            </label>
            <label>
              City <span className="hint">(optional — auto-detected on first scan)</span>
              <input
                list="city-options"
                value={form.region}
                onChange={(e) => setForm({ ...form, region: e.target.value })}
                placeholder="Leave blank to detect from first scan"
              />
              <datalist id="city-options">
                {cities.map((c) => (
                  <option key={c} value={c.replace(/\b\w/g, (m) => m.toUpperCase())} />
                ))}
              </datalist>
            </label>
            <label>
              Phone (optional)
              <input
                value={form.phone}
                onChange={(e) => setForm({ ...form, phone: e.target.value })}
                placeholder="98XXXXXXXX"
              />
            </label>
          </div>
          <p className="hint" style={{ margin: 0 }}>
            Map location is set automatically from the city. The exact shop
            position locks in by GPS the first time this customer scans a code.
          </p>
          <button className="btn-primary" disabled={busy}>
            {busy ? 'Adding…' : 'Add customer'}
          </button>
        </form>
      )}

      <div className="panel-card table-card">
        <div className="table-tools">
          <input
            className="search"
            placeholder="Search name, shop, city, phone…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        <table className="data-table">
          <thead>
            <tr>
              <th>Shop</th>
              <th>Owner</th>
              <th>City</th>
              <th>Phone</th>
              <th>Location</th>
              <th className="num">Scans</th>
              <th className="num">Points</th>
              <th className="actions-col">Actions</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((r) =>
              editing?.id === r.id ? (
                <tr key={r.id} className="editing-row">
                  <td>
                    <input
                      className="inline-input"
                      value={editing.shop_name}
                      onChange={(e) =>
                        setEditing({ ...editing, shop_name: e.target.value })
                      }
                    />
                  </td>
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
                      list="city-options"
                      value={editing.region}
                      onChange={(e) =>
                        setEditing({ ...editing, region: e.target.value })
                      }
                    />
                  </td>
                  <td>
                    <input
                      className="inline-input"
                      value={editing.phone ?? ''}
                      onChange={(e) =>
                        setEditing({ ...editing, phone: e.target.value })
                      }
                    />
                  </td>
                  <td>
                    <span className="loc-badge">
                      {r.location_source === 'gps' ? 'GPS kept' : 'auto'}
                    </span>
                  </td>
                  <td className="num">{fmt(r.scans)}</td>
                  <td className="num">{fmt(r.points)}</td>
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
                <tr key={r.id}>
                  <td>{r.shop_name}</td>
                  <td>{r.name}</td>
                  <td>{r.region || <span style={{ color: 'var(--ink-soft)' }}>Pending first scan</span>}</td>
                  <td className="mono">{r.phone ?? '—'}</td>
                  <td>
                    {r.location_source === 'gps' ? (
                      <span className="loc-badge gps">GPS · exact</span>
                    ) : r.location_source === 'city' ? (
                      <span className="loc-badge">city</span>
                    ) : (
                      <span className="loc-badge none">pending</span>
                    )}
                  </td>
                  <td className="num">{fmt(r.scans)}</td>
                  <td className="num">{fmt(r.points)}</td>
                  <td className="actions-col">
                    <button
                      className="btn-ghost small"
                      onClick={() =>
                        setEditing({
                          id: r.id,
                          name: r.name,
                          shop_name: r.shop_name,
                          region: r.region,
                          phone: r.phone,
                        })
                      }
                    >
                      Edit
                    </button>
                    <button
                      className="btn-ghost small"
                      onClick={() => {
                        setPts('')
                        setNote('')
                        setModal({ type: 'adjust', r })
                      }}
                    >
                      Points
                    </button>
                    <button
                      className="btn-ghost small danger"
                      onClick={() => remove(r)}
                    >
                      Remove
                    </button>
                  </td>
                </tr>
              ),
            )}
            {filtered.length === 0 && (
              <tr>
                <td colSpan="8" className="empty">
                  No customers match.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {modal?.type === 'adjust' && (
        <div className="modal-backdrop" onClick={() => setModal(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>Adjust points — {modal.r.shop_name}</h3>
            <p className="hint" style={{ margin: 0 }}>
              Current balance {fmt(modal.r.points)}. Use a negative number to
              remove points. Cannot go below zero.
            </p>
            <label>
              Points (+ add / − remove)
              <input
                type="number"
                value={pts}
                onChange={(e) => setPts(e.target.value)}
                placeholder="e.g. 50 or -50"
              />
            </label>
            <label>
              Reason
              <input
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder="Why this correction?"
              />
            </label>
            <div className="btn-row">
              <button
                className="btn-primary"
                disabled={busy || !pts || !note.trim()}
                onClick={doAdjust}
              >
                Apply
              </button>
              <button className="btn-ghost" onClick={() => setModal(null)}>
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

      {modal?.type === 'transfer' && (
        <div className="modal-backdrop" onClick={() => setModal(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>Transfer points</h3>
            <p className="hint" style={{ margin: 0 }}>
              Move points from one shop to another (e.g. a scan credited to the
              wrong retailer).
            </p>
            <label>
              From
              <select value={fromId} onChange={(e) => setFromId(e.target.value)}>
                <option value="">Select shop…</option>
                {list.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.shop_name} ({fmt(r.points)} pts)
                  </option>
                ))}
              </select>
            </label>
            <label>
              To
              <select value={toId} onChange={(e) => setToId(e.target.value)}>
                <option value="">Select shop…</option>
                {list.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.shop_name} ({fmt(r.points)} pts)
                  </option>
                ))}
              </select>
            </label>
            <label>
              Points
              <input
                type="number"
                min="1"
                value={pts}
                onChange={(e) => setPts(e.target.value)}
              />
            </label>
            <label>
              Reason
              <input
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder="Why this transfer?"
              />
            </label>
            <div className="btn-row">
              <button
                className="btn-primary"
                disabled={
                  busy || !fromId || !toId || fromId === toId ||
                  !pts || !note.trim()
                }
                onClick={doTransfer}
              >
                Transfer
              </button>
              <button className="btn-ghost" onClick={() => setModal(null)}>
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
