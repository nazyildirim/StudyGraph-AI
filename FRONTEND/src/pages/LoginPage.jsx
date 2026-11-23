// GİRİŞ EKRANI: e-posta, şifre ve rol seçimi
import { useState } from 'react'
import { login } from '../api/api.js'

export default function LoginPage({ onLogin }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [role, setRole] = useState('student')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const user = await login(email, password, role)
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

        <form onSubmit={handleSubmit}>
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

          <label>
            E-posta
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="ornek@universite.edu.tr" />
          </label>
          <label>
            Şifre
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="••••••" />
          </label>

          {error && <p className="error">{error}</p>}

          <button type="submit" className="btn primary full" disabled={loading}>
            {loading ? 'Giriş yapılıyor…' : 'Giriş yap'}
          </button>
          <p className="hint">Demo modu: herhangi bir e-posta ve şifre ile giriş yapabilirsin.</p>
        </form>
      </div>
    </div>
  )
}
