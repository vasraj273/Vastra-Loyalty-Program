// Lightweight themed SVG bar chart. Supports one series (single bars) or several
// grouped series per label. No external dependency — colors come from the panel
// theme. The SVG uses a viewBox + width:100% so it always scales to fit the card
// (never overflows) while keeping a tall, readable aspect ratio.

const VB_W = 720
const PAD = { top: 26, right: 14, bottom: 34, left: 50 }

const niceMax = (v) => {
  if (v <= 0) return 1
  const pow = Math.pow(10, Math.floor(Math.log10(v)))
  const n = v / pow
  const step = n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10
  return step * pow
}

const fmt = (n) => (n ?? 0).toLocaleString('en-IN')

export default function BarChart({
  data = [],
  series = [{ name: '', color: '#1d466f' }],
  height = 360,
  showValues = false,
}) {
  const innerW = VB_W - PAD.left - PAD.right
  const innerH = height - PAD.top - PAD.bottom
  const rawMax = Math.max(1, ...data.flatMap((d) => d.values))
  const max = niceMax(rawMax)
  const groupW = innerW / Math.max(1, data.length)
  const nSeries = series.length
  const slot = groupW * 0.6 // share of the group used by bars
  const barW = slot / nSeries
  const x0 = PAD.left + (groupW - slot) / 2

  const y = (v) => PAD.top + innerH * (1 - v / max)
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((t) => Math.round(max * t))

  return (
    <svg
      className="bar-chart"
      viewBox={`0 0 ${VB_W} ${height}`}
      preserveAspectRatio="xMidYMid meet"
      role="img"
    >
      {/* gridlines + y-axis labels */}
      {ticks.map((t, i) => (
        <g key={i}>
          <line
            className="bc-grid"
            x1={PAD.left}
            x2={VB_W - PAD.right}
            y1={y(t)}
            y2={y(t)}
          />
          <text className="bc-ytick" x={PAD.left - 8} y={y(t) + 4}>
            {fmt(t)}
          </text>
        </g>
      ))}

      {data.map((d, gi) => {
        const gx = PAD.left + gi * groupW
        return (
          <g key={d.label}>
            {d.values.map((v, si) => {
              const bx = x0 + gi * groupW + si * barW
              const by = y(v)
              const bh = PAD.top + innerH - by
              return (
                <g key={si}>
                  <rect
                    className="bc-bar"
                    x={bx}
                    y={by}
                    width={Math.max(0, barW - 3)}
                    height={Math.max(0, bh)}
                    rx={3}
                    fill={series[si].color}
                  >
                    <title>{`${d.label} · ${series[si].name || 'value'}: ${fmt(v)}`}</title>
                  </rect>
                  {showValues && v > 0 && (
                    <text
                      className="bc-vlabel"
                      x={bx + (barW - 3) / 2}
                      y={by - 7}
                    >
                      {fmt(v)}
                    </text>
                  )}
                </g>
              )
            })}
            <text
              className="bc-xlabel"
              x={gx + groupW / 2}
              y={height - PAD.bottom + 22}
            >
              {d.label}
            </text>
          </g>
        )
      })}
    </svg>
  )
}
