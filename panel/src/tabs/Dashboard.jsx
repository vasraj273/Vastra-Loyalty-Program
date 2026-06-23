import { useEffect, useMemo, useState } from 'react'
import { get } from '../api.js'
import IndiaMap from '../components/IndiaMap.jsx'
import BarChart from '../components/BarChart.jsx'

const fmt = (n) => (n ?? 0).toLocaleString('en-IN')
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

export default function Dashboard() {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [year, setYear] = useState(null)

  useEffect(() => {
    get('/analytics/dashboard').then(setData).catch((e) => setError(e.message))
  }, [])

  const by_month = data?.by_month ?? []

  // Years present in the data, newest first; default the selector to the latest.
  const years = useMemo(() => {
    const set = new Set(by_month.map((m) => m.month.slice(0, 4)))
    return [...set].sort().reverse()
  }, [by_month])

  useEffect(() => {
    if (years.length && (year === null || !years.includes(year))) setYear(years[0])
  }, [years, year])

  // 12 rows (Jan–Dec) for the selected year, zero-filled for missing months.
  const monthly = useMemo(() => {
    const byKey = Object.fromEntries(by_month.map((m) => [m.month, m]))
    return MONTHS.map((label, i) => {
      const key = `${year}-${String(i + 1).padStart(2, '0')}`
      const row = byKey[key] || {}
      return { label, generated: row.generated || 0, scanned: row.scanned || 0 }
    })
  }, [by_month, year])

  // Totals for the selected year, so the bars reconcile to a number on the card.
  const yearGen = monthly.reduce((s, m) => s + m.generated, 0)
  const yearScan = monthly.reduce((s, m) => s + m.scanned, 0)

  if (error) return <p className="error">Failed to load dashboard: {error}</p>
  if (!data) return <p className="loading">Loading…</p>

  const { totals, by_region, by_product, top_retailers, map_points,
          by_distributor = [] } = data

  return (
    <div className="dashboard">
      <section className="stat-row">
        <article className="stat-card reveal" style={{ '--d': '0ms' }}>
          <span className="stat-label">Retailers</span>
          <span className="stat-value">{fmt(totals.retailers)}</span>
        </article>
        <article className="stat-card reveal" style={{ '--d': '60ms' }}>
          <span className="stat-label">Products</span>
          <span className="stat-value">{fmt(totals.products)}</span>
        </article>
        <article className="stat-card reveal" style={{ '--d': '120ms' }}>
          <span className="stat-label">Codes issued</span>
          <span className="stat-value">{fmt(totals.codes_issued)}</span>
        </article>
        <article className="stat-card reveal" style={{ '--d': '180ms' }}>
          <span className="stat-label">Codes scanned</span>
          <span className="stat-value">{fmt(totals.scans)}</span>
        </article>
        <article className="stat-card reveal accent" style={{ '--d': '240ms' }}>
          <span className="stat-label">Points awarded</span>
          <span className="stat-value">{fmt(totals.points_awarded)}</span>
        </article>
      </section>

      <section className="stat-row stat-row-3">
        <article className="stat-card reveal" style={{ '--d': '0ms' }}>
          <span className="stat-label">Redeem requests</span>
          <span className="stat-value">{fmt(totals.redeem_total)}</span>
        </article>
        <article className="stat-card reveal accent-gold" style={{ '--d': '60ms' }}>
          <span className="stat-label">Pending requests</span>
          <span className="stat-value">{fmt(totals.redeem_pending)}</span>
        </article>
        <article className="stat-card reveal accent-leaf" style={{ '--d': '120ms' }}>
          <span className="stat-label">Approved requests</span>
          <span className="stat-value">{fmt(totals.redeem_approved)}</span>
        </article>
      </section>

      <section className="map-section">
        <div className="panel-card map-card">
          <h2>Scan activity across India</h2>
          <p className="hint">One dot per scanning retailer — hover for detail.</p>
          <IndiaMap points={map_points} />
        </div>
        <div className="panel-card region-card">
          <h2>Region-wise</h2>
          <table className="data-table">
            <thead>
              <tr><th>Region</th><th className="num">Scans</th><th className="num">Points</th></tr>
            </thead>
            <tbody>
              {by_region.map((r) => (
                <tr key={r.region}>
                  <td>{r.region}</td>
                  <td className="num">{fmt(r.scans)}</td>
                  <td className="num">{fmt(r.points)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="two-col">
        <div className="panel-card">
          <h2>Products</h2>
          <table className="data-table">
            <thead>
              <tr><th>Product</th><th>SKU</th><th className="num">Scans</th><th className="num">Points</th></tr>
            </thead>
            <tbody>
              {by_product.map((p) => (
                <tr key={p.id}>
                  <td>{p.name}</td>
                  <td className="mono">{p.sku}</td>
                  <td className="num">{fmt(p.scans)}</td>
                  <td className="num">{fmt(p.points)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="panel-card">
          <h2>Top retailers</h2>
          <table className="data-table">
            <thead>
              <tr><th>Shop</th><th>Region</th><th className="num">Scans</th><th className="num">Points</th></tr>
            </thead>
            <tbody>
              {top_retailers.map((r) => (
                <tr key={r.id}>
                  <td>
                    {r.shop_name}
                    <span className="sub"> · {r.name}</span>
                  </td>
                  <td>{r.region}</td>
                  <td className="num">{fmt(r.scans)}</td>
                  <td className="num">{fmt(r.points)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section>
        <div className="panel-card">
          <h2>By distributor</h2>
          <p className="hint">
            Which distributor is moving your goods. Totals are the connected
            retailers' own scans and points — distributors hold no points
            themselves.
          </p>
          <table className="data-table">
            <thead>
              <tr>
                <th>Distributor</th>
                <th className="num">Retailers</th>
                <th className="num">Retailer scans</th>
                <th className="num">Retailer points</th>
              </tr>
            </thead>
            <tbody>
              {by_distributor.map((d) => (
                <tr key={d.id}>
                  <td>{d.name}</td>
                  <td className="num">{fmt(d.retailers)}</td>
                  <td className="num">{fmt(d.scans)}</td>
                  <td className="num">{fmt(d.points)}</td>
                </tr>
              ))}
              {by_distributor.length === 0 && (
                <tr>
                  <td colSpan="4" className="empty">
                    No distributors yet — add them in the Distributors tab or via
                    CSV import.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      <section className="chart-section">
        <div className="chart-head">
          <h2>QR analytics</h2>
          {years.length > 0 && (
            <label className="chart-toolbar">
              Year
              <select value={year ?? ''} onChange={(e) => setYear(e.target.value)}>
                {years.map((y) => (
                  <option key={y} value={y}>{y}</option>
                ))}
              </select>
            </label>
          )}
        </div>

        {by_month.length === 0 ? (
          <div className="panel-card">
            <p className="empty">No QR codes generated yet — generate codes in the
              Vastra app to see monthly trends here.</p>
          </div>
        ) : (
          <div className="chart-grid">
            <div className="panel-card chart-card">
              <h3>Month-wise QR generation</h3>
              <p className="hint">
                {year} total: <strong>{fmt(yearGen)}</strong> codes generated.
              </p>
              <BarChart
                data={monthly.map((m) => ({ label: m.label, values: [m.generated] }))}
                series={[{ name: 'Generated', color: '#e07b39' }]}
                showValues
              />
            </div>
            <div className="panel-card chart-card">
              <h3>Generated vs scanned</h3>
              <p className="hint">
                {year}: <strong>{fmt(yearGen)}</strong> generated ·{' '}
                <strong>{fmt(yearScan)}</strong> scanned.
              </p>
              <div className="chart-legend">
                <span><i style={{ background: '#2b3468' }} /> Generated</span>
                <span><i style={{ background: '#c8472b' }} /> Scanned</span>
              </div>
              <BarChart
                data={monthly.map((m) => ({
                  label: m.label, values: [m.generated, m.scanned],
                }))}
                series={[
                  { name: 'Generated', color: '#2b3468' },
                  { name: 'Scanned', color: '#c8472b' },
                ]}
              />
            </div>
          </div>
        )}
      </section>
    </div>
  )
}
