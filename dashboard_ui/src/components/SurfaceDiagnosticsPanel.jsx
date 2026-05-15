import { useState } from 'react'

/**
 * Collapsible diagnostics panel — surfaces parity (R², residual_std),
 * model params (SSVI θ_T, ρ, η, γ, butterfly margin OR SABR α, β, ρ, ν),
 * RND sanity (∫q, E[K]−F, n_neg_clipped), and arbitrage diagnostics
 * (Durrleman g_min, Lee wing slopes).
 *
 * Hidden by default; click the chevron to expand.
 */
export default function SurfaceDiagnosticsPanel({ surface }) {
  const [open, setOpen] = useState(false)
  if (!surface) return null

  const fmt = (v, digits = 4) =>
    v == null || !isFinite(v) ? '—' : Number(v).toFixed(digits)

  const fmtPct = (v, digits = 2) =>
    v == null || !isFinite(v) ? '—' : `${(v * 100).toFixed(digits)}%`

  const integralOK = Math.abs((surface.arbitrage?.integral_q ?? 0) - 1) < 1e-3
  const meanOK = Math.abs(surface.arbitrage?.mean_recovery_pct ?? 0) < 0.1
  const durrlemanOK = (surface.arbitrage?.durrleman_min ?? -1) > -1e-3

  return (
    <div className="bg-gray-800 rounded-lg p-3 border border-gray-700 text-xs">
      <button
        onClick={() => setOpen(v => !v)}
        className="flex items-center gap-2 text-gray-300 hover:text-white"
      >
        <span>{open ? '▼' : '▶'}</span>
        <span className="font-semibold">Diagnostics</span>
        <span className="text-gray-500">
          {' '}— RMSE {fmt(surface.ssvi?.rmse_iv ?? surface.sabr?.rmse_iv, 5)} · ∫q{' '}
          {integralOK ? '✓' : '⚠'} {fmt(surface.arbitrage?.integral_q, 4)} · E[K]−F{' '}
          {meanOK ? '✓' : '⚠'} {fmt(surface.arbitrage?.mean_recovery_pct, 3)}%
        </span>
      </button>
      {open && (
        <div className="mt-3 grid grid-cols-2 lg:grid-cols-4 gap-x-4 gap-y-2 text-gray-400">
          <Section title="Parity">
            <Row label="F" value={fmt(surface.F, 4)} />
            <Row label="r (SOFR)" value={fmtPct(surface.r, 3)} />
            <Row label="r_implied" value={fmtPct(surface.parity?.r_implied_raw, 3)} />
            <Row label="D" value={fmt(surface.D, 6)} />
            <Row label="R²" value={fmt(surface.parity?.r2, 6)} />
            <Row label="Residual σ" value={fmt(surface.parity?.residual_std, 4)} />
            <Row label="n_strikes" value={surface.parity?.n_strikes ?? '—'} />
          </Section>
          {surface.model === 'ssvi' && surface.ssvi && (
            <Section title="SSVI">
              <Row label="θ_T" value={fmt(surface.ssvi.theta_T, 5)} />
              <Row label="ρ" value={fmt(surface.ssvi.rho, 3)} />
              <Row label="η" value={fmt(surface.ssvi.eta, 3)} />
              <Row label="γ" value={fmt(surface.ssvi.gamma, 3)} />
              <Row label="RMSE_IV" value={fmt(surface.ssvi.rmse_iv, 5)} />
              <Row label="Butterfly margin" value={fmt(surface.ssvi.butterfly_margin, 3)} />
              <Row label="n_obs" value={surface.ssvi.n_obs} />
            </Section>
          )}
          {surface.model === 'sabr' && surface.sabr && (
            <Section title="SABR">
              <Row label="α" value={fmt(surface.sabr.alpha, 4)} />
              <Row label="β" value={fmt(surface.sabr.beta, 2)} />
              <Row label="ρ" value={fmt(surface.sabr.rho, 3)} />
              <Row label="ν" value={fmt(surface.sabr.nu, 3)} />
              <Row label="RMSE_IV" value={fmt(surface.sabr.rmse_iv, 5)} />
              <Row label="n_obs" value={surface.sabr.n_obs} />
            </Section>
          )}
          <Section title="RND sanity">
            <Row label="∫q dK" value={fmt(surface.arbitrage?.integral_q, 5)} />
            <Row label="E[K]−F" value={fmt(surface.arbitrage?.mean_recovery_pct, 3) + '%'} />
            <Row label="n_neg_clipped" value={surface.arbitrage?.n_neg_clipped ?? 0} />
          </Section>
          <Section title="No-arb">
            <Row
              label="Durrleman min"
              value={
                durrlemanOK
                  ? `${fmt(surface.arbitrage?.durrleman_min, 4)} ✓`
                  : `${fmt(surface.arbitrage?.durrleman_min, 4)} ⚠`
              }
            />
            <Row label="Lee left slope" value={fmt(surface.arbitrage?.lee_left, 3)} />
            <Row label="Lee right slope" value={fmt(surface.arbitrage?.lee_right, 3)} />
          </Section>
        </div>
      )}
    </div>
  )
}

function Section({ title, children }) {
  return (
    <div>
      <div className="text-gray-300 font-semibold mb-1">{title}</div>
      <div className="space-y-1">{children}</div>
    </div>
  )
}

function Row({ label, value }) {
  return (
    <div className="flex justify-between">
      <span>{label}</span>
      <span className="font-mono text-white">{value}</span>
    </div>
  )
}
