// Shared period vocabulary, imported from the repo-root config/periods.json.
// Source of truth: config/periods.json. The Python side reads the same file
// via config/periods.py.
//
// NOTE: vite.config.js must include `server.fs.allow: [__dirname, repoRoot]`
// for this cross-boundary import to resolve. Without it, `npm run dev`
// returns 403 and `npm run build` errors at module-resolve time.
import PERIODS from '../../../config/periods.json'

export const HISTORICAL_PERIODS = Object.freeze(PERIODS.historical)
export const INTRADAY_PERIODS = Object.freeze(PERIODS.intraday)
export const INTRADAY_TO_HISTORY = Object.freeze(PERIODS.intraday_to_history)
export const INTRADAY_KEYS = new Set(INTRADAY_PERIODS)
