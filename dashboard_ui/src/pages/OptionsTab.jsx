import { useOutletContext } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import PutCallIVChart from '../components/PutCallIVChart'
import GreeksTable from '../components/GreeksTable'
import PayoffDiagram from '../components/PayoffDiagram'

export default function OptionsTab() {
  const { ticker } = useOutletContext()
  const { data: ivData, loading } = useApi(`/research/iv-spread?ticker=${ticker}`)

  return (
    <div className="space-y-6">
      {/* IV Smile / Skew Chart + Term Structure */}
      <PutCallIVChart initialTicker={ticker} />

      {/* Greeks Table */}
      {loading && (
        <div className="bg-gray-800 rounded-lg p-8 border border-gray-700 text-center">
          <p className="text-gray-500">Loading options data for {ticker}...</p>
        </div>
      )}

      {!loading && ivData?.skew?.length > 0 && (
        <>
          <GreeksTable
            skew={ivData.skew}
            spot={ivData.spot}
            expiry={ivData.skew_expiry}
          />
          <PayoffDiagram spot={ivData.spot} />
        </>
      )}
    </div>
  )
}
