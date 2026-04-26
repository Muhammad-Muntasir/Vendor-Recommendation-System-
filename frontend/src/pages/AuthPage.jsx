import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth.js'
import { confirmRegistration, resendConfirmationCode } from '../services/auth.js'

export default function AuthPage() {
  const [tab, setTab] = useState('login')
  const { login, register } = useAuth()
  const navigate = useNavigate()

  return (
    <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: '#f5f5f5' }}>
      <div style={{ background: '#fff', borderRadius: '10px', boxShadow: '0 4px 20px rgba(0,0,0,0.1)', padding: '2rem', width: '100%', maxWidth: '420px' }}>
        <h1 style={{ textAlign: 'center', color: '#e94560', marginBottom: '1.5rem', fontSize: '1.5rem' }}>RetailFixIt AI-VRS</h1>

        {/* Tabs */}
        <div style={{ display: 'flex', borderBottom: '2px solid #e2e8f0', marginBottom: '1.5rem' }}>
          {['login', 'register'].map(t => (
            <button key={t} onClick={() => setTab(t)}
              style={{ flex: 1, padding: '0.6rem', border: 'none', background: 'none', cursor: 'pointer', fontWeight: tab === t ? 700 : 400, color: tab === t ? '#e94560' : '#6b7280', borderBottom: tab === t ? '2px solid #e94560' : '2px solid transparent', marginBottom: '-2px', textTransform: 'capitalize', fontSize: '0.95rem' }}>
              {t === 'login' ? 'Login' : 'Register'}
            </button>
          ))}
        </div>

        {tab === 'login'
          ? <LoginForm login={login} navigate={navigate} />
          : <RegisterForm register={register} />}
      </div>
    </div>
  )
}

// ── Login Form ────────────────────────────────────────────────────────────────

function LoginForm({ login, navigate }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      await login(email, password)
      navigate('/dashboard')
    } catch (err) {
      setError(err.message || 'Invalid credentials. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <form onSubmit={handleSubmit}>
      {error && <ErrorBox message={error} />}
      <label style={labelStyle}>Email</label>
      <input type="email" value={email} onChange={e => setEmail(e.target.value)} required
        autoComplete="email" style={inputStyle} placeholder="admin@retailfixit.com" />
      <label style={labelStyle}>Password</label>
      <input type="password" value={password} onChange={e => setPassword(e.target.value)} required
        autoComplete="current-password" style={inputStyle} placeholder="••••••••" />
      <button type="submit" disabled={loading} style={btnStyle(loading)}>
        {loading ? 'Signing in…' : 'Sign In'}
      </button>
    </form>
  )
}

// ── Register Form (3 steps) ───────────────────────────────────────────────────
// Step 1: Enter email + password → Cognito sends verification code to email
// Step 2: Enter the 6-digit code from the email → account confirmed
// Step 3: Success — user can now log in

