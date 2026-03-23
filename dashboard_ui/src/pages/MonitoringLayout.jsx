import TabLayout from '../components/TabLayout'

const TABS = [
  { path: '/monitoring/watchlist', label: 'Watchlist' },
  { path: '/monitoring/live', label: 'Live Monitor' },
]

export default function MonitoringLayout() {
  return <TabLayout title="Monitoring" tabs={TABS} />
}
