import { useEffect, useState } from 'react'
import { get } from '../api.js'
import IndiaMap from '../components/IndiaMap.jsx'

const fmt = (n) => (n ?? 0).toLocaleString('en-IN')

export default function Dashboard() {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    get('/analytics/dashboard').then(setData).catch((e) => setError(e.message))
  }, [])

  if (error) return <p className="error">Failed to load dashboard: {error}</p>
  if (!data) return <p className="loading">Loading…</p>

  const { totals, by_region, by_product, top_retailers, map_points } = data

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
          <span className="stat-label">Scans</span>
          <span className="stat-value">{fmt(totals.scans)}</span>
        </article>
        <article className="stat-card reveal accent" style={{ '--d': '180ms' }}>
          <span className="stat-label">Points awarded</span>
          <span className="stat-value">{fmt(totals.points_awarded)}</span>
        </article>
        <article className="stat-card reveal" style={{ '--d': '240ms' }}>
          <span className="stat-label">Codes issued</span>
          <span className="stat-value">{fmt(totals.codes_issued)}</span>
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
    </div>
  )
}
