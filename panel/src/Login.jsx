import { useState } from 'react'
import { post, setSession } from './api.js'
import vastraLogo from './assets/vastra-logo.png'

// Access is Vastra mobile + OTP only. The password endpoint still exists on the
// API, but the panel no longer offers it as a way in.
export default function Login({ onLogin }) {
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

  const submit = async (e) => {
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

  const changeNumber = () => {
    setOtpSent(false)
    setOtp('')
    setInfo(null)
    setError(null)
  }

  return (
    <div className="login-screen">
      <div className="login-bg" aria-hidden="true">
        <div className="login-orb orb-1" />
        <div className="login-orb orb-2" />
        <div className="login-wave wave-1" />
        <div className="login-wave wave-2" />
        <div className="login-wave wave-3" />
        <div className="login-wave-lines" />
        <div className="login-dots" />
      </div>

      <form className="login-card" onSubmit={submit}>
        <img className="brand-logo login-logo" src={vastraLogo} alt="Vastra" />
        <h1>Loyalty Panel</h1>

        <div className="login-icon" aria-hidden="true">
          <svg viewBox="0 0 48 48" fill="none" stroke="currentColor" strokeWidth="2.2">
            <circle cx="18" cy="15" r="7" />
            <path d="M6 35c1.7-7 6-10 12-10s10.3 3 12 10" />
            <path d="M31 24l7 3v6c0 5-3 8-7 10-4-2-7-5-7-10v-6l7-3z" />
            <path d="M28.5 33l2 2 4-4" />
          </svg>
        </div>

        <label className="login-field" htmlFor="login-mobile">
          <span className="login-label">Registered mobile number</span>
          <span className="login-input-wrap">
            <svg
              className="login-input-icon"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              aria-hidden="true"
            >
              <rect x="7" y="3" width="10" height="18" rx="2" />
              <path d="M10 6h4" />
              <circle cx="12" cy="18" r=".8" fill="currentColor" />
            </svg>
            <input
              id="login-mobile"
              required
              autoFocus
              type="tel"
              inputMode="numeric"
              maxLength={10}
              autoComplete="tel-national"
              placeholder="Enter 10-digit Vastra mobile number"
              value={mobile}
              onChange={(e) => setMobile(e.target.value.replace(/\D/g, '').slice(0, 10))}
              disabled={otpSent}
            />
          </span>
        </label>

        {otpSent && (
          <label className="login-field" htmlFor="login-otp">
            <span className="login-label">One-time password</span>
            <span className="login-input-wrap">
              <svg
                className="login-input-icon"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.8"
                aria-hidden="true"
              >
                <rect x="4" y="10" width="16" height="10" rx="2" />
                <path d="M8 10V7a4 4 0 0 1 8 0v3" />
              </svg>
              <input
                id="login-otp"
                required
                autoFocus
                inputMode="numeric"
                autoComplete="one-time-code"
                placeholder="Code from SMS"
                value={otp}
                onChange={(e) => setOtp(e.target.value)}
              />
            </span>
          </label>
        )}

        {info && <p className="login-info">{info}</p>}
        {error && <p className="error">{error}</p>}

        <button className="login-submit" disabled={busy}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" aria-hidden="true">
            <path d="M12 3l8 3v6c0 5-3.4 8-8 9-4.6-1-8-4-8-9V6l8-3z" />
            <path d="M8.5 12l2.2 2.2 4.8-5" />
          </svg>
          {busy ? 'Please wait…' : otpSent ? 'Verify & log in' : 'Send OTP'}
        </button>

        {otpSent && (
          <p className="login-links">
            <a href="#resend" onClick={(e) => { e.preventDefault(); sendOtp(1) }}>
              Resend OTP
            </a>
            {' · '}
            <a href="#change" onClick={(e) => { e.preventDefault(); changeNumber() }}>
              Change number
            </a>
          </p>
        )}

        <p className="login-note">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
            <path d="M12 3l8 3v6c0 5-3.4 8-8 9-4.6-1-8-4-8-9V6l8-3z" />
            <path d="M8.5 12l2.2 2.2 4.8-5" />
          </svg>
          Secure access · OTP verification
        </p>
      </form>
    </div>
  )
}
