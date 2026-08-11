import { useCallback, useEffect, useState } from 'react'
import { get, post, del } from '../api.js'
import EmptyState from '../components/EmptyState.jsx'
import { Fab } from '../components/Toolbar.jsx'

const SECTIONS = [
  { status: 'active', title: 'Active now' },
  { status: 'upcoming', title: 'Upcoming' },
  { status: 'previous', title: 'Previous' },
]

const EMPTY_FORM = {
  name: '',
  description: '',
  start_date: '',
  end_date: '',
  bonus_points: 20,
  product_ids: [],
}

export default function Schemes() {
  const [schemes, setSchemes] = useState(null)
  const [products, setProducts] = useState([])
  const [form, setForm] = useState(EMPTY_FORM)
  const [showForm, setShowForm] = useState(false)
  const [error, setError] = useState(null)
  const [saving, setSaving] = useState(false)

  const load = useCallback(() => {
    get('/schemes').then(setSchemes).catch((e) => setError(e.message))
    get('/products').then(setProducts).catch(() => {})
  }, [])

  useEffect(load, [load])

  const submit = async (e) => {
    e.preventDefault()
    setSaving(true)
    setError(null)
    try {
      await post('/schemes', { ...form, bonus_points: Number(form.bonus_points) })
      setForm(EMPTY_FORM)
      setShowForm(false)
      load()
    } catch (err) {
      setError(err.message)
    } finally {
      setSaving(false)
    }
  }

  const remove = async (id) => {
    setError(null)
    try {
      await del(`/schemes/${id}`)
      load()
    } catch (err) {
      setError(err.message)
    }
  }

  const toggleProduct = (id) =>
    setForm((f) => ({
      ...f,
      product_ids: f.product_ids.includes(id)
        ? f.product_ids.filter((p) => p !== id)
        : [...f.product_ids, id],
    }))

  if (!schemes) return <p className="loading">Loading…</p>

  return (
    <div className="schemes">
      <div className="schemes-head">
        <h2 className="page-title">Schemes &amp; Campaigns</h2>
      </div>
      {error && <p className="error">{error}</p>}

      {showForm && (
        <form className="panel-card scheme-form" onSubmit={submit}>
          <div className="form-grid">
            <label>
              Name
              <input
                required
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                placeholder="Diwali Dhamaka"
              />
            </label>
            <label>
              Bonus points per scan
              <input
                required
                type="number"
                min="1"
                value={form.bonus_points}
                onChange={(e) =>
                  setForm({ ...form, bonus_points: e.target.value })
                }
              />
            </label>
            <label>
              Starts
              <input
                required
                type="date"
                value={form.start_date}
                onChange={(e) =>
                  setForm({ ...form, start_date: e.target.value })
                }
              />
            </label>
            <label>
              Ends
              <input
                required
                type="date"
                value={form.end_date}
                onChange={(e) => setForm({ ...form, end_date: e.target.value })}
              />
            </label>
          </div>
          <label>
            Description
            <input
              value={form.description}
              onChange={(e) =>
                setForm({ ...form, description: e.target.value })
              }
              placeholder="Bonus points during the festive season"
            />
          </label>
          <fieldset className="product-pick">
            <legend>
              Covered products{' '}
              <span className="sub">(none selected = all products)</span>
            </legend>
            <div className="chips">
              {products.map((p) => (
                <button
                  type="button"
                  key={p.id}
                  className={
                    form.product_ids.includes(p.id) ? 'chip on' : 'chip'
                  }
                  onClick={() => toggleProduct(p.id)}
                >
                  {p.name}
                </button>
              ))}
            </div>
          </fieldset>
          <button className="btn-primary" disabled={saving}>
            {saving ? 'Creating…' : 'Create scheme'}
          </button>
        </form>
      )}

      {schemes.length === 0 && !showForm && (
        <div className="panel-card">
          <EmptyState
            icon="🎯"
            title="No schemes yet"
            message="A scheme adds bonus points on top of a product's base value for a set period. The most generous active scheme wins — bonuses never stack."
            action={
              <button className="btn-primary" onClick={() => setShowForm(true)}>
                + New scheme
              </button>
            }
          />
        </div>
      )}

      {schemes.length > 0 && SECTIONS.map(({ status, title }) => {
        const list = schemes.filter((s) => s.status === status)
        return (
          <section key={status} className={`scheme-section ${status}`}>
            <h3 className="section-title">
              {title} <span className="count">{list.length}</span>
            </h3>
            {list.length === 0 && <p className="empty">None.</p>}
            <div className="scheme-grid">
              {list.map((s) => (
                <article key={s.id} className={`scheme-card ${status}`}>
                  <header>
                    <h4>{s.name}</h4>
                    <span className="bonus">+{s.bonus_points} pts</span>
                  </header>
                  {s.description && <p className="desc">{s.description}</p>}
                  <p className="dates">
                    {s.start_date} → {s.end_date}
                  </p>
                  <p className="coverage">
                    {s.all_products
                      ? 'All products'
                      : s.products.map((p) => p.name).join(', ')}
                  </p>
                  {status === 'upcoming' && (
                    <button
                      className="btn-ghost danger"
                      onClick={() => remove(s.id)}
                    >
                      Delete
                    </button>
                  )}
                </article>
              ))}
            </div>
          </section>
        )
      })}

      <Fab
        label={showForm ? 'Close the new-scheme form' : 'New scheme'}
        close={showForm}
        onClick={() => setShowForm((s) => !s)}
      />
    </div>
  )
}
