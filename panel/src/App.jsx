import { useEffect, useRef, useState } from 'react'
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
  const [menuOpen, setMenuOpen] = useState(false)
  const menuRef = useRef(null)

  useEffect(() => {
    const onLogout = () => setUser(null)
    window.addEventListener('vl-logout', onLogout)
    return () => window.removeEventListener('vl-logout', onLogout)
  }, [])

  // Close the menu on outside click or Escape.
  useEffect(() => {
    if (!menuOpen) return undefined
    const onDoc = (e) => {
      if (menuRef.current && !menuRef.current.contains(e.target)) setMenuOpen(false)
    }
    const onEsc = (e) => e.key === 'Escape' && setMenuOpen(false)
    document.addEventListener('mousedown', onDoc)
    document.addEventListener('keydown', onEsc)
    return () => {
      document.removeEventListener('mousedown', onDoc)
      document.removeEventListener('keydown', onEsc)
    }
  }, [menuOpen])

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

  const activeTab = tabs.find((t) => t.id === tab) ?? tabs[0]
  const Active = activeTab.component

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
        <div className="nav-menu" ref={menuRef}>
          <button
            className={menuOpen ? 'burger open' : 'burger'}
            onClick={() => setMenuOpen((o) => !o)}
            aria-haspopup="menu"
            aria-expanded={menuOpen}
            aria-label="Open menu"
          >
            <span className="burger-current">{activeTab.label}</span>
            <span className="burger-lines" aria-hidden="true">
              <i /><i /><i />
            </span>
          </button>
          {menuOpen && (
            <div className="menu-pop" role="menu">
              {tabs.map((t) => (
                <button
                  key={t.id}
                  role="menuitem"
                  className={tab === t.id ? 'menu-item active' : 'menu-item'}
                  onClick={() => {
                    setTab(t.id)
                    setMenuOpen(false)
                  }}
                >
                  {t.label}
                </button>
              ))}
              <div className="menu-sep" />
              <button
                className="menu-item logout"
                role="menuitem"
                onClick={() => {
                  setMenuOpen(false)
                  logout()
                }}
              >
                Log out
              </button>
            </div>
          )}
        </div>
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
