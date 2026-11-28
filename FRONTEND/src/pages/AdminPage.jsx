// PLATFORM YÖNETİCİSİ: kullanıcı ekleme, rol değiştirme, hesabı pasif/aktif yapma
import { useEffect, useState } from 'react'
import { addUser, features, getUsers, updateUser } from '../api/api.js'

const roleLabels = { student: 'Öğrenci', instructor: 'Akademisyen', admin: 'Yönetici' }

export default function AdminPage() {
  const [users, setUsers] = useState(null)
  const [filter, setFilter] = useState('')
  const [form, setForm] = useState({ name: '', email: '', role: 'student' })
  const [msg, setMsg] = useState(null)

  useEffect(() => {
    getUsers()
      .then(setUsers)
      .catch((err) => {
        setUsers([])
        setMsg({ ok: false, text: err.message })
      })
  }, [])

  async function run(fn, okText) {
    setMsg(null)
    try {
      setUsers(await fn())
      setMsg({ ok: true, text: okText })
      return true
    } catch (err) {
      setMsg({ ok: false, text: err.message })
      return false
    }
  }

  if (!users) return <p className="muted">Kullanıcılar yükleniyor…</p>

  const shown = users.filter((u) => !filter || u.role === filter)
  const count = (r) => users.filter((u) => u.role === r).length

  return (
    <div>
      <h1>Kullanıcı ve Rol Yönetimi</h1>
      <p className="muted">
        {users.length} kullanıcı · {count('student')} öğrenci · {count('instructor')} akademisyen · {count('admin')} yönetici
      </p>

      <div className="two-col wide-right">
        {features.addUser ? (
        <form
          className="card"
          onSubmit={async (e) => {
            e.preventDefault()
            if (await run(() => addUser(form), `${form.name} eklendi.`)) setForm({ name: '', email: '', role: 'student' })
          }}
        >
          <h3>Yeni kullanıcı</h3>
          <label>
            Ad soyad
            <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          </label>
          <label>
            E-posta
            <input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
          </label>
          <label>
            Rol
            <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
              {Object.entries(roleLabels).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </select>
          </label>
          <button type="submit" className="btn primary">
            Kullanıcı ekle
          </button>
        </form>
        ) : (
          <div className="card">
            <h3>Yeni kullanıcılar</h3>
            <p className="muted">
              Öğrenciler giriş ekranından kendileri kayıt olur ve öğrenci rolüyle başlar. Akademisyen ya da yönetici
              yapmak için listeden rolünü değiştir.
            </p>
          </div>
        )}

        <div className="card">
          <div className="panel-head">
            <h3>Kullanıcılar</h3>
            <select className="auto" value={filter} onChange={(e) => setFilter(e.target.value)}>
              <option value="">Tüm roller</option>
              {Object.entries(roleLabels).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </select>
          </div>
          {msg && <p className={msg.ok ? 'success' : 'error'}>{msg.text}</p>}
          <table className="table users">
            <thead>
              <tr>
                <th>Ad</th>
                <th>Rol</th>
                <th>Durum</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {shown.map((u) => (
                <tr key={u.id} className={u.active ? '' : 'inactive'}>
                  <td>
                    {u.name}
                    <div className="muted small">{u.email}</div>
                  </td>
                  <td>
                    <select
                      className="auto"
                      value={u.role}
                      onChange={(e) =>
                        run(() => updateUser(u.id, { role: e.target.value }), `${u.name}: rol ${roleLabels[e.target.value]} yapıldı.`)
                      }
                    >
                      {Object.entries(roleLabels).map(([k, v]) => (
                        <option key={k} value={k}>
                          {v}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td>
                    <span className={u.active ? 'success' : 'muted'}>{u.active ? 'Aktif' : 'Pasif'}</span>
                  </td>
                  <td>
                    <button
                      type="button"
                      className="btn small ghost"
                      onClick={() =>
                        run(() => updateUser(u.id, { active: !u.active }), `${u.name} ${u.active ? 'pasif' : 'aktif'} yapıldı.`)
                      }
                    >
                      {u.active ? 'Pasif yap' : 'Aktif yap'}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card">
        <h3>Rol ve yetki matrisi</h3>
        <table className="table">
          <thead>
            <tr>
              <th>İşlem</th>
              <th>Öğrenci</th>
              <th>Akademisyen</th>
              <th>Yönetici</th>
            </tr>
          </thead>
          <tbody>
            {[
              ['Sınava girme, kendi haritasını görme', 1, 0, 0],
              ['Yapay zekâ asistanını kullanma', 1, 0, 0],
              ['Ders, kazanım, soru, not yönetimi', 0, 1, 0],
              ['Sınıf raporlarını görme', 0, 1, 0],
              ['Kullanıcı ve rol yönetimi', 0, 0, 1],
            ].map(([action, ...cols]) => (
              <tr key={action}>
                <td>{action}</td>
                {cols.map((c, i) => (
                  <td key={i} className={c ? 'success' : 'muted'}>
                    {c ? 'Evet' : '—'}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        <p className="muted small">Asıl yetki kontrolü sunucu tarafında (backend) yapılır; arayüz yalnızca yetkili menüleri gösterir.</p>
      </div>
    </div>
  )
}
