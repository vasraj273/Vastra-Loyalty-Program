import { useCallback, useEffect, useRef, useState } from 'react'
import { del, get, post, put } from '../api.js'
import GenerateQrModal from '../components/GenerateQrModal.jsx'
import ImportResult from '../components/ImportResult.jsx'
import { useConfirm } from '../confirm.jsx'
import { downloadCSV, today } from '../utils/csv.js'

// The catalog is the manufacturer's own CSV import. Columns are whatever their
// file contained: the API returns `columns` (the free-form headers, in CSV
// order) alongside the products, and the table renders name/code, then those,
// then Points and Actions.
const CSV_HELP =
  'CSV needs a product name column and a product code column (any spelling, ' +
  'any case). A points column is optional. Every other column is kept and ' +
  'shown here.'

const PAGE_SIZES = [10, 25, 50, 100]

export default function Products() {
  const [catalog, setCatalog] = useState(null) // {products, columns, source}
  const [editing, setEditing] = useState(null) // {external_id, points}
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const [showGenerate, setShowGenerate] = useState(false)
  const [importResult, setImportResult] = useState(null)
  const [pendingCsv, setPendingCsv] = useState(null) // awaiting update/replace
  const [pageSize, setPageSize] = useState(PAGE_SIZES[0])
  const [page, setPage] = useState(0)
  const fileRef = useRef(null)
  const confirm = useConfirm()

  const products = catalog?.products ?? []
  const attrCols = catalog?.columns ?? []
  const imported = catalog?.source === 'import'

  const pages = Math.max(1, Math.ceil(products.length / pageSize))
  const from = page * pageSize
  const visible = products.slice(from, from + pageSize)

  // Deleting or re-importing can shrink the list out from under the current
  // page; land on the last real one rather than an empty table.
  useEffect(() => {
    if (page >= pages) setPage(pages - 1)
  }, [page, pages])

  const load = useCallback(() => {
    setError(null)
    get('/catalog/products').then(setCatalog).catch((e) => setError(e.message))
  }, [])

  useEffect(load, [load])

  const runImport = async (csv, mode) => {
    setBusy(true)
    setError(null)
    setImportResult(null)
    setPendingCsv(null)
    try {
      setImportResult(await post('/catalog/products/import', { csv, mode }))
      load()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const onImportFile = async (e) => {
    const file = e.target.files?.[0]
    if (file) e.target.value = '' // allow re-importing the same filename
    if (!file) return
    setError(null)
    let csv
    try {
      csv = await file.text()
    } catch (err) {
      setError(`Could not read ${file.name}: ${err.message}`)
      return
    }
    // The first import just runs. Once a list exists, the manufacturer decides
    // whether the file updates it or replaces it wholesale.
    if (imported) setPendingCsv({ csv, name: file.name })
    else runImport(csv, 'upsert')
  }

  const confirmReplace = async () => {
    const ok = await confirm({
      title: 'Replace the entire product list?',
      message:
        `All ${products.length} product(s) currently listed are removed and ` +
        'replaced by the file. Points you set here are lost. Already-printed ' +
        'QR codes keep working — they carry their own product details.',
      confirmLabel: 'Replace all',
      danger: true,
    })
    if (ok) runImport(pendingCsv.csv, 'replace')
  }

  const remove = async (p) => {
    const ok = await confirm({
      title: `Delete ${p.name}?`,
      message:
        'It is removed from your product list. Already-printed QR codes for ' +
        'it keep working — they carry their own product details.',
      confirmLabel: 'Delete',
      danger: true,
    })
    if (!ok) return
    setBusy(true)
    setError(null)
    try {
      await del(`/catalog/products/${encodeURIComponent(p.external_id)}`)
      load()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const removeAll = async () => {
    const ok = await confirm({
      title: `Delete all ${products.length} products?`,
      message:
        'Your entire product list is cleared and you would need to import a ' +
        'CSV again to rebuild it. Points you set here are lost. ' +
        'Already-printed QR codes keep working — they carry their own ' +
        'product details.',
      confirmLabel: `Delete all ${products.length}`,
      danger: true,
    })
    if (!ok) return
    setBusy(true)
    setError(null)
    try {
      await del('/catalog/products')
      setImportResult(null)
      load()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const savePoints = async () => {
    setBusy(true)
    setError(null)
    try {
      await put(
        `/catalog/products/${encodeURIComponent(editing.external_id)}/points`,
        { points: Number(editing.points) },
      )
      setEditing(null)
      load()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const exportCsv = () => {
    downloadCSV(
      `products-${today()}.csv`,
      [
        { label: 'Product name', key: 'name' },
        { label: 'Product code', key: 'sku' },
        ...attrCols.map((c) => ({ label: c, key: c })),
        { label: 'Points', key: 'points' },
      ],
      // Fixed fields last so they win if a CSV column shared their key.
      products.map((p) => ({
        ...p.attrs,
        name: p.name,
        sku: p.sku,
        points: p.points,
      })),
    )
  }

  if (!catalog && !error) return <p className="loading">Loading…</p>

  return (
    <div className="products">
      <div className="schemes-head">
        <h2 className="page-title">
          Products <span className="count">{products.length}</span>
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
            className="btn-primary"
            disabled={busy}
            onClick={() => fileRef.current?.click()}
            title={CSV_HELP}
          >
            Import CSV
          </button>
          <button
            className="btn-secondary"
            onClick={() => setShowGenerate(true)}
            disabled={!products.length}
          >
            Generate QR
          </button>
          <button
            className="btn-secondary"
            disabled={!products.length}
            onClick={exportCsv}
          >
            ↓ Export CSV
          </button>
          {imported && (
            <button
              className="btn-ghost"
              disabled={busy || !products.length}
              onClick={removeAll}
            >
              Delete all
            </button>
          )}
        </div>
      </div>

      <p className="hint">
        {CSV_HELP} Points per scan are set by you and affect{' '}
        <strong>future batches only</strong> — already printed batches keep
        their promised points.
      </p>

      {catalog?.source === 'sample' && (
        <p className="hint">
          <strong>Sample products.</strong> These are built-in examples for
          testing. Import your CSV and they are replaced by your own catalog.
        </p>
      )}

      {error && <p className="error">{error}</p>}
      <ImportResult
        result={importResult}
        onDismiss={() => setImportResult(null)}
      />

      {catalog?.source === 'empty' && (
        <div className="panel-card">
          <p className="hint" style={{ margin: 0 }}>
            No products yet — add them using the <strong>Import CSV</strong>{' '}
            button.
          </p>
        </div>
      )}

      {products.length > 0 && (
        <div className="panel-card table-card">
          <div className="table-toolbar">
            <span>
              Showing <strong>{from + 1}</strong>–
              <strong>{from + visible.length}</strong> of{' '}
              <strong>{products.length}</strong>
            </span>
            <label>
              Rows{' '}
              <select
                value={pageSize}
                onChange={(e) => {
                  setPageSize(Number(e.target.value))
                  setPage(0)
                }}
              >
                {PAGE_SIZES.map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <div className="catalog-scroll">
            <table className="data-table catalog-table">
              <thead>
                <tr>
                  <th className="sticky-col col-name">
                    <div className="cell">Product name</div>
                  </th>
                  <th className="sticky-col col-code">
                    <div className="cell">Product code</div>
                  </th>
                  {attrCols.map((c) => (
                    <th key={c}>{c}</th>
                  ))}
                  <th className="sticky-col col-points num">
                    <div className="cell">Points</div>
                  </th>
                  <th className="sticky-col col-actions">
                    <div className="cell">Actions</div>
                  </th>
                </tr>
              </thead>
              <tbody>
                {visible.map((p) => {
                  const isEditing = editing?.external_id === p.external_id
                  return (
                    <tr
                      key={p.external_id}
                      className={isEditing ? 'editing-row' : undefined}
                    >
                      <td className="sticky-col col-name">
                        <div className="cell" title={p.name}>
                          {p.name}
                        </div>
                      </td>
                      <td className="sticky-col col-code mono">
                        <div className="cell" title={p.sku}>
                          {p.sku}
                        </div>
                      </td>
                      {attrCols.map((c) => (
                        <td key={c}>{p.attrs?.[c] ?? ''}</td>
                      ))}
                      <td className="sticky-col col-points num">
                        <div className="cell">
                          {isEditing ? (
                            <input
                              className="inline-input num"
                              type="number"
                              min="0"
                              autoFocus
                              value={editing.points}
                              onChange={(e) =>
                                setEditing({
                                  ...editing,
                                  points: e.target.value,
                                })
                              }
                            />
                          ) : (
                            <strong>{p.points}</strong>
                          )}
                        </div>
                      </td>
                      <td className="sticky-col col-actions">
                        <div className="cell">
                          {isEditing ? (
                            <>
                              <button
                                className="btn-ghost small"
                                onClick={savePoints}
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
                            </>
                          ) : (
                            <>
                              <button
                                className="btn-ghost small"
                                onClick={() =>
                                  setEditing({
                                    external_id: p.external_id,
                                    points: p.points,
                                  })
                                }
                              >
                                Edit points
                              </button>
                              {imported && (
                                <button
                                  className="btn-ghost small"
                                  disabled={busy}
                                  onClick={() => remove(p)}
                                >
                                  Delete
                                </button>
                              )}
                            </>
                          )}
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>

          {pages > 1 && (
            <div className="pager">
              <button
                className="btn-ghost"
                disabled={page === 0}
                onClick={() => setPage((p) => p - 1)}
              >
                ← Prev
              </button>
              <span>
                Page {page + 1} of {pages}
              </span>
              <button
                className="btn-ghost"
                disabled={page + 1 >= pages}
                onClick={() => setPage((p) => p + 1)}
              >
                Next →
              </button>
            </div>
          )}
        </div>
      )}

      {pendingCsv && (
        <div className="modal-backdrop" onClick={() => setPendingCsv(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>Import {pendingCsv.name}</h3>
            <p className="hint">
              You already have {products.length} product(s). Update the list
              with this file, or replace it entirely?
            </p>
            <div className="btn-row">
              <button
                className="btn-primary"
                disabled={busy}
                onClick={() => runImport(pendingCsv.csv, 'upsert')}
              >
                Update existing list
              </button>
              <button
                className="btn-secondary"
                disabled={busy}
                onClick={confirmReplace}
              >
                Replace entire list
              </button>
              <button
                className="btn-ghost"
                onClick={() => setPendingCsv(null)}
              >
                Cancel
              </button>
            </div>
            <p className="hint" style={{ marginBottom: 0 }}>
              <strong>Update</strong> refreshes products whose code matches,
              adds new ones, and deletes nothing — points you set here are kept
              unless the file has its own points column.
            </p>
          </div>
        </div>
      )}

      {showGenerate && (
        <GenerateQrModal
          products={products}
          onClose={() => setShowGenerate(false)}
        />
      )}
    </div>
  )
}
