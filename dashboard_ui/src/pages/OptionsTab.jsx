import { useState, useCallback } from 'react'
import { useOutletContext } from 'react-router-dom'
import OptionsSurfaceChart from '../components/OptionsSurfaceChart'
import GreeksTable from '../components/GreeksTable'

/**
 * Options tab — SSVI/SABR + GP-residual + RND surface chart plus a
 * Greeks table. The risk-free rate is always the externally-resolved
 * SOFR (plumbed through ``surface.r``); the chain-implied rate is
 * preserved on ``surface.parity.r_implied_raw`` as a diagnostic.
 */
export default function OptionsTab() {
  const { ticker } = useOutletContext()
  const [surface, setSurface] = useState(null)

  // The callback ref pattern lets OptionsSurfaceChart push its latest
  // SurfaceFitResponse up here without prop drilling.
  const handleSurfaceLoaded = useCallback(s => setSurface(s), [])

  return (
    <div className="space-y-6">
      <OptionsSurfaceChart initialTicker={ticker} onSurfaceLoaded={handleSurfaceLoaded} />

      {surface && (
        <GreeksTable
          ivCurve={surface.iv_curve}
          spot={surface.spot}
          expiry={surface.expiry}
          riskFreeRate={surface.r}
        />
      )}
    </div>
  )
}
