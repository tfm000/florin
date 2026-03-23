import TabLayout from '../components/TabLayout'

const TABS = [
  { path: '/trading', label: 'Overview', end: true },
  { path: '/trading/account', label: 'Account' },
  { path: '/trading/trades', label: 'Trades' },
  { path: '/trading/stats', label: 'Stats' },
  { path: '/trading/screeners', label: 'Screeners' },
  { path: '/trading/settings', label: 'Settings' },
]

export default function TradingLayout() {
  return <TabLayout title="Trading" tabs={TABS} />
}
