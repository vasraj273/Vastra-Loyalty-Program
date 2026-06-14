import { useCallback, useEffect, useState } from 'react'
import { get, post, patch, del } from '../api.js'

const EMPTY = {
  name: '',
  description: '',
  points_cost: 1000,
  image_url: '',
}
const fmt = (n) => (n ?? 0).toLocaleString('en-IN')

export default function Gifts() {
  const [list, setList] = useState(null)
  const [form, setForm] = useState(EMPTY)
  const [editingId, setEditingId] = useState(null) // null = creating new
  const [showForm, setShowForm] = useState(false)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback(() => {
    get('/gifts').then(setList).catch((e) => setError(e.message))
  }, [])

  useEffect(load, [load])

  const openAdd = () => {
    setEditingId(null)
    setForm(EMPTY)
    setShowForm(true)
  }

  const openEdit = (g) => {
    setEditingId(g.id)
    setForm({
      name: g.name,
      description: g.description ?? '',
      points_cost: g.points_cost,
      image_url: g.image_url ?? '',
    })
    setShowForm(true)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  const submit = async (e) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const payload = {
        name: form.name,
        description: form.description,
        points_cost: Number(form.points_cost),
        image_url: form.image_url || null,
      }
      if (editingId) {
        await patch(`/gifts/${editingId}`, payload)
      } else {
        await post('/gifts', payload)
      }
      setForm(EMPTY)
      setEditingId(null)
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

  // Read a chosen file, downscale it, and store it inline as a data URI so
  // the image survives without depending on an external URL.
  const onFile = (e) => {
    const file = e.target.files?.[0]
    if (!file) return
    setError(null)
    const reader = new FileReader()
    reader.onload = () => {
      const img = new Image()
      img.onload = () => {
        const max = 600
        let { width, height } = img
        if (width > max || height > max) {
          const s = Math.min(max / width, max / height)
          width = Math.round(width * s)
          height = Math.round(height * s)
        }
        const canvas = document.createElement('canvas')
        canvas.width = width
        canvas.height = height
        canvas.getContext('2d').drawImage(img, 0, 0, width, height)
        setForm((f) => ({
          ...f,
          image_url: canvas.toDataURL('image/jpeg', 0.82),
        }))
      }
      img.onerror = () => setError('Could not read that image file')
      img.src = reader.result
    }
    reader.readAsDataURL(file)
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
          Reward shop <span className="count">{list.length}</span>
        </h2>
        <button className="btn-primary" onClick={showForm ? () => setShowForm(false) : openAdd}>
          {showForm ? 'Close' : '+ Add reward'}
        </button>
      </div>
      <p className="hint">
        Rewards retailers redeem with their points. Claims arrive in the{' '}
        <strong>Redemptions</strong> tab for approval.
      </p>
      {error && <p className="error">{error}</p>}

      {showForm && (
        <form className="panel-card scheme-form" onSubmit={submit}>
          <h3 style={{ margin: 0, fontFamily: 'Fraunces, serif' }}>
            {editingId ? 'Edit reward' : 'New reward'}
          </h3>
          <div className="form-grid">
            <label>
              Product name
              <input
                required
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                placeholder="LED TV (32 Inch)"
              />
            </label>
            <label>
              Points to redeem
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
              Description
              <input
                value={form.description}
                onChange={(e) =>
                  setForm({ ...form, description: e.target.value })
                }
                placeholder="Samsung / Mi / Similar Brand"
              />
            </label>
          </div>

          <div className="image-row">
            <label>
              Image URL
              <input
                value={form.image_url?.startsWith('data:') ? '' : form.image_url}
                onChange={(e) =>
                  setForm({ ...form, image_url: e.target.value })
                }
                placeholder="https://… product photo"
              />
            </label>
            <span className="or-sep">or</span>
            <label>
              Upload from device
              <input type="file" accept="image/*" onChange={onFile} />
            </label>
          </div>

          {form.image_url && (
            <div className="preview-row">
              <img
                src={form.image_url}
                alt=""
                className="img-preview"
                onError={(e) => {
                  e.currentTarget.style.display = 'none'
                }}
              />
              <button
                type="button"
                className="btn-ghost small"
                onClick={() => setForm({ ...form, image_url: '' })}
              >
                Remove image
              </button>
              {form.image_url.startsWith('data:') && (
                <span className="sub">Uploaded photo (stored with the reward)</span>
              )}
            </div>
          )}
          <button className="btn-primary" disabled={busy}>
            {busy ? 'Saving…' : editingId ? 'Save changes' : 'Add reward'}
          </button>
        </form>
      )}

      <div className="gift-grid">
        {list.map((g) => (
          <div key={g.id} className={g.active ? 'gift-card' : 'gift-card off'}>
            <div className="gift-badge">
              <span className="pts">{fmt(g.points_cost)}</span>
              <span className="lbl">POINTS</span>
            </div>
            <div className="gift-thumb">
              {g.image_url ? (
                <img
                  src={g.image_url}
                  alt=""
                  onError={(e) => {
                    e.currentTarget.replaceWith(
                      Object.assign(document.createElement('div'), {
                        className: 'ph',
                        textContent: '🎁',
                      }),
                    )
                  }}
                />
              ) : (
                <div className="ph">🎁</div>
              )}
            </div>
            <div className="gift-body">
              <h4>{g.name}</h4>
              {g.description && <p className="desc">{g.description}</p>}
              <p className="meta">
                {g.claims} claim{g.claims === 1 ? '' : 's'} ·{' '}
                {g.active ? 'in shop' : 'hidden'}
              </p>
              <div className="btn-row">
                <button className="btn-ghost small" onClick={() => openEdit(g)}>
                  Edit
                </button>
                <button
                  className="btn-ghost small"
                  onClick={() => toggleActive(g)}
                >
                  {g.active ? 'Hide' : 'Show'}
                </button>
                <button
                  className="btn-ghost small danger"
                  onClick={() => remove(g)}
                >
                  Delete
                </button>
              </div>
            </div>
          </div>
        ))}
        {list.length === 0 && <p className="empty">No rewards yet.</p>}
      </div>
    </div>
  )
}
