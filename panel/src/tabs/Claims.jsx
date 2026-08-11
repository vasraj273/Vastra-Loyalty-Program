import { useEffect, useState } from 'react'
import { get, post } from '../api.js'
import EmptyState from '../components/EmptyState.jsx'
import { useConfirm } from '../confirm.jsx'
import { downloadCSV, today } from '../utils/csv.js'
import { OverflowMenu } from '../components/Toolbar.jsx'
import { IconExport } from '../components/icons.jsx'

const PAGE = 20
const EXPORT_PAGE = 500
const fmt = (n) => (n ?? 0).toLocaleString('en-IN')

export default function Claims() {
  const [data, setData] = useState(null)
  const [products, setProducts] = useState([])
  const [retailers, setRetailers] = useState([])
  const [error, setError] = useState(null)
  const [page, setPage] = useState(0)
  const [lookupCode, setLookupCode] = useState('')
  const [lookup, setLookup] = useState(null)
  const [actionError, setActionError] = useState(null)
  const [notice, setNotice] = useState(null)
  const [busy, setBusy] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [refresh, setRefresh] = useState(0)
  const confirm = useConfirm()
  const [filters, setFilters] = useState({
    product_id: '',
    retailer_id: '',
    region: '',
    from: '',
    to: '',
  })

  const anyFilter = Object.values(filters).some(Boolean)

  // Shared query string for the current filters (without paging).
  const filterParams = () => {
    const params = new URLSearchParams()
    if (filters.product_id) params.set('product_id', filters.product_id)
    if (filters.retailer_id) params.set('retailer_id', filters.retailer_id)
    if (filters.region) params.set('region', filters.region)
    if (filters.from) params.set('from', filters.from)
    if (filters.to) params.set('to', `${filters.to} 23:59:59`)
    return params
  }

  useEffect(() => {
    get('/products').then(setProducts).catch(() => {})
    get('/retailers').then(setRetailers).catch(() => {})
  }, [])

  useEffect(() => {
    const params = filterParams()
    params.set('limit', PAGE)
    params.set('offset', page * PAGE)
    get(`/claims?${params}`).then(setData).catch((e) => setError(e.message))
  }, [filters, page, refresh])

  // Auto-dismiss the toast so it doesn't linger over the table.
  useEffect(() => {
    if (!notice && !actionError) return
    const t = setTimeout(() => { setNotice(null); setActionError(null) }, 5000)
    return () => clearTimeout(t)
  }, [notice, actionError])

  // Claims are server-paginated, so walk every page (with the current filters)
  // before building the CSV. Rows are already box-grouped by the API.
  const exportCsv = async () => {
    setExporting(true)
    setError(null)
    try {
      const rows = []
      for (let offset = 0; ; offset += EXPORT_PAGE) {
        const params = filterParams()
        params.set('limit', EXPORT_PAGE)
        params.set('offset', offset)
        const res = await get(`/claims?${params}`)
        rows.push(...res.claims)
        if (offset + EXPORT_PAGE >= res.total || res.claims.length === 0) break
      }
      downloadCSV(
        `claims-${today()}.csv`,
        [
          { label: 'When', key: 'scanned_at' },
          { label: 'Shop', key: 'shop_name' },
          { label: 'Owner', key: 'retailer_name' },
          { label: 'Region', key: 'region' },
          { label: 'Product', key: 'product_name' },
          { label: 'SKU', key: 'sku' },
          { label: 'Points', key: 'points' },
          { label: 'Base', key: 'base_points' },
          { label: 'Bonus', key: 'bonus_points' },
          { label: 'Scheme', key: 'scheme_name' },
          { label: 'Items', format: (c) => c.item_count ?? 1 },
          { label: 'Code', key: 'token' },
        ],
        rows,
      )
    } catch (e) {
      setError(e.message)
    } finally {
      setExporting(false)
    }
  }

  const doLookup = async () => {
    if (!lookupCode.trim()) return
    setBusy(true)
    setActionError(null)
    setNotice(null)
    setLookup(null)
    try {
      setLookup(await get(`/scans/lookup?code=${encodeURIComponent(lookupCode.trim())}`))
    } catch (e) {
      setActionError(e.message)
    } finally {
      setBusy(false)
    }
  }

  // Shared by the lookup card and the per-row action. `info` carries whatever
  // scan details we have for the confirm message.
  const doReverse = async (code, info) => {
    const items = info.item_count > 1 ? ` (📦 box · ${info.item_count} items)` : ''
    const ok = await confirm({
      title: 'Reverse this scan?',
      message:
        `Deduct ${fmt(info.points)} points from ${info.shop_name}${items} ` +
        'and re-enable the QR code so the rightful retailer can scan it again.',
      confirmLabel: 'Reverse scan',
      danger: true,
    })
    if (!ok) return
    setBusy(true)
    setActionError(null)
    setNotice(null)
    try {
      const res = await post('/scans/reverse', { code })
      setNotice(
        `Reversed — ${fmt(res.points_deducted)} points deducted, ` +
        'code can be scanned again.',
      )
      setLookup(null)
      setLookupCode('')
      setRefresh((n) => n + 1)
    } catch (e) {
      setActionError(e.message)
    } finally {
      setBusy(false)
    }
  }

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
      {/* Fixed toast so a reverse triggered from a row deep in the scrolled
          list shows its result (success or error) where the user is looking,
          not off-screen at the top of the page. */}
      {(notice || actionError) && (
        <div
          className={`toast ${actionError ? 'toast-err' : 'toast-ok'}`}
          onClick={() => { setNotice(null); setActionError(null) }}
        >
          {actionError || notice}
        </div>
      )}
      <div className="schemes-head">
        <h2 className="page-title">Claims &amp; Redemptions</h2>
        <div className="btn-row">
          <OverflowMenu
            items={[
              {
                label: exporting ? 'Exporting…' : 'Export CSV',
                icon: <IconExport />,
                // Nothing matches the current filters — nothing to export.
                show: data.total > 0,
                disabled: exporting,
                onClick: exportCsv,
              },
            ]}
          />
        </div>
      </div>

      {/* Find a specific scan by sticker code (full QR token or 6-char
          manual code) — the entry point when a retailer reports someone
          else scanned their product. */}
      <div className="filters panel-card">
        <label style={{ flex: 1, minWidth: 220 }}>
          Find scan by code
          <input
            type="text"
            placeholder="QR token or 6-char code"
            value={lookupCode}
            onChange={(e) => setLookupCode(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && doLookup()}
          />
        </label>
        <button className="btn-secondary" disabled={busy || !lookupCode.trim()} onClick={doLookup}>
          Look up
        </button>
      </div>

      {lookup && (
        <div className="filters panel-card">
          {lookup.redeemed ? (
            <>
              <span>
                <strong>{lookup.retailer?.shop_name ?? `Retailer #${lookup.retailer?.id}`}</strong>
                <span className="sub"> scanned {lookup.product_name}</span>
                {lookup.is_box && (
                  <span className="scheme-tag" style={{ marginLeft: 6 }}>
                    📦 Box · {lookup.item_count} items
                  </span>
                )}
              </span>
              <span className="mono nowrap sub">{lookup.scanned_at}</span>
              <span>
                <strong>{fmt(lookup.points)} pts</strong>
                {lookup.bonus_points > 0 && (
                  <span className="sub"> ({fmt(lookup.base_points)}+{fmt(lookup.bonus_points)}
                    {lookup.scheme_name ? ` · ${lookup.scheme_name}` : ''})
                  </span>
                )}
              </span>
              <button
                className="btn-secondary"
                disabled={busy || !lookup.reversible}
                title={lookup.reversible ? undefined : lookup.reason}
                onClick={() =>
                  doReverse(lookup.token, {
                    points: lookup.points,
                    shop_name: lookup.retailer?.shop_name,
                    item_count: lookup.item_count,
                  })
                }
              >
                ↩ Reverse scan
              </button>
              {!lookup.reversible && <span className="sub">{lookup.reason}</span>}
            </>
          ) : (
            <span className="sub">
              {lookup.product_name} · not scanned yet — worth {fmt(lookup.points_per_code)} pts
            </span>
          )}
        </div>
      )}

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

      {data.claims.length === 0 ? (
        <div className="panel-card">
          <EmptyState
            icon={anyFilter ? '🔍' : '📄'}
            title={anyFilter ? 'No scans match these filters' : 'No scans yet'}
            message={
              anyFilter
                ? 'Widen the date range, or clear the filters to see every scan.'
                : 'Every QR code a retailer scans is listed here with the points it paid out.'
            }
            action={
              anyFilter ? (
                <button
                  className="btn-ghost"
                  onClick={() => {
                    setFilters({
                      product_id: '', retailer_id: '', region: '',
                      from: '', to: '',
                    })
                    setPage(0)
                  }}
                >
                  Clear filters
                </button>
              ) : null
            }
          />
        </div>
      ) : (
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
              <th />
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
                  {c.item_count > 1 && (
                    <span className="scheme-tag" style={{ marginLeft: 6 }}>
                      📦 Box · {c.item_count} items
                    </span>
                  )}
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
                <td className="mono sub">
                  {c.token.slice(0, 8)}…
                  {c.item_count > 1 && ` (${c.item_count} codes)`}
                </td>
                <td>
                  <button
                    className="btn-ghost"
                    disabled={busy}
                    title="Deduct these points and re-enable the QR code"
                    onClick={() => doReverse(c.token, c)}
                  >
                    ↩ Reverse
                  </button>
                </td>
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
      )}
    </div>
  )
}
