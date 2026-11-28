// DERS NOTLARI: yapay zekâ asistanının kaynak olarak kullandığı notlar
// Canlı modda PDF/TXT dosyası yüklenebilir; backend dosyayı parçalara böler.
import { useEffect, useRef, useState } from 'react'
import { addMaterial, deleteMaterial, features, getMaterials, getOutcomes, uploadMaterial } from '../../api/api.js'

const emptyForm = { title: '', page: 1, outcomeId: '', text: '' }

export default function MaterialManager({ course, onChanged }) {
  const [outcomes, setOutcomes] = useState([])
  const [materials, setMaterials] = useState(null)
  const [form, setForm] = useState(emptyForm)
  const [source, setSource] = useState(features.materialUpload ? 'file' : 'text') // 'file' | 'text'
  const [file, setFile] = useState(null)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState(null)
  const fileInput = useRef(null)

  useEffect(() => {
    getOutcomes(course.id).then(setOutcomes).catch(() => setOutcomes([]))
    getMaterials(course.id)
      .then(setMaterials)
      .catch((err) => {
        setMaterials([])
        setMsg({ ok: false, text: err.message })
      })
  }, [course.id])

  async function submit(e) {
    e.preventDefault()
    setMsg(null)
    setBusy(true)
    try {
      if (source === 'file') {
        const list = await uploadMaterial(course.id, { file, title: form.title, outcomeId: form.outcomeId })
        setMaterials(list)
        const up = list.lastUpload
        setMsg(
          up?.status === 'failed'
            ? { ok: false, text: `Dosya kaydedildi ama işlenemedi: ${up.error || 'bilinmeyen hata'}` }
            : { ok: true, text: 'Dosya yüklendi ve işlendi. Asistan artık bu notu kaynak olarak kullanabilir.' },
        )
        setFile(null)
        if (fileInput.current) fileInput.current.value = ''
        setForm({ ...emptyForm, outcomeId: form.outcomeId })
      } else {
        setMaterials(await addMaterial(course.id, form))
        setForm({ ...emptyForm, title: form.title, page: Number(form.page) + 1, outcomeId: form.outcomeId })
        setMsg({ ok: true, text: 'Not eklendi. Asistan artık bu notu kaynak olarak kullanabilir.' })
      }
      onChanged()
    } catch (err) {
      setMsg({ ok: false, text: err.message })
    } finally {
      setBusy(false)
    }
  }

  async function remove(id) {
    setMsg(null)
    try {
      setMaterials(await deleteMaterial(course.id, id))
      onChanged()
    } catch (err) {
      setMsg({ ok: false, text: err.message })
    }
  }

  if (!materials) return <p className="muted">Yükleniyor…</p>
  const byId = Object.fromEntries(outcomes.map((o) => [o.id, o]))

  return (
    <div className="two-col wide-right">
      <form className="card" onSubmit={submit}>
        <h3>Ders notu ekle</h3>

        {features.materialUpload ? (
          <div className="segmented" style={{ gridTemplateColumns: '1fr 1fr' }}>
            <button type="button" className={source === 'file' ? 'active' : ''} onClick={() => setSource('file')}>
              Dosya yükle
            </button>
            <button type="button" className={source === 'text' ? 'active' : ''} onClick={() => setSource('text')}>
              Metin yapıştır
            </button>
          </div>
        ) : (
          <p className="muted small">Demo modunda not metni buraya yapıştırılır. Canlı modda PDF/TXT dosyası da yüklenebilir.</p>
        )}

        <label>
          Başlık{source === 'file' ? ' (boş bırakılırsa dosya adı kullanılır)' : ''}
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
          {source === 'text' && (
            <label className="page-input">
              Sayfa
              <input type="number" min="1" value={form.page} onChange={(e) => setForm({ ...form, page: e.target.value })} />
            </label>
          )}
        </div>

        {source === 'file' ? (
          <label>
            Dosya (PDF ya da TXT, en fazla 10 MB)
            <input
              ref={fileInput}
              type="file"
              accept=".pdf,.txt,application/pdf,text/plain"
              onChange={(e) => setFile(e.target.files?.[0] || null)}
            />
          </label>
        ) : (
          <label>
            Not metni
            <textarea rows={6} value={form.text} onChange={(e) => setForm({ ...form, text: e.target.value })} />
          </label>
        )}

        {msg && <p className={msg.ok ? 'success' : 'error'}>{msg.text}</p>}
        <button type="submit" className="btn primary" disabled={busy || (source === 'file' && !file)}>
          {busy ? 'İşleniyor… (büyük dosyalarda biraz sürebilir)' : source === 'file' ? 'Dosyayı yükle' : 'Notu ekle'}
        </button>
      </form>

      <div className="card">
        <h3>Yüklenen notlar ({materials.length})</h3>
        {materials.length === 0 && <p className="muted">Henüz not yok.</p>}
        <ul className="list">
          {materials.map((m) => (
            <li key={m.id}>
              <div>
                <b>{m.title}</b>{' '}
                <span className="muted small">
                  {m.pageCount ? `· ${m.pageCount} sayfa` : m.page ? `· s. ${m.page}` : ''}
                  {m.fileType ? ` · ${m.fileType === 'application/pdf' ? 'PDF' : 'Metin'}` : ''}
                </span>{' '}
                {m.outcomeId && byId[m.outcomeId] && <span className="tag accent">{byId[m.outcomeId].name}</span>}{' '}
                {m.status && <span className={`tag status-${m.status}`}>{m.statusLabel}</span>}
                {m.error && <div className="error small">{m.error}</div>}
                {m.text && <div className="muted small clamp">{m.text}</div>}
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
