// ------------------------------------------------------------
// ÖĞRENME HARİTASI (renkli ön koşul grafiği)
// Her kutu bir kazanım, oklar "önce bunu öğren" ilişkisi.
// Renk: yeşil = yeterli, sarı = geliştirilmeli, kırmızı = eksik
// Ek kütüphane kullanmadan SVG ile çizilir.
// ------------------------------------------------------------
import { levelOf, levelLabels } from '../api/learningLogic.js'

const NODE_W = 170
const NODE_H = 64
const GAP_X = 70
const GAP_Y = 40

// Her konunun "derinliği": ön koşulu yoksa 0, varsa en derin ön koşul + 1
function computeDepths(outcomes) {
  const byId = Object.fromEntries(outcomes.map((o) => [o.id, o]))
  const depth = {}
  function d(id) {
    if (depth[id] !== undefined) return depth[id]
    const pre = byId[id].prerequisites
    depth[id] = pre.length === 0 ? 0 : Math.max(...pre.map(d)) + 1
    return depth[id]
  }
  outcomes.forEach((o) => d(o.id))
  return depth
}

export default function LearningGraph({ outcomes, scores, thresholds, recommendedId, onSelect, selectedId }) {
  const depth = computeDepths(outcomes)
  const columns = {}
  outcomes.forEach((o) => {
    const c = depth[o.id]
    columns[c] = columns[c] || []
    columns[c].push(o)
  })
  const colCount = Object.keys(columns).length
  const maxRows = Math.max(...Object.values(columns).map((c) => c.length))
  const width = colCount * NODE_W + (colCount - 1) * GAP_X + 20
  const PAD_Y = 40 // üstte ve altta, sütun atlayan oklar için boşluk
  const height = maxRows * NODE_H + (maxRows - 1) * GAP_Y + 20 + PAD_Y * 2

  // Kutuların konumları
  const pos = {}
  Object.entries(columns).forEach(([c, list]) => {
    const colHeight = list.length * NODE_H + (list.length - 1) * GAP_Y
    const offsetY = (height - colHeight) / 2
    list.forEach((o, i) => {
      pos[o.id] = {
        x: 10 + Number(c) * (NODE_W + GAP_X),
        y: offsetY + i * (NODE_H + GAP_Y),
      }
    })
  })

  return (
    <div className="graph-wrap">
      <svg viewBox={`0 0 ${width} ${height}`} className="graph" role="img" aria-label="Öğrenme haritası">
        <defs>
          <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">
            <path d="M0,0 L10,5 L0,10 z" className="arrow-head" />
          </marker>
        </defs>

        {/* Oklar: ön koşuldan konuya */}
        {outcomes.flatMap((o) =>
          o.prerequisites.map((p) => {
            const from = pos[p]
            const to = pos[o.id]
            const x1 = from.x + NODE_W
            const y1 = from.y + NODE_H / 2
            const x2 = to.x
            const y2 = to.y + NODE_H / 2
            const mid = (x1 + x2) / 2
            // Ok bir sütunu atlıyorsa aradaki kutunun arkasından geçmesin diye
            // grafiğin üstünden ya da altından dolaştırılır.
            const skips = depth[o.id] - depth[p] > 1
            const arcY = y1 < height / 2 ? 4 : height - 4
            const d = skips
              ? `M${x1},${y1} C${x1 + 80},${arcY} ${x2 - 80},${arcY} ${x2 - 2},${y2}`
              : `M${x1},${y1} C${mid},${y1} ${mid},${y2} ${x2 - 2},${y2}`
            return (
              <path
                key={p + '-' + o.id}
                d={d}
                className="edge"
                markerEnd="url(#arrow)"
              />
            )
          }),
        )}

        {/* Kutular: kazanımlar */}
        {outcomes.map((o) => {
          const p = pos[o.id]
          const level = levelOf(scores[o.id], thresholds)
          const isRec = o.id === recommendedId
          const isSel = o.id === selectedId
          return (
            <g
              key={o.id}
              transform={`translate(${p.x},${p.y})`}
              className={`node level-${level} ${isRec ? 'recommended' : ''} ${isSel ? 'selected' : ''}`}
              onClick={() => onSelect && onSelect(o)}
              tabIndex={0}
              onKeyDown={(e) => e.key === 'Enter' && onSelect && onSelect(o)}
            >
              <rect width={NODE_W} height={NODE_H} rx="12" />
              <text x={NODE_W / 2} y={26} textAnchor="middle" className="node-title">
                {o.name}
              </text>
              <text x={NODE_W / 2} y={46} textAnchor="middle" className="node-score">
                {scores[o.id] !== undefined ? `%${scores[o.id]} · ${levelLabels[level]}` : levelLabels.unknown}
              </text>
            </g>
          )
        })}
      </svg>

      <div className="legend">
        <span><i className="dot level-sufficient" /> Yeterli (≥ %{thresholds.sufficient})</span>
        <span><i className="dot level-developing" /> Geliştirilmeli (≥ %{thresholds.developing})</span>
        <span><i className="dot level-missing" /> Eksik</span>
        <span><i className="dot recommended-dot" /> Önerilen konu</span>
      </div>
    </div>
  )
}
