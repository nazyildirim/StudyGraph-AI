// GİRİŞ EKRANI
// Demo modunda: rol seçilir, herhangi bir e-posta/şifre kabul edilir.
// Canlı modda: rol sunucudan gelir; yeni öğrenciler kayıt olabilir.
import { useState } from 'react'
import { features, login, register } from '../api/api.js'

export default function LoginPage({ onLogin, notice }) {
  const [mode, setMode] = useState('login') // 'login' | 'register'
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [firstName, setFirstName] = useState('')
  const [lastName, setLastName] = useState('')
  const [role, setRole] = useState('student')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const user =
        mode === 'register'
          ? await register({ email, password, firstName, lastName })
          : await login(email, password, role)
      onLogin(user)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="login-page">
      <div className="login-card card">
        <div className="brand big">
          <span className="logo" aria-hidden="true" /> StudyGraph AI
        </div>
        <p className="muted">Eksik kazanımlarını bul, ön koşullarıyla birlikte doğru sırayla çalış.</p>

        {notice && <p className="note">{notice}</p>}

        <form onSubmit={handleSubmit}>
          {features.roleSelect && (
            <div className="role-switch">
              <button type="button" className={role === 'student' ? 'active' : ''} onClick={() => setRole('student')}>
                Öğrenci
              </button>
              <button type="button" className={role === 'instructor' ? 'active' : ''} onClick={() => setRole('instructor')}>
                Akademisyen
              </button>
              <button type="button" className={role === 'admin' ? 'active' : ''} onClick={() => setRole('admin')}>
                Yönetici
              </button>
            </div>
          )}

          {mode === 'register' && (
            <div className="row tight">
              <label className="grow">
                Ad
                <input value={firstName} onChange={(e) => setFirstName(e.target.value)} autoComplete="given-name" />
              </label>
              <label className="grow">
                Soyad
                <input value={lastName} onChange={(e) => setLastName(e.target.value)} autoComplete="family-name" />
              </label>
            </div>
          )}

          <label>
            E-posta
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="ornek@universite.edu.tr"
              autoComplete="email"
            />
          </label>
          <label>
            Şifre
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••"
              autoComplete={mode === 'register' ? 'new-password' : 'current-password'}
            />
          </label>

          {error && <p className="error">{error}</p>}

          <button type="submit" className="btn primary full" disabled={loading}>
            {loading ? 'Bekleniyor…' : mode === 'register' ? 'Kayıt ol' : 'Giriş yap'}
          </button>

          {features.register ? (
            <p className="hint">
              {mode === 'login' ? 'Hesabın yok mu? ' : 'Zaten hesabın var mı? '}
              <button
                type="button"
                className="linklike"
                onClick={() => {
                  setMode(mode === 'login' ? 'register' : 'login')
                  setError('')
                }}
              >
                {mode === 'login' ? 'Öğrenci olarak kayıt ol' : 'Giriş yap'}
              </button>
            </p>
          ) : (
            <p className="hint">Demo modu: herhangi bir e-posta ve şifre ile giriş yapabilirsin.</p>
          )}
        </form>
      </div>
    </div>
  )
}