function RegisterForm({ register }) {
  const [step, setStep] = useState('form')   // 'form' | 'verify' | 'done'
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [code, setCode] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [resent, setResent] = useState(false)

  // Step 1: Register → triggers Cognito to send verification email
  async function handleRegister(e) {
    e.preventDefault()
    setError('')
    if (password !== confirm) { setError('Passwords do not match.'); return }
    setLoading(true)
    try {
      await register(email, password)
      setStep('verify')  // Move to code entry step
    } catch (err) {
      const msg = err.message || ''
      if (msg.includes('already') || msg.includes('exists')) {
        // Account exists but may be unconfirmed — go straight to verify step
        setStep('verify')
      } else {
        setError(msg || 'Registration failed.')
      }
    } finally {
      setLoading(false)
    }
  }

  // Step 2: Confirm with the 6-digit code from email
  async function handleVerify(e) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      await confirmRegistration(email, code.trim())
      setStep('done')  // Account confirmed!
    } catch (err) {
      setError(err.message || 'Invalid code. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  // Resend the verification code
  async function handleResend() {
    setError('')
    setResent(false)
    try {
      await resendConfirmationCode(email)
      setResent(true)
    } catch (err) {
      setError(err.message || 'Failed to resend code.')
    }
  }

  // ── Step 1: Registration form ─────────────────────────────────────────────
  if (step === 'form') return (
    <form onSubmit={handleRegister}>
      {error && <ErrorBox message={error} />}
      <label style={labelStyle}>Email</label>
      <input type="email" value={email} onChange={e => setEmail(e.target.value)} required
        style={inputStyle} placeholder="admin@retailfixit.com" />
      <label style={labelStyle}>Password</label>
      <input type="password" value={password} onChange={e => setPassword(e.target.value)} required
        style={inputStyle} placeholder="Min 8 chars, upper, lower, digit, special" />
      <label style={labelStyle}>Confirm Password</label>
      <input type="password" value={confirm} onChange={e => setConfirm(e.target.value)} required
        style={inputStyle} placeholder="••••••••" />
      <button type="submit" disabled={loading} style={btnStyle(loading)}>
        {loading ? 'Creating account…' : 'Create Account'}
      </button>
    </form>
  )

  // ── Step 2: Verification code entry ──────────────────────────────────────
  if (step === 'verify') return (
    <form onSubmit={handleVerify}>
      {/* Info box explaining what to do */}
      <div style={{ background: '#eff6ff', border: '1px solid #93c5fd', borderRadius: '6px', padding: '0.75rem 1rem', marginBottom: '1rem', fontSize: '0.9rem', color: '#1e40af' }}>
        📧 A 6-digit verification code was sent to <strong>{email}</strong>.
        Check your inbox (and spam folder) and enter the code below.
      </div>

      {error && <ErrorBox message={error} />}
      {resent && <div style={{ background: '#f0fdf4', border: '1px solid #86efac', borderRadius: '4px', padding: '0.5rem 0.8rem', color: '#16a34a', marginBottom: '0.75rem', fontSize: '0.85rem' }}>✓ New code sent to {email}</div>}

      <label style={labelStyle}>Verification Code</label>
      <input
        type="text"
        value={code}
        onChange={e => setCode(e.target.value)}
        required
        maxLength={6}
        style={{ ...inputStyle, fontSize: '1.5rem', letterSpacing: '0.5rem', textAlign: 'center' }}
        placeholder="123456"
        autoFocus
        autoComplete="one-time-code"
      />

      <button type="submit" disabled={loading || code.trim().length < 6} style={btnStyle(loading || code.trim().length < 6)}>
        {loading ? 'Verifying…' : 'Verify Email'}
      </button>

      {/* Resend link */}
      <p style={{ textAlign: 'center', marginTop: '1rem', fontSize: '0.85rem', color: '#6b7280' }}>
        Didn't receive it?{' '}
        <button type="button" onClick={handleResend}
          style={{ background: 'none', border: 'none', color: '#e94560', cursor: 'pointer', fontWeight: 600, fontSize: '0.85rem', padding: 0 }}>
          Resend code
        </button>
      </p>
    </form>
  )

  // ── Step 3: Success ───────────────────────────────────────────────────────
  return (
    <div style={{ textAlign: 'center', padding: '1rem' }}>
      <div style={{ fontSize: '3rem', marginBottom: '0.75rem' }}>✅</div>
      <p style={{ fontWeight: 700, color: '#16a34a', fontSize: '1.1rem', marginBottom: '0.5rem' }}>Email verified!</p>
      <p style={{ fontSize: '0.9rem', color: '#374151', marginBottom: '1.25rem' }}>
        Your account is confirmed. You can now sign in.
      </p>
      {/* Switch to login tab by reloading the page */}
      <button onClick={() => window.location.reload()}
        style={{ ...btnStyle(false), display: 'inline-block', width: 'auto', padding: '0.5rem 1.5rem' }}>
        Go to Login
      </button>
    </div>
  )
}

// ── Shared components ─────────────────────────────────────────────────────────

function ErrorBox({ message }) {
  // Safely convert any error type to a string
  const text = typeof message === 'string'
    ? message
    : message?.response?.data?.error?.message
      || message?.message
      || 'An unexpected error occurred.'

  return (
    <div role="alert" style={{ background: '#fef2f2', border: '1px solid #fca5a5', borderRadius: '4px', padding: '0.6rem 0.8rem', color: '#dc2626', marginBottom: '1rem', fontSize: '0.9rem' }}>
      {text}
    </div>
  )
}

const labelStyle = { display: 'block', fontWeight: 600, fontSize: '0.85rem', color: '#374151', marginBottom: '0.3rem', marginTop: '0.8rem' }
const inputStyle = { width: '100%', padding: '0.5rem 0.75rem', border: '1px solid #d1d5db', borderRadius: '4px', fontSize: '0.95rem', boxSizing: 'border-box', marginBottom: '0.1rem' }
const btnStyle = (disabled) => ({ width: '100%', marginTop: '1.2rem', padding: '0.6rem', background: disabled ? '#9ca3af' : '#e94560', color: '#fff', border: 'none', borderRadius: '4px', fontSize: '1rem', fontWeight: 600, cursor: disabled ? 'not-allowed' : 'pointer' })
