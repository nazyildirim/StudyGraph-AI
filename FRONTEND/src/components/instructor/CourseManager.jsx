// DERS YÖNETİMİ: yeni ders ekleme ve ders listesi
import { useState } from 'react'
import { createCourse, deleteCourse } from '../../api/api.js'

const empty = { code: '', name: '', description: '' }

export default function CourseManager({ courses, onChanged, onOpen }) {
  const [form, setForm] = useState(empty)
  const [msg, setMsg] = useState(null)

  async function submit(e) {
    e.preventDefault()
    setMsg(null)
    try {
      const c = await createCourse(form)
      setForm(empty)
      setMsg({ ok: true, text: `"${c.name}" dersi eklendi. Şimdi kazanımlarını tanımla.` })
      await onChanged()
    } catch (err) {
      setMsg({ ok: false, text: err.message })
    }
  }

  async function remove(c) {
    if (!window.confirm(`"${c.name}" dersi ve tüm kazanım, soru ve notları silinsin mi?`)) return
    await deleteCourse(c.id)
    await onChanged()
  }

  return (
    <div className="two-col">
      <form className="card" onSubmit={submit}>
        <h3>Yeni ders ekle</h3>
        <label>
          Ders kodu
          <input value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} placeholder="BİM301" />
        </label>
        <label>
          Ders adı
          <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="İşletim Sistemleri" />
        </label>
        <label>
          Kısa açıklama
          <input
            value={form.description}
            onChange={(e) => setForm({ ...form, description: e.target.value })}
            placeholder="Süreçler, iş parçacıkları, zamanlama…"
          />
        </label>
        {msg && <p className={msg.ok ? 'success' : 'error'}>{msg.text}</p>}
        <button type="submit" className="btn primary">
          Dersi ekle
        </button>
        <p className="muted small">
          Ders, en az bir kazanım ve bir başlangıç sınavı sorusu eklenince öğrencilere açılır.
        </p>
      </form>

      <div className="card">
        <h3>Derslerim</h3>
        {courses.length === 0 && <p className="muted">Henüz ders yok.</p>}
        <ul className="list">
          {courses.map((c) => (
            <li key={c.id}>
              <div>
                <span className="tag">{c.code}</span> <b>{c.name}</b>
                <div className="muted small">
                  {c.outcomeCount} kazanım · {c.questionCount} soru · {c.materialCount} not ·{' '}
                  <span className={c.active ? 'success' : 'warn'}>{c.active ? 'Öğrencilere açık' : 'Hazırlanıyor'}</span>
                </div>
              </div>
              <div className="row tight">
                <button type="button" className="btn small" onClick={() => onOpen(c.id, 'outcomes')}>
                  Düzenle
                </button>
                <button type="button" className="btn small ghost danger" onClick={() => remove(c)}>
                  Sil
                </button>
              </div>
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}
