// Üst menü: kullanıcı rolüne göre farklı bağlantılar gösterir
import { features } from '../api/api.js'

export default function Header({ user, page, go, onLogout }) {
  const studentLinks = [
    { id: 'courses', label: 'Dersler' },
    { id: 'map', label: 'Öğrenme Haritam' },
    { id: 'study', label: 'Çalış & Asistan' },
  ]
  const linksByRole = {
    student: studentLinks,
    instructor: [{ id: 'instructor', label: 'Akademisyen Paneli' }],
    admin: [{ id: 'admin', label: 'Kullanıcı Yönetimi' }],
  }
  const links = linksByRole[user.role] || studentLinks

  return (
    <header className="topbar">
      <div className="brand" onClick={() => go(links[0].id)}>
        <span className="logo" aria-hidden="true" /> StudyGraph AI
      </div>
      <nav>
        {links.map((l) => (
          <button
            key={l.id}
            type="button"
            className={`navlink ${page === l.id ? 'active' : ''}`}
            onClick={() => go(l.id)}
          >
            {l.label}
          </button>
        ))}
      </nav>
      <div className="user">
        {features.mode === 'demo' && (
          <span className="tag mode-demo" title="Örnek veriyle çalışıyor. Canlı backend için: npm run dev:canli">
            Demo
          </span>
        )}
        <span className="muted">{user.name}</span>
        <button type="button" className="btn ghost small" onClick={onLogout}>
          Çıkış
        </button>
      </div>
    </header>
  )
}
