import { useCallback, useEffect, useState } from 'react'
import { get, post, patch, del } from '../api.js'

const EMPTY = { name: '', description: '', points_cost: 100, image_url: '' }
const fmt = (n) => (n ?? 0).toLocaleString('en-IN')

export default function Gifts() {
  const [list, setList] = useState(null)
  const [form, setForm] = useState(EMPTY)
  const [showForm, setShowForm] = useState(false)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback(() => {
    get('/gifts').then(setList).catch((e) => setError(e.message))
  }, [])

  useEffect(load, [load])

  const add = async (e) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await post('/gifts', {
        ...form,
        points_cost: Number(form.points_cost),
        image_url: form.image_url || null,
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

  const toggleActive = async (g) => {
    setError(null)
    try {
      await patch(`/gifts/${g.id}`, { active: !g.active })
      load()
    } catch (err) {
      setError(err.message)
    }
  }

  const remove = async (g) => {
    if (!window.confirm(`Delete "${g.name}"?`)) return
    setError(null)
    try {
      await del(`/gifts/${g.id}`)
      load()
    } catch (err) {
      setError(err.message)
    }
  }

  if (!list) return <p className="loading">Loading…</p>

  return (
    <div className="gifts">
      <div className="schemes-head">
        <h2 className="page-title">
          Gifts <span className="count">{list.length}</span>
        </h2>
        <button className="btn-primary" onClick={() => setShowForm((s) => !s)}>
          {showForm ? 'Close' : '+ Add gift'}
        </button>
      </div>
      <p className="hint">
        Rewards retailers can claim with their points in the shop. Claims land
        in the <strong>Redemptions</strong> tab for approval.
      </p>
      {error && <p className="error">{error}</p>}

      {showForm && (
        <form className="panel-card scheme-form" onSubmit={add}>
          <div className="form-grid">
            <label>
              Gift name
              <input
                required
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                placeholder="Branded umbrella"
              />
            </label>
            <label>
              Points cost
              <input
                required
                type="number"
                min="1"
                value={form.points_cost}
                onChange={(e) =>
                  setForm({ ...form, points_cost: e.target.value })
                }
              />
            </label>
            <label>
              Image URL (optional)
              <input
                value={form.image_url}
                onChange={(e) =>
                  setForm({ ...form, image_url: e.target.value })
                }
                placeholder="https://…"
              />
            </label>
            <label>
              Description (optional)
              <input
                value={form.description}
                onChange={(e) =>
                  setForm({ ...form, description: e.target.value })
                }
                placeholder="Short detail shown in the shop"
              />
            </label>
          </div>
          <button className="btn-primary" disabled={busy}>
            {busy ? 'Adding…' : 'Add gift'}
          </button>
        </form>
      )}

      <div className="scheme-grid">
        {list.map((g) => (
          <div
            key={g.id}
            className={g.active ? 'scheme-card active' : 'scheme-card previous'}
          >
            <header>
              <h4>{g.name}</h4>
              <span className="bonus">{g.points_cost} pts</span>
            </header>
            {g.description && <p className="desc">{g.description}</p>}
            <p className="coverage">
              {g.claims} claim{g.claims === 1 ? '' : 's'} ·{' '}
              {g.active ? 'active in shop' : 'hidden'}
            </p>
            <div className="btn-row">
              <button className="btn-ghost small" onClick={() => toggleActive(g)}>
                {g.active ? 'Deactivate' : 'Activate'}
              </button>
              <button
                className="btn-ghost small danger"
                onClick={() => remove(g)}
              >
                Delete
              </button>
            </div>
          </div>
        ))}
        {list.length === 0 && <p className="empty">No gifts yet.</p>}
      </div>
    </div>
  )
}
