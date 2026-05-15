import TabLayout from '../components/TabLayout'

const TABS = [
  { path: '/news', label: 'Feed', end: true },
  { path: '/news/economic', label: 'Economic Calendar' },
  { path: '/news/earnings', label: 'Earnings' },
]

export default function NewsLayout() {
  return <TabLayout title="News & Calendar" tabs={TABS} />
}
