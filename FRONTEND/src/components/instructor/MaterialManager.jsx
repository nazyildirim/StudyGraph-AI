// DERS NOTLARI: yapay zekâ asistanının kaynak olarak kullandığı notlar
import { useEffect, useState } from 'react'
import { addMaterial, deleteMaterial, getMaterials, getOutcomes, USE_MOCK } from '../../api/api.js'

const emptyForm = { title: '', page: 1, outcomeId: '', text: '' }

export default function MaterialManager({ course, onChanged }) {
  const [outcomes, setOutcomes] = useState([])
  const [materials, setMaterials] = useState(null)
  const [form, setForm] = useState(emptyForm)
  const [msg, setMsg] = useState(null)

  useEffect(() => {
    getOutcomes(course.id).then(setOutcomes)
    getMaterials(course.id).then(setMaterials)
  }, [course.id])

  async function submit(e) {
    e.preventDefault()
    setMsg(null)
    try {
      setMaterials(await addMaterial(course.id, form))
      setForm({ ...emptyForm, title: form.title, page: Number(form.page) + 1, outcomeId: form.outcomeId })
      setMsg({ ok: true, text: 'Not eklendi. Asistan artık bu notu kaynak olarak kullanabilir.' })
      onChanged()
    } catch (err) {
      setMsg({ ok: false, text: err.message })
    }
  }

  async function remove(id) {
    setMaterials(await deleteMaterial(course.id, id))
    onChanged()
  }

  if (!materials) return <p className="muted">Yükleniyor…</p>
  const byId = Object.fromEntries(outcomes.map((o) => [o.id, o]))

  return (
    <div className="two-col wide-right">
      <form className="card" onSubmit={submit}>
        <h3>Ders notu ekle</h3>
        {USE_MOCK && (
          <p className="muted small">
            Demo modunda not metni buraya yapıştırılır. Backend bağlanınca PDF yükleme ve otomatik parçalama 2. kişinin RAG
            servisiyle yapılacak.
          </p>
        )}
        <label>
          Başlık
          <input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} placeholder="Hafta 3 Notları" />
        </label>
        <div className="row tight">
          <label className="grow">
            İlgili kazanım
            <select value={form.outcomeId} onChange={(e) => setForm({ ...form, outcomeId: e.target.value })}>
              <option value="">Genel</option>
              {outcomes.map((o) => (
                <option key={o.id} value={o.id}>
                  {o.name}
                </option>
              ))}
            </select>
          </label>
          <label className="page-input">
            Sayfa
            <input type="number" min="1" value={form.page} onChange={(e) => setForm({ ...form, page: e.target.value })} />
          </label>
        </div>
        <label>
          Not metni
          <textarea rows={6} value={form.text} onChange={(e) => setForm({ ...form, text: e.target.value })} />
        </label>
        {msg && <p className={msg.ok ? 'success' : 'error'}>{msg.text}</p>}
        <button type="submit" className="btn primary">
          Notu ekle
        </button>
      </form>

      <div className="card">
        <h3>Yüklenen notlar ({materials.length})</h3>
        {materials.length === 0 && <p className="muted">Henüz not yok.</p>}
        <ul className="list">
          {materials.map((m) => (
            <li key={m.id}>
              <div>
                <b>{m.title}</b> <span className="muted small">· s. {m.page}</span>
                {m.outcomeId && byId[m.outcomeId] && <span className="tag accent">{byId[m.outcomeId].name}</span>}
                <div className="muted small clamp">{m.text}</div>
              </div>
              <button type="button" className="btn small ghost danger" onClick={() => remove(m.id)}>
                Sil
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}
