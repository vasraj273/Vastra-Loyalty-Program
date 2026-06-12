import { useState } from 'react'
import { post, setSession } from './api.js'

export default function Login({ onLogin }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  const submit = async (e) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const out = await post('/auth/login', { username, password })
      const user = {
        display_name: out.display_name,
        username: out.username,
        is_admin: out.is_admin,
      }
      setSession(out.token, user)
      onLogin(user)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="login-screen">
      <form className="panel-card login-card" onSubmit={submit}>
        <span className="brand-mark">वस्त्र</span>
        <h1>Loyalty Panel</h1>
        <p className="login-sub">Manufacturer &amp; super-admin access</p>
        <label>
          Username
          <input
            required
            autoFocus
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
          />
        </label>
        <label>
          Password
          <input
            required
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
          />
        </label>
        {error && <p className="error">{error}</p>}
        <button className="btn-primary" disabled={busy}>
          {busy ? 'Logging in…' : 'Log in'}
        </button>
      </form>
    </div>
  )
}
