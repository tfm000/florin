import { NavLink, Outlet } from 'react-router-dom'

/**
 * Shared layout for tabbed sub-navigation pages (Monitoring, Trading, etc.).
 *
 * Props:
 *   title — heading text displayed above the tabs
 *   tabs  — array of { path, label, end? } objects for the tab bar
 */
export default function TabLayout({ title, tabs }) {
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-white">{title}</h1>

      <nav className="flex gap-1 border-b border-gray-700" aria-label={`${title} tabs`}>
        {tabs.map(tab => (
          <NavLink
            key={tab.path}
            to={tab.path}
            end={tab.end}
            className={({ isActive }) =>
              `px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
                isActive
                  ? 'border-indigo-500 text-white'
                  : 'border-transparent text-gray-400 hover:text-gray-300 hover:border-gray-600'
              }`
            }
          >
            {tab.label}
          </NavLink>
        ))}
      </nav>

      <Outlet />
    </div>
  )
}
