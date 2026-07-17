import { useState } from 'react'
import { post, setSession } from './api.js'
import vastraLogo from './assets/vastra-logo.png'

export default function Login({ onLogin }) {
  const [mode, setMode] = useState('password') // 'password' | 'otp'
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [mobile, setMobile] = useState('')
  const [otp, setOtp] = useState('')
  const [otpSent, setOtpSent] = useState(false)
  const [info, setInfo] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  const finish = (out) => {
    const user = {
      display_name: out.display_name,
      username: out.username,
      is_admin: out.is_admin,
    }
    setSession(out.token, user)
    onLogin(user)
  }

  const submitPassword = async (e) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      finish(await post('/auth/login', { username, password }))
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const sendOtp = async (isResend = 0) => {
    setBusy(true)
    setError(null)
    setInfo(null)
    try {
      const out = await post('/auth/vastra/send-otp', {
        mobile: mobile.trim(),
        is_resend: isResend,
      })
      setOtpSent(true)
      setInfo(out.message)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const submitOtp = async (e) => {
    e.preventDefault()
    if (!otpSent) return sendOtp(0)
    setBusy(true)
    setError(null)
    try {
      finish(await post('/auth/vastra/verify-otp', {
        mobile: mobile.trim(),
        otp: otp.trim(),
      }))
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const switchMode = (m) => {
    setMode(m)
    setError(null)
    setInfo(null)
    setOtpSent(false)
    setOtp('')
  }

  return (
    <div className="login-screen">
      <form
        className="panel-card login-card"
        onSubmit={mode === 'password' ? submitPassword : submitOtp}
      >
        <img className="brand-logo login-logo" src={vastraLogo} alt="Vastra" />
        <h1>Loyalty Panel</h1>
        <p className="login-sub">Manufacturer &amp; super-admin access</p>
        {mode === 'password' ? (
          <>
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
          </>
        ) : (
          <>
            <label>
              Registered mobile number
              <input
                required
                autoFocus
                inputMode="numeric"
                placeholder="10-digit Vastra mobile"
                value={mobile}
                onChange={(e) => setMobile(e.target.value)}
                disabled={otpSent}
                autoComplete="tel-national"
              />
            </label>
            {otpSent && (
              <label>
                OTP
                <input
                  required
                  autoFocus
                  inputMode="numeric"
                  placeholder="Code from SMS"
                  value={otp}
                  onChange={(e) => setOtp(e.target.value)}
                  autoComplete="one-time-code"
                />
              </label>
            )}
            {info && <p className="login-sub">{info}</p>}
          </>
        )}
        {error && <p className="error">{error}</p>}
        <button className="btn-primary" disabled={busy}>
          {busy
            ? 'Please wait…'
            : mode === 'password'
              ? 'Log in'
              : otpSent
                ? 'Verify & log in'
                : 'Send OTP'}
        </button>
        <p className="login-sub">
          {mode === 'password' ? (
            <a href="#otp" onClick={(e) => { e.preventDefault(); switchMode('otp') }}>
              Log in with Vastra OTP instead
            </a>
          ) : (
            <>
              {otpSent && (
                <>
                  <a href="#resend" onClick={(e) => { e.preventDefault(); sendOtp(1) }}>
                    Resend OTP
                  </a>
                  {' · '}
                </>
              )}
              <a href="#pw" onClick={(e) => { e.preventDefault(); switchMode('password') }}>
                Use username &amp; password
              </a>
            </>
          )}
        </p>
      </form>
    </div>
  )
}
