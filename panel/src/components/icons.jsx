// Inline stroke icons for the toolbar buttons and the overflow menu. Kept as
// plain SVG (no icon dependency) and drawn on a 24px grid with currentColor so
// they inherit the button's own colour, including the danger variant.
const Svg = ({ children }) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"
       strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {children}
  </svg>
)

export const IconTransfer = () => (
  <Svg><path d="M4 8h13M14 5l3 3-3 3" /><path d="M20 16H7M10 13l-3 3 3 3" /></Svg>
)

export const IconImport = () => (
  <Svg>
    <path d="M6.5 18a4 4 0 0 1-.3-8 6 6 0 0 1 11.5 1.3A3.5 3.5 0 0 1 17.5 18" />
    <path d="M12 20v-8M9 14l3-3 3 3" />
  </Svg>
)

export const IconExport = () => (
  <Svg><path d="M12 3v11M8 11l4 4 4-4" /><path d="M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" /></Svg>
)

export const IconSample = () => (
  <Svg>
    <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" />
    <path d="M14 3v5h5" /><path d="M12 12v5M9.5 14.5 12 17l2.5-2.5" />
  </Svg>
)

export const IconTrash = () => (
  <Svg>
    <path d="M4 7h16M10 7V5a1 1 0 0 1 1-1h2a1 1 0 0 1 1 1v2" />
    <path d="M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12" />
    <path d="M10 11v6M14 11v6" />
  </Svg>
)

export const IconQr = () => (
  <Svg>
    <rect x="3" y="3" width="7" height="7" rx="1" />
    <rect x="14" y="3" width="7" height="7" rx="1" />
    <rect x="3" y="14" width="7" height="7" rx="1" />
    <path d="M14 14h3v3h-3zM20 14v.01M14 20v.01M20 20v.01M17.5 20.5v.01" />
  </Svg>
)

export const IconDots = () => (
  <Svg>
    <circle cx="12" cy="5" r="1.4" fill="currentColor" />
    <circle cx="12" cy="12" r="1.4" fill="currentColor" />
    <circle cx="12" cy="19" r="1.4" fill="currentColor" />
  </Svg>
)

export const IconPlus = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4"
       strokeLinecap="round" aria-hidden="true">
    <path d="M12 5v14M5 12h14" />
  </svg>
)
