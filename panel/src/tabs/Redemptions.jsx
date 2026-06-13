import { useCallback, useEffect, useState } from 'react'
import { get, post } from '../api.js'

const STATUSES = ['pending', 'approved', 'rejected']

export default function Redemptions() {
  const [list, setList] = useState(null)
  const [filter, setFilter] = useState('pending')
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(null)

  const load = useCallback(() => {
    const q = filter ? `?status=${filter}` : ''
    get(`/gift-claims${q}`).then(setList).catch((e) => setError(e.message))
  }, [filter])

  useEffect(load, [load])

  const decide = async (id, action) => {
    setBusy(id)
    setError(null)
    try {
      await post(`/gift-claims/${id}/${action}`)
      load()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="redemptions">
      <h2 className="page-title">Gift redemptions</h2>
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
      ) : (
        <div className="panel-card table-card">
          <table className="data-table">
            <thead>
              <tr>
                <th>When</th>
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
                        onClick={() => decide(c.id, 'approve')}
                      >
                        Approve
                      </button>
                      <button
                        className="btn-ghost small danger"
                        disabled={busy === c.id}
                        onClick={() => decide(c.id, 'reject')}
                      >
                        Reject
                      </button>
                    </td>
                  )}
                </tr>
              ))}
              {list.length === 0 && (
                <tr>
                  <td colSpan={filter === 'pending' ? 7 : 6} className="empty">
                    No {filter} redemptions.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
