import { useCallback, useEffect, useState } from 'react'
import { get, post } from '../api.js'

const EMPTY = { username: '', password: '', display_name: '' }

export default function Manufacturers() {
  const [list, setList] = useState(null)
  const [form, setForm] = useState(EMPTY)
  const [created, setCreated] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback(() => {
    get('/admin/manufacturers').then(setList).catch((e) => setError(e.message))
  }, [])

  useEffect(load, [load])

  const submit = async (e) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    setCreated(null)
    try {
      const out = await post('/admin/manufacturers', form)
      // Show the credentials once so they can be handed to the manufacturer
      setCreated({ ...out, password: form.password })
      setForm(EMPTY)
      load()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  if (!list) return <p className="loading">Loading…</p>

  return (
    <div className="manufacturers">
      <h2 className="page-title">Manufacturer accounts</h2>
      {error && <p className="error">{error}</p>}

      <form className="panel-card scheme-form" onSubmit={submit}>
        <div className="form-grid three">
          <label>
            Company / display name
            <input
              required
              value={form.display_name}
              onChange={(e) =>
                setForm({ ...form, display_name: e.target.value })
              }
              placeholder="Surya Textiles"
            />
          </label>
          <label>
            Login username
            <input
              required
              minLength={3}
              value={form.username}
              onChange={(e) => setForm({ ...form, username: e.target.value })}
              placeholder="surya"
            />
          </label>
          <label>
            Password
            <input
              required
              minLength={6}
              value={form.password}
              onChange={(e) => setForm({ ...form, password: e.target.value })}
              placeholder="min 6 characters"
            />
          </label>
        </div>
        <button className="btn-primary" disabled={busy}>
          {busy ? 'Creating…' : 'Create manufacturer login'}
        </button>
        {created && (
          <p className="created-note">
            Created <strong>{created.display_name}</strong> — hand over these
            credentials: <span className="mono">{created.username}</span> /{' '}
            <span className="mono">{created.password}</span>
          </p>
        )}
      </form>

      <div className="panel-card table-card">
        <table className="data-table">
          <thead>
            <tr>
              <th>Company</th>
              <th>Username</th>
              <th className="num">Products</th>
              <th className="num">Retailers</th>
              <th className="num">Scans</th>
              <th>Created</th>
            </tr>
          </thead>
          <tbody>
            {list.map((m) => (
              <tr key={m.id}>
                <td>{m.display_name}</td>
                <td className="mono">{m.username}</td>
                <td className="num">{m.products}</td>
                <td className="num">{m.retailers}</td>
                <td className="num">{m.scans}</td>
                <td className="mono sub">{m.created_at}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
