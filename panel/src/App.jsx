import { useEffect, useState } from 'react'
import Dashboard from './tabs/Dashboard.jsx'
import Schemes from './tabs/Schemes.jsx'
import Claims from './tabs/Claims.jsx'
import Customers from './tabs/Customers.jsx'
import Products from './tabs/Products.jsx'
import Gifts from './tabs/Gifts.jsx'
import Redemptions from './tabs/Redemptions.jsx'
import Distributors from './tabs/Distributors.jsx'
import Manufacturers from './tabs/Manufacturers.jsx'
import Login from './Login.jsx'
import { getUser, getToken, clearSession, post } from './api.js'

const MANUF_TABS = [
  { id: 'dashboard', label: 'Dashboard', component: Dashboard },
  { id: 'customers', label: 'Customers', component: Customers },
  { id: 'distributors', label: 'Distributors', component: Distributors },
  { id: 'products', label: 'Products', component: Products },
  { id: 'schemes', label: 'Schemes', component: Schemes },
  { id: 'gifts', label: 'Gifts', component: Gifts },
  { id: 'claims', label: 'Claims', component: Claims },
  { id: 'redemptions', label: 'Redemptions', component: Redemptions },
]

const ADMIN_TABS = [
  { id: 'manufacturers', label: 'Manufacturers', component: Manufacturers },
]

export default function App() {
  const [user, setUser] = useState(() => (getToken() ? getUser() : null))
  const tabs = user?.is_admin ? ADMIN_TABS : MANUF_TABS
  const [tab, setTab] = useState(tabs[0].id)

  useEffect(() => {
    const onLogout = () => setUser(null)
    window.addEventListener('vl-logout', onLogout)
    return () => window.removeEventListener('vl-logout', onLogout)
  }, [])

  if (!user) {
    return (
      <Login
        onLogin={(u) => {
          setUser(u)
          setTab(u.is_admin ? 'manufacturers' : 'dashboard')
        }}
      />
    )
  }

  const logout = async () => {
    try {
      await post('/auth/logout')
    } catch { /* token already dead */ }
    clearSession()
    setUser(null)
  }

  const Active = (tabs.find((t) => t.id === tab) ?? tabs[0]).component

  return (
    <div className="shell">
      <header className="masthead">
        <div className="brand">
          <span className="brand-mark">वस्त्र</span>
          <div>
            <h1>{user.display_name}</h1>
            <p className="brand-sub">
              {user.is_admin ? 'Super Admin' : 'Loyalty Panel'}
            </p>
          </div>
        </div>
        <nav className="tabs">
          {tabs.map((t) => (
            <button
              key={t.id}
              className={tab === t.id ? 'tab active' : 'tab'}
              onClick={() => setTab(t.id)}
            >
              {t.label}
            </button>
          ))}
          <button className="tab logout" onClick={logout}>
            Log out
          </button>
        </nav>
      </header>
      <main className="content">
        <Active />
      </main>
      <footer className="footer">
        Loyalty QR API · scans recorded from YourApp · codes generated in Vastra
      </footer>
    </div>
  )
}
