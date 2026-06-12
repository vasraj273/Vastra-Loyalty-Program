import { useCallback, useEffect, useState } from 'react'
import { get, post } from '../api.js'

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

  const load = useCallback(() => {
    get('/retailers').then(setList).catch((e) => setError(e.message))
  }, [])

  useEffect(load, [load])

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
      setNotice(
        out.lat != null
          ? `${out.shop_name} added — placed on the map at ${out.region}.`
          : `${out.shop_name} added. City "${out.region}" not in the map ` +
            'lookup; the shop will be pinned by GPS on its first scan.',
      )
      setForm(EMPTY)
      setShowForm(false)
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
        <button className="btn-primary" onClick={() => setShowForm((s) => !s)}>
          {showForm ? 'Close' : '+ Add customer'}
        </button>
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
              City
              <input
                required
                value={form.region}
                onChange={(e) => setForm({ ...form, region: e.target.value })}
                placeholder="Jaipur"
              />
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
            </tr>
          </thead>
          <tbody>
            {filtered.map((r) => (
              <tr key={r.id}>
                <td>{r.shop_name}</td>
                <td>{r.name}</td>
                <td>{r.region}</td>
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
              </tr>
            ))}
            {filtered.length === 0 && (
              <tr>
                <td colSpan="7" className="empty">
                  No customers match.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
