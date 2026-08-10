import { useCallback, useEffect, useRef, useState } from 'react'
import { get, post, patch, del } from '../api.js'
import ImportResult from '../components/ImportResult.jsx'
import EmptyState from '../components/EmptyState.jsx'
import { useConfirm } from '../confirm.jsx'
import { downloadSample } from '../utils/sampleCsv.js'

const EMPTY = { name: '', phone: '', region: '' }
const fmt = (n) => (n ?? 0).toLocaleString('en-IN')

export default function Distributors() {
  const [list, setList] = useState(null)
  const [form, setForm] = useState(EMPTY)
  const [showForm, setShowForm] = useState(false)
  const [editing, setEditing] = useState(null) // {id, name, phone, region}
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const [importResult, setImportResult] = useState(null)
  const fileRef = useRef(null)
  const confirm = useConfirm()

  // Bulk import distributors from a CSV file. The server matches the headers
  // rather than requiring ours, so the manufacturer's own export imports as-is.
  const onImportFile = async (e) => {
    const file = e.target.files?.[0]
    if (file) e.target.value = '' // allow re-importing the same filename
    if (!file) return
    setBusy(true)
    setError(null)
    setImportResult(null)
    try {
      const csv = await file.text()
      setImportResult(await post('/distributors/import', { csv }))
      load()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const load = useCallback(() => {
    get('/distributors').then(setList).catch((e) => setError(e.message))
  }, [])

  useEffect(load, [load])

  const add = async (e) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await post('/distributors', {
        name: form.name,
        phone: form.phone || null,
        region: form.region || null,
      })
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
      await patch(`/distributors/${editing.id}`, {
        name: editing.name,
        phone: editing.phone || null,
        region: editing.region || null,
      })
      setEditing(null)
      load()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const remove = async (d) => {
    const ok = await confirm({
      title: `Delete ${d.name}?`,
      message:
        `Its ${d.retailers} retailer(s) are only unassigned, never deleted, ` +
        'and past scans keep the distributor they were recorded against.',
      confirmLabel: 'Delete distributor',
      danger: true,
    })
    if (!ok) return
    setError(null)
    try {
      await del(`/distributors/${d.id}`)
      load()
    } catch (err) {
      setError(err.message)
    }
  }

  const removeAll = async () => {
    const ok = await confirm({
      title: `Delete all ${list.length} distributors?`,
      confirmLabel: `Delete all ${list.length}`,
      danger: true,
    })
    if (!ok) return
    setBusy(true)
    setError(null)
    try {
      await del('/distributors')
      setImportResult(null)
      load()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  if (!list) return <p className="loading">Loading…</p>

  return (
    <div className="distributors">
      <div className="schemes-head">
        <h2 className="page-title">
          Distributors <span className="count">{list.length}</span>
        </h2>
        <div className="btn-row">
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
            title="Needs a name column. Phone and region are matched from your own headers (Mobile, Contact No, City, State…)."
          >
            Import CSV
          </button>
          <button
            className="btn-ghost"
            onClick={() => downloadSample('distributors')}
            title="Download a filled-in example file with the expected columns"
          >
            ↓ Sample CSV
          </button>
          <button className="btn-primary" onClick={() => setShowForm((s) => !s)}>
            {showForm ? 'Close' : '+ Add distributor'}
          </button>
          {list.length > 0 && (
            <button className="btn-ghost" disabled={busy} onClick={removeAll}>
              Delete all
            </button>
          )}
        </div>
      </div>
      <p className="hint">
        Distributors sit between you and your retailers (you → distributor →
        retailer). Assign retailers to a distributor in the Retailers tab, or via
        the <strong>distributor</strong> column when importing a CSV. An imported
        file only needs a name column — phone and region are matched from
        whatever your export calls them.
      </p>
      {error && <p className="error">{error}</p>}
      <ImportResult result={importResult} onDismiss={() => setImportResult(null)} />

      {showForm && (
        <form className="panel-card entity-form" onSubmit={add}>
          <div className="entity-form-head">
            <h3>New distributor</h3>
            <p className="hint">
              Tracking only — a distributor has no login and holds no points.
              The name is all that is needed.
            </p>
          </div>

          <div className="field-grid">
            <label>
              <span className="field-label">
                Distributor name <em className="req">required</em>
              </span>
              <input
                required
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                placeholder="Vansh Distributors"
              />
            </label>
            <label>
              <span className="field-label">
                Mobile number <em className="opt">optional</em>
              </span>
              <input
                type="tel"
                inputMode="numeric"
                value={form.phone}
                onChange={(e) => setForm({ ...form, phone: e.target.value })}
                placeholder="98XXXXXXXX"
              />
            </label>
            <label>
              <span className="field-label">
                Region <em className="opt">optional</em>
              </span>
              <input
                value={form.region}
                onChange={(e) => setForm({ ...form, region: e.target.value })}
                placeholder="Gujarat"
              />
            </label>
          </div>

          <div className="entity-form-actions">
            <button
              type="button"
              className="btn-ghost"
              onClick={() => {
                setForm(EMPTY)
                setShowForm(false)
              }}
            >
              Cancel
            </button>
            <button className="btn-primary" disabled={busy}>
              {busy ? 'Adding…' : 'Add distributor'}
            </button>
          </div>
        </form>
      )}

      {list.length === 0 ? (
        <div className="panel-card">
          <EmptyState
            icon="🚚"
            title="No distributors yet"
            message="Import your distributor list as a CSV, or add the first one by hand. Retailers can then be assigned to them in the Retailers tab."
            action={
              <>
                <button
                  className="btn-primary"
                  disabled={busy}
                  onClick={() => fileRef.current?.click()}
                >
                  Import CSV
                </button>
                <button
                  className="btn-ghost"
                  onClick={() => downloadSample('distributors')}
                >
                  ↓ Sample CSV
                </button>
              </>
            }
          />
        </div>
      ) : (
      <div className="panel-card table-card">
        <table className="data-table">
          <thead>
            <tr>
              <th>Distributor</th>
              <th>Phone</th>
              <th>Region</th>
              <th className="num">Retailers</th>
              <th className="num">Scans</th>
              <th className="actions-col">Actions</th>
            </tr>
          </thead>
          <tbody>
            {list.map((d) =>
              editing?.id === d.id ? (
                <tr key={d.id} className="editing-row">
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
                      value={editing.phone}
                      onChange={(e) =>
                        setEditing({ ...editing, phone: e.target.value })
                      }
                    />
                  </td>
                  <td>
                    <input
                      className="inline-input"
                      value={editing.region}
                      onChange={(e) =>
                        setEditing({ ...editing, region: e.target.value })
                      }
                    />
                  </td>
                  <td className="num">{fmt(d.retailers)}</td>
                  <td className="num">{fmt(d.scans)}</td>
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
                <tr key={d.id}>
                  <td>{d.name}</td>
                  <td className="mono">{d.phone ?? '—'}</td>
                  <td>{d.region ?? '—'}</td>
                  <td className="num">{fmt(d.retailers)}</td>
                  <td className="num">{fmt(d.scans)}</td>
                  <td className="actions-col">
                    <button
                      className="btn-ghost small"
                      onClick={() =>
                        setEditing({
                          id: d.id,
                          name: d.name,
                          phone: d.phone ?? '',
                          region: d.region ?? '',
                        })
                      }
                    >
                      Edit
                    </button>
                    <button
                      className="btn-ghost small danger"
                      onClick={() => remove(d)}
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ),
            )}
          </tbody>
        </table>
      </div>
      )}
    </div>
  )
}
