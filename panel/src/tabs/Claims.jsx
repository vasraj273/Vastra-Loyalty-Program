import { useEffect, useState } from 'react'
import { get } from '../api.js'

const PAGE = 20

export default function Claims() {
  const [data, setData] = useState(null)
  const [products, setProducts] = useState([])
  const [retailers, setRetailers] = useState([])
  const [error, setError] = useState(null)
  const [page, setPage] = useState(0)
  const [filters, setFilters] = useState({
    product_id: '',
    retailer_id: '',
    region: '',
    from: '',
    to: '',
  })

  useEffect(() => {
    get('/products').then(setProducts).catch(() => {})
    get('/retailers').then(setRetailers).catch(() => {})
  }, [])

  useEffect(() => {
    const params = new URLSearchParams({ limit: PAGE, offset: page * PAGE })
    if (filters.product_id) params.set('product_id', filters.product_id)
    if (filters.retailer_id) params.set('retailer_id', filters.retailer_id)
    if (filters.region) params.set('region', filters.region)
    if (filters.from) params.set('from', filters.from)
    if (filters.to) params.set('to', `${filters.to} 23:59:59`)
    get(`/claims?${params}`).then(setData).catch((e) => setError(e.message))
  }, [filters, page])

  const setFilter = (key) => (e) => {
    setPage(0)
    setFilters((f) => ({ ...f, [key]: e.target.value }))
  }

  const regions = [...new Set(retailers.map((r) => r.region))].sort()

  if (error) return <p className="error">Failed to load claims: {error}</p>
  if (!data) return <p className="loading">Loading…</p>

  const pages = Math.ceil(data.total / PAGE)

  return (
    <div className="claims">
      <h2 className="page-title">Claims &amp; Redemptions</h2>

      <div className="filters panel-card">
        <label>
          Product
          <select value={filters.product_id} onChange={setFilter('product_id')}>
            <option value="">All</option>
            {products.map((p) => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
        </label>
        <label>
          Retailer
          <select value={filters.retailer_id} onChange={setFilter('retailer_id')}>
            <option value="">All</option>
            {retailers.map((r) => (
              <option key={r.id} value={r.id}>{r.shop_name}</option>
            ))}
          </select>
        </label>
        <label>
          Region
          <select value={filters.region} onChange={setFilter('region')}>
            <option value="">All</option>
            {regions.map((r) => (
              <option key={r} value={r}>{r}</option>
            ))}
          </select>
        </label>
        <label>
          From
          <input type="date" value={filters.from} onChange={setFilter('from')} />
        </label>
        <label>
          To
          <input type="date" value={filters.to} onChange={setFilter('to')} />
        </label>
        <span className="total">{data.total.toLocaleString('en-IN')} claims</span>
      </div>

      <div className="panel-card table-card">
        <table className="data-table claims-table">
          <thead>
            <tr>
              <th>When</th>
              <th>Retailer</th>
              <th>Region</th>
              <th>Product</th>
              <th className="num">Points</th>
              <th>Scheme</th>
              <th>Code</th>
            </tr>
          </thead>
          <tbody>
            {data.claims.map((c) => (
              <tr key={c.id}>
                <td className="mono nowrap">{c.scanned_at}</td>
                <td>
                  {c.shop_name}
                  <span className="sub"> · {c.retailer_name}</span>
                </td>
                <td>{c.region}</td>
                <td>
                  {c.product_name}
                  <span className="sub mono"> {c.sku}</span>
                </td>
                <td className="num">
                  <strong>{c.points}</strong>
                  {c.bonus_points > 0 && (
                    <span className="bonus-split">
                      {' '}{c.base_points}+{c.bonus_points}
                    </span>
                  )}
                </td>
                <td>
                  {c.scheme_name ? (
                    <span className="scheme-tag">{c.scheme_name}</span>
                  ) : (
                    <span className="sub">—</span>
                  )}
                </td>
                <td className="mono sub">{c.token.slice(0, 8)}…</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="pager">
          <button
            className="btn-ghost"
            disabled={page === 0}
            onClick={() => setPage((p) => p - 1)}
          >
            ← Prev
          </button>
          <span>
            Page {page + 1} of {Math.max(1, pages)}
          </span>
          <button
            className="btn-ghost"
            disabled={page + 1 >= pages}
            onClick={() => setPage((p) => p + 1)}
          >
            Next →
          </button>
        </div>
      </div>
    </div>
  )
}
