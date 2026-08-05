import { useCallback, useEffect, useRef, useState } from 'react'
import { get, post, patch, del } from '../api.js'
import { ColumnMap } from '../components/ImportResult.jsx'
import { useConfirm } from '../confirm.jsx'
import { downloadCSV, today } from '../utils/csv.js'

const EMPTY = { name: '', shop_name: '', region: '', phone: '', distributor_id: '' }
const fmt = (n) => (n ?? 0).toLocaleString('en-IN')

export default function Customers() {
  const [list, setList] = useState(null)
  const [form, setForm] = useState(EMPTY)
  const [showForm, setShowForm] = useState(false)
  const [error, setError] = useState(null)
  const [notice, setNotice] = useState(null)
  const [busy, setBusy] = useState(false)
  const [query, setQuery] = useState('')
  const [editing, setEditing] = useState(null)
  const [modal, setModal] = useState(null) // {type:'adjust', r} | {type:'transfer'}
  const [pts, setPts] = useState('')
  const [note, setNote] = useState('')
  const [fromId, setFromId] = useState('')
  const [toId, setToId] = useState('')

  const [cities, setCities] = useState([])
  const [distributors, setDistributors] = useState([])
  const [importResult, setImportResult] = useState(null)
  const fileRef = useRef(null)
  const confirm = useConfirm()

  const load = useCallback(() => {
    get('/retailers').then(setList).catch((e) => setError(e.message))
  }, [])

  const loadDistributors = useCallback(() => {
    get('/distributors').then(setDistributors).catch(() => {})
  }, [])

  useEffect(load, [load])
  useEffect(loadDistributors, [loadDistributors])
  useEffect(() => {
    get('/public/cities').then(setCities).catch(() => {})
  }, [])

  const submit = async (e) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      const out = await post('/retailers', {
        ...form,
        phone: form.phone || null,
        distributor_id: form.distributor_id ? Number(form.distributor_id) : null,
      })
      const place =
        out.lat != null
          ? `Placed on the map at ${out.region}.`
          : !out.region
            ? "No city set — it'll be detected from the first scan location."
            : `City "${out.region}" not in the map lookup; pinned by GPS on first scan.`
      const creds = out.login_username
        ? ` Login → ${out.login_username} / ${out.login_password}`
        : ''
      setNotice(`${out.shop_name} added. ${place}${creds}`)
      setForm(EMPTY)
      setShowForm(false)
      load()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const saveEdit = async () => {
    setBusy(true)
    setError(null)
    try {
      await patch(`/retailers/${editing.id}`, {
        name: editing.name,
        shop_name: editing.shop_name,
        region: editing.region,
        phone: editing.phone || null,
      })
      setEditing(null)
      load()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const remove = async (r) => {
    if (!window.confirm(`Remove "${r.shop_name}"? This cannot be undone.`))
      return
    setError(null)
    try {
      await del(`/retailers/${r.id}`)
      load()
    } catch (err) {
      setError(err.message)
    }
  }

  const removeAll = async () => {
    const ok = await confirm({
      title: `Delete all ${list.length} customers?`,
      message:
        'Your entire customer list is cleared and you would need to import a ' +
        'CSV again to rebuild it. Their logins stop working immediately. ' +
        'Customers who already have scan history are kept — their points and ' +
        'claims need an owner.',
      confirmLabel: `Delete all ${list.length}`,
      danger: true,
    })
    if (!ok) return
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      const res = await del('/retailers')
      setImportResult(null)
      setNotice(
        res.skipped
          ? `Deleted ${res.deleted}. Kept ${res.skipped} with scan history — ` +
            'delete their scans first, or leave them.'
          : `Deleted ${res.deleted} customer(s).`,
      )
      load()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  // Assign / unassign a retailer's distributor straight from the table row.
  const assignDistributor = async (r, value) => {
    setError(null)
    try {
      await patch(`/retailers/${r.id}`, {
        distributor_id: value === '' ? null : Number(value),
      })
      load()
      loadDistributors()
    } catch (err) {
      setError(err.message)
    }
  }

function splitCsvChunks(csvText, chunkSize = 250) {
  const lines = csvText.split(/\r?\n/)
  if (lines.length <= 1) return [csvText]

  let headerIndex = 0
  while (headerIndex < lines.length && !lines[headerIndex].trim()) {
    headerIndex++
  }
  if (headerIndex >= lines.length) return [csvText]

  const header = lines[headerIndex]
  const dataLines = lines.slice(headerIndex + 1).filter((l) => l.trim().length > 0)

  if (dataLines.length <= chunkSize) return [csvText]

  const chunks = []
  for (let i = 0; i < dataLines.length; i += chunkSize) {
    const batch = dataLines.slice(i, i + chunkSize)
    chunks.push([header, ...batch].join('\n'))
  }
  return chunks
}

  // Bulk import retailers (+ their distributors) from a CSV file in chunks
  // to prevent request timeouts and provide real-time batch progress.
  const onImportFile = async (e) => {
    const file = e.target.files?.[0]
    if (file) e.target.value = '' // allow re-importing the same filename
    if (!file) return
    setBusy(true)
    setError(null)
    setNotice(null)
    setImportResult(null)
    try {
      const csv = await file.text()
      const chunks = splitCsvChunks(csv, 250)

      let totalCreated = 0
      let totalSkipped = 0
      const allErrors = []
      const allCredentials = []
      let lastColumns = null

      for (let i = 0; i < chunks.length; i++) {
        if (chunks.length > 1) {
          setNotice(
            `Importing customers: batch ${i + 1} of ${chunks.length}...`,
          )
        }
        const res = await post('/retailers/import', { csv: chunks[i] })
        totalCreated += res.created || 0
        totalSkipped += res.skipped || 0
        if (res.errors) allErrors.push(...res.errors)
        if (res.credentials) allCredentials.push(...res.credentials)
        if (res.columns) lastColumns = res.columns
      }

      setImportResult({
        created: totalCreated,
        skipped: totalSkipped,
        errors: allErrors,
        credentials: allCredentials,
        columns: lastColumns,
      })
      setNotice(
        `Import completed! ${totalCreated} customer(s) created, ${totalSkipped} skipped.`,
      )
      load()
      loadDistributors()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  // Download every customer (current list) as CSV; distributor id → name.
  const exportCsv = () => {
    const dName = (id) =>
      distributors.find((d) => d.id === id)?.name ?? ''
    downloadCSV(
      `customers-${today()}.csv`,
      [
        { label: 'Shop', key: 'shop_name' },
        { label: 'Owner', key: 'name' },
        { label: 'City', key: 'region' },
        { label: 'Distributor', format: (r) => dName(r.distributor_id) },
        { label: 'Phone', key: 'phone' },
        { label: 'Address', key: 'address' },
        { label: 'Scans', format: (r) => r.scans ?? 0 },
        { label: 'Points', format: (r) => r.points ?? 0 },
      ],
      list,
    )
  }

  const doAdjust = async () => {
    const n = Number(pts)
    const ok = await confirm({
      title: n < 0 ? 'Remove points?' : 'Add points?',
      message:
        `${n >= 0 ? '+' : ''}${fmt(n)} points ${n < 0 ? 'from' : 'to'} ` +
        `${modal.r.shop_name} — balance ${fmt(modal.r.points)} → ` +
        `${fmt(modal.r.points + n)}.${note ? ` Reason: ${note}` : ''}`,
      confirmLabel: n < 0 ? 'Remove points' : 'Add points',
      danger: n < 0,
    })
    if (!ok) return
    setBusy(true)
    setError(null)
    try {
      await post(`/retailers/${modal.r.id}/adjust`, {
        points: Number(pts),
        note,
      })
      setModal(null)
      load()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const doTransfer = async () => {
    const from = list.find((r) => r.id === Number(fromId))
    const to = list.find((r) => r.id === Number(toId))
    const ok = await confirm({
      title: 'Transfer points?',
      message:
        `Move ${fmt(Number(pts))} points from ${from?.shop_name} to ` +
        `${to?.shop_name}.${note ? ` Reason: ${note}` : ''}`,
      confirmLabel: 'Transfer',
    })
    if (!ok) return
    setBusy(true)
    setError(null)
    try {
      await post('/retailers/transfer', {
        from_retailer_id: Number(fromId),
        to_retailer_id: Number(toId),
        points: Number(pts),
        note,
      })
      setModal(null)
      load()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  if (!list) return <p className="loading">Loading…</p>

  const q = query.trim().toLowerCase()
  const filtered = q
    ? list.filter((r) =>
        [r.name, r.shop_name, r.region, r.phone ?? '']
          .join(' ')
          .toLowerCase()
          .includes(q),
      )
    : list

  return (
    <div className="customers">
      <div className="schemes-head">
        <h2 className="page-title">
          Customers <span className="count">{list.length}</span>
        </h2>
        <div className="btn-row">
          <button
            className="btn-secondary"
            onClick={() => {
              setPts('')
              setNote('')
              setFromId('')
              setToId('')
              setModal({ type: 'transfer' })
            }}
          >
            Transfer points
          </button>
          <button
            className="btn-secondary"
            disabled={list.length === 0}
            onClick={exportCsv}
          >
            ↓ Export CSV
          </button>
          <input
            ref={fileRef}
            type="file"
            accept=".csv,text/csv"
            style={{ display: 'none' }}
            onChange={onImportFile}
          />
          <button
            className="btn-secondary"
            disabled={busy}
            onClick={() => fileRef.current?.click()}
            title="Needs a shop or name column. Phone, city, address and distributor are matched from your own headers (Mobile, city, address1…)."
          >
            Import CSV
          </button>
          <button className="btn-primary" onClick={() => setShowForm((s) => !s)}>
            {showForm ? 'Close' : '+ Add customer'}
          </button>
          <button
            className="btn-ghost"
            disabled={busy || list.length === 0}
            onClick={removeAll}
          >
            Delete all
          </button>
        </div>
      </div>
      {error && <p className="error">{error}</p>}
      {notice && <p className="created-note">{notice}</p>}

      {importResult && (
        <div className="panel-card" style={{ marginBottom: 14 }}>
          <div className="schemes-head" style={{ marginBottom: 6 }}>
            <strong>
              Imported {importResult.created} · skipped {importResult.skipped}
              {importResult.errors.length
                ? ` · ${importResult.errors.length} error(s)`
                : ''}
            </strong>
            <button className="btn-ghost small" onClick={() => setImportResult(null)}>
              Dismiss
            </button>
          </div>
          <ColumnMap columns={importResult.columns} />
          {importResult.errors.length > 0 && (
            <ul className="hint" style={{ marginTop: 0 }}>
              {importResult.errors.slice(0, 8).map((er, i) => (
                <li key={i}>{er}</li>
              ))}
            </ul>
          )}
          {importResult.credentials.length > 0 && (
            <>
              <p className="hint" style={{ margin: '4px 0' }}>
                New logins (shown once — copy them now):
              </p>
              <div style={{ maxHeight: 180, overflowY: 'auto' }}>
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Shop</th>
                      <th>Username</th>
                      <th>Password</th>
                    </tr>
                  </thead>
                  <tbody>
                    {importResult.credentials.map((c) => (
                      <tr key={c.username}>
                        <td>{c.shop_name}</td>
                        <td className="mono">{c.username}</td>
                        <td className="mono">{c.password}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </div>
      )}

      {showForm && (
        <form className="panel-card scheme-form" onSubmit={submit}>
          <div className="form-grid">
            <label>
              Owner name
              <input
                required
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                placeholder="Ramesh Kumar"
              />
            </label>
            <label>
              Shop name
              <input
                required
                value={form.shop_name}
                onChange={(e) =>
                  setForm({ ...form, shop_name: e.target.value })
                }
                placeholder="Kumar Sarees"
              />
            </label>
            <label>
              City <span className="hint">(optional — auto-detected on first scan)</span>
              <input
                list="city-options"
                value={form.region}
                onChange={(e) => setForm({ ...form, region: e.target.value })}
                placeholder="Leave blank to detect from first scan"
              />
              <datalist id="city-options">
                {cities.map((c) => (
                  <option key={c} value={c.replace(/\b\w/g, (m) => m.toUpperCase())} />
                ))}
              </datalist>
            </label>
            <label>
              Phone (optional)
              <input
                value={form.phone}
                onChange={(e) => setForm({ ...form, phone: e.target.value })}
                placeholder="98XXXXXXXX"
              />
            </label>
            <label>
              Distributor <span className="hint">(optional)</span>
              <select
                value={form.distributor_id}
                onChange={(e) =>
                  setForm({ ...form, distributor_id: e.target.value })
                }
              >
                <option value="">— none —</option>
                {distributors.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.name}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <p className="hint" style={{ margin: 0 }}>
            Map location is set automatically from the city. The exact shop
            position locks in by GPS the first time this customer scans a code.
          </p>
          <button className="btn-primary" disabled={busy}>
            {busy ? 'Adding…' : 'Add customer'}
          </button>
        </form>
      )}

      <div className="panel-card table-card">
        <div className="table-tools">
          <input
            className="search"
            placeholder="Search name, shop, city, phone…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        <table className="data-table">
          <thead>
            <tr>
              <th>Shop</th>
              <th>Owner</th>
              <th>City</th>
              <th>Distributor</th>
              <th>Phone</th>
              <th>Location</th>
              <th className="num">Scans</th>
              <th className="num">Points</th>
              <th className="actions-col">Actions</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((r) =>
              editing?.id === r.id ? (
                <tr key={r.id} className="editing-row">
                  <td>
                    <input
                      className="inline-input"
                      value={editing.shop_name}
                      onChange={(e) =>
                        setEditing({ ...editing, shop_name: e.target.value })
                      }
                    />
                  </td>
                  <td>
                    <input
                      className="inline-input"
                      value={editing.name}
                      onChange={(e) =>
                        setEditing({ ...editing, name: e.target.value })
                      }
                    />
                  </td>
                  <td>
                    <input
                      className="inline-input"
                      list="city-options"
                      value={editing.region}
                      onChange={(e) =>
                        setEditing({ ...editing, region: e.target.value })
                      }
                    />
                  </td>
                  <td>
                    <select
                      className="inline-input"
                      value={r.distributor_id ?? ''}
                      onChange={(e) => assignDistributor(r, e.target.value)}
                    >
                      <option value="">— none —</option>
                      {distributors.map((d) => (
                        <option key={d.id} value={d.id}>
                          {d.name}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td>
                    <input
                      className="inline-input"
                      value={editing.phone ?? ''}
                      onChange={(e) =>
                        setEditing({ ...editing, phone: e.target.value })
                      }
                    />
                  </td>
                  <td>
                    <span className="loc-badge">
                      {r.location_source === 'gps' ? 'GPS kept' : 'auto'}
                    </span>
                  </td>
                  <td className="num">{fmt(r.scans)}</td>
                  <td className="num">{fmt(r.points)}</td>
                  <td className="actions-col">
                    <button
                      className="btn-ghost small"
                      onClick={saveEdit}
                      disabled={busy}
                    >
                      Save
                    </button>
                    <button
                      className="btn-ghost small"
                      onClick={() => setEditing(null)}
                    >
                      Cancel
                    </button>
                  </td>
                </tr>
              ) : (
                <tr key={r.id}>
                  <td>{r.shop_name}</td>
                  <td>{r.name}</td>
                  <td>{r.region || <span style={{ color: 'var(--ink-soft)' }}>Pending first scan</span>}</td>
                  <td>
                    <select
                      className="inline-input"
                      value={r.distributor_id ?? ''}
                      onChange={(e) => assignDistributor(r, e.target.value)}
                    >
                      <option value="">— none —</option>
                      {distributors.map((d) => (
                        <option key={d.id} value={d.id}>
                          {d.name}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td className="mono">{r.phone ?? '—'}</td>
                  <td>
                    {r.location_source === 'gps' && r.lat != null ? (
                      <div className="loc-cell">
                        <span className="loc-addr" title={r.address || ''}>
                          {r.address || r.region || 'Location captured'}
                        </span>
                        <a
                          className="loc-map"
                          href={`https://www.google.com/maps?q=${r.lat},${r.lng}`}
                          target="_blank"
                          rel="noreferrer"
                        >
                          View on map →
                        </a>
                      </div>
                    ) : r.location_source === 'city' ? (
                      <span className="loc-badge">city (approx)</span>
                    ) : (
                      <span className="loc-badge none">pending first scan</span>
                    )}
                  </td>
                  <td className="num">{fmt(r.scans)}</td>
                  <td className="num">{fmt(r.points)}</td>
                  <td className="actions-col">
                    <button
                      className="btn-ghost small"
                      onClick={() =>
                        setEditing({
                          id: r.id,
                          name: r.name,
                          shop_name: r.shop_name,
                          region: r.region,
                          phone: r.phone,
                        })
                      }
                    >
                      Edit
                    </button>
                    <button
                      className="btn-ghost small"
                      onClick={() => {
                        setPts('')
                        setNote('')
                        setModal({ type: 'adjust', r })
                      }}
                    >
                      Points
                    </button>
                    <button
                      className="btn-ghost small danger"
                      onClick={() => remove(r)}
                    >
                      Remove
                    </button>
                  </td>
                </tr>
              ),
            )}
            {filtered.length === 0 && (
              <tr>
                <td colSpan="9" className="empty">
                  No customers match.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {modal?.type === 'adjust' && (
        <div className="modal-backdrop" onClick={() => setModal(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>Adjust points — {modal.r.shop_name}</h3>
            <p className="hint" style={{ margin: 0 }}>
              Current balance {fmt(modal.r.points)}. Use a negative number to
              remove points. Cannot go below zero.
            </p>
            <label>
              Points (+ add / − remove)
              <input
                type="number"
                value={pts}
                onChange={(e) => setPts(e.target.value)}
                placeholder="e.g. 50 or -50"
              />
            </label>
            <label>
              Reason
              <input
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder="Why this correction?"
              />
            </label>
            <div className="btn-row">
              <button
                className="btn-primary"
                disabled={busy || !pts || !note.trim()}
                onClick={doAdjust}
              >
                Apply
              </button>
              <button className="btn-ghost" onClick={() => setModal(null)}>
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

      {modal?.type === 'transfer' && (
        <div className="modal-backdrop" onClick={() => setModal(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>Transfer points</h3>
            <p className="hint" style={{ margin: 0 }}>
              Move points from one shop to another (e.g. a scan credited to the
              wrong retailer).
            </p>
            <label>
              From
              <select value={fromId} onChange={(e) => setFromId(e.target.value)}>
                <option value="">Select shop…</option>
                {list.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.shop_name} ({fmt(r.points)} pts)
                  </option>
                ))}
              </select>
            </label>
            <label>
              To
              <select value={toId} onChange={(e) => setToId(e.target.value)}>
                <option value="">Select shop…</option>
                {list.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.shop_name} ({fmt(r.points)} pts)
                  </option>
                ))}
              </select>
            </label>
            <label>
              Points
              <input
                type="number"
                min="1"
                value={pts}
                onChange={(e) => setPts(e.target.value)}
              />
            </label>
            <label>
              Reason
              <input
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder="Why this transfer?"
              />
            </label>
            <div className="btn-row">
              <button
                className="btn-primary"
                disabled={
                  busy || !fromId || !toId || fromId === toId ||
                  !pts || !note.trim()
                }
                onClick={doTransfer}
              >
                Transfer
              </button>
              <button className="btn-ghost" onClick={() => setModal(null)}>
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
