import { useCallback, useEffect, useState } from 'react'
import EmptyState from '../components/EmptyState.jsx'
import { get, post } from '../api.js'
import { useConfirm } from '../confirm.jsx'
import { downloadCSV, today } from '../utils/csv.js'
import { OverflowMenu } from '../components/Toolbar.jsx'
import { IconExport } from '../components/icons.jsx'

const STATUSES = ['pending', 'approved', 'rejected']

export default function Redemptions() {
  const [list, setList] = useState(null)
  const [filter, setFilter] = useState('pending')
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(null)
  const [exporting, setExporting] = useState(false)
  const confirm = useConfirm()

  // Exports all three statuses, not just the one being viewed.
  const exportCsv = async () => {
    setExporting(true)
    setError(null)
    try {
      const all = (
        await Promise.all(STATUSES.map((s) => get(`/gift-claims?status=${s}`)))
      ).flat()
      downloadCSV(
        `redemptions-${today()}.csv`,
        [
          { label: 'When', key: 'created_at' },
          { label: 'Reference', format: (c) => c.reference || `CLM-${c.id}` },
          { label: 'Shop', key: 'shop_name' },
          { label: 'Owner', key: 'retailer_name' },
          { label: 'Region', key: 'region' },
          { label: 'Gift', key: 'gift_name' },
          { label: 'Points', key: 'points_spent' },
          { label: 'Status', key: 'status' },
        ],
        all,
      )
    } catch (err) {
      setError(err.message)
    } finally {
      setExporting(false)
    }
  }

  const load = useCallback(() => {
    const q = filter ? `?status=${filter}` : ''
    get(`/gift-claims${q}`).then(setList).catch((e) => setError(e.message))
  }, [filter])

  useEffect(load, [load])

  const decide = async (c, action) => {
    const ok = await confirm(
      action === 'approve'
        ? {
            title: 'Approve redemption?',
            message:
              `Hand over "${c.gift_name}" to ${c.shop_name}. The ` +
              `${c.points_spent} points stay deducted.`,
            confirmLabel: 'Approve',
          }
        : {
            title: 'Reject & refund?',
            message:
              `Refund ${c.points_spent} points to ${c.shop_name} and cancel ` +
              `this claim for "${c.gift_name}".`,
            confirmLabel: 'Reject & refund',
            danger: true,
          },
    )
    if (!ok) return
    setBusy(c.id)
    setError(null)
    try {
      await post(`/gift-claims/${c.id}/${action}`)
      load()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="redemptions">
      <div className="schemes-head">
        <h2 className="page-title">Gift redemptions</h2>
        <div className="btn-row">
          <OverflowMenu
            items={[
              {
                label: exporting ? 'Exporting…' : 'Export CSV',
                icon: <IconExport />,
                // Only meaningful once something has been claimed.
                show: (list?.length ?? 0) > 0,
                disabled: exporting,
                onClick: exportCsv,
              },
            ]}
          />
        </div>
      </div>
      <p className="hint">
        Approve to confirm you’ll hand over the gift. Reject to refund the
        retailer’s points automatically.
      </p>

      <div className="table-tools btn-row">
        {STATUSES.map((s) => (
          <button
            key={s}
            className={filter === s ? 'btn-primary' : 'btn-ghost'}
            onClick={() => setFilter(s)}
          >
            {s[0].toUpperCase() + s.slice(1)}
          </button>
        ))}
      </div>

      {error && <p className="error">{error}</p>}
      {!list ? (
        <p className="loading">Loading…</p>
      ) : list.length === 0 ? (
        <div className="panel-card">
          <EmptyState
            icon={filter === 'pending' ? '✅' : '🎁'}
            title={`No ${filter} redemptions`}
            message={
              filter === 'pending'
                ? 'Nothing is waiting on you. New gift claims from retailers land here for approval.'
                : `Nothing has been ${filter} yet.`
            }
          />
        </div>
      ) : (
        <div className="panel-card table-card">
          <table className="data-table">
            <thead>
              <tr>
                <th>When</th>
                <th>Reference</th>
                <th>Retailer</th>
                <th>Region</th>
                <th>Gift</th>
                <th className="num">Points</th>
                <th>Status</th>
                {filter === 'pending' && <th className="actions-col">Action</th>}
              </tr>
            </thead>
            <tbody>
              {list.map((c) => (
                <tr key={c.id}>
                  <td className="mono nowrap">{c.created_at}</td>
                  <td className="mono">{c.reference || `CLM-${c.id}`}</td>
                  <td>
                    {c.shop_name}
                    <span className="sub"> · {c.retailer_name}</span>
                  </td>
                  <td>{c.region}</td>
                  <td>{c.gift_name}</td>
                  <td className="num">{c.points_spent}</td>
                  <td>
                    <span className={`loc-badge ${c.status === 'approved'
                      ? 'gps' : c.status === 'rejected' ? 'none' : ''}`}>
                      {c.status}
                    </span>
                  </td>
                  {filter === 'pending' && (
                    <td className="actions-col">
                      <button
                        className="btn-ghost small"
                        disabled={busy === c.id}
                        onClick={() => decide(c, 'approve')}
                      >
                        Approve
                      </button>
                      <button
                        className="btn-ghost small danger"
                        disabled={busy === c.id}
                        onClick={() => decide(c, 'reject')}
                      >
                        Reject
                      </button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
