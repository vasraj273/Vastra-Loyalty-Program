// Client-side CSV export. No dependency — builds an RFC-4180 string from
// already-loaded rows and triggers a browser download. Shared by every data
// tab (Customers, Distributors, Products, Gifts, Claims, Redemptions).

// Quote a single field only when it contains a comma, quote, or newline; inner
// quotes are doubled per RFC 4180.
function escapeField(value) {
  if (value == null) return ''
  const s = String(value)
  return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
}

// columns: [{ key, label, format? }]  — `format(row)` overrides `row[key]`.
// rows:    array of plain objects.
export function toCSV(columns, rows) {
  const header = columns.map((c) => escapeField(c.label)).join(',')
  const body = rows
    .map((row) =>
      columns
        .map((c) => escapeField(c.format ? c.format(row) : row[c.key]))
        .join(','),
    )
    .join('\r\n')
  return `${header}\r\n${body}`
}

// Build the CSV and save it as `filename`. A leading BOM makes Excel open
// UTF-8 (₹, accented names) correctly.
export function downloadCSV(filename, columns, rows) {
  const csv = toCSV(columns, rows)
  const blob = new Blob(['﻿', csv], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

// `YYYY-MM-DD` stamp for export filenames.
export const today = () => new Date().toISOString().slice(0, 10)
