/**
 * Shared exchange constants used across the application.
 *
 * Each entry maps a yfinance exchange code to a human-readable label and region.
 * EXCHANGE_GROUPS bundles related codes under a single market name for
 * multi-select UIs (e.g. market breadth).
 */

export const EXCHANGES = [
  { value: 'NMS', label: 'NASDAQ GS', region: 'us' },
  { value: 'NGM', label: 'NASDAQ GM', region: 'us' },
  { value: 'NCM', label: 'NASDAQ CM', region: 'us' },
  { value: 'NYQ', label: 'NYSE', region: 'us' },
  { value: 'PCX', label: 'NYSE Arca', region: 'us' },
  { value: 'ASE', label: 'NYSE American', region: 'us' },
  { value: 'BTS', label: 'BATS', region: 'us' },
  { value: 'PNK', label: 'OTC (Pink/ADRs)', region: 'us' },
  { value: 'OQB', label: 'OTC (QB Tier)', region: 'us' },
  { value: 'OQX', label: 'OTC (QX Tier)', region: 'us' },
  { value: 'LSE', label: 'London', region: 'gb' },
  { value: 'IOB', label: 'Intl. Order Book', region: 'gb' },
  { value: 'TOR', label: 'Toronto (TSX)', region: 'ca' },
  { value: 'VAN', label: 'TSX Venture', region: 'ca' },
  { value: 'CNQ', label: 'CSE', region: 'ca' },
  { value: 'GER', label: 'XETRA', region: 'de' },
  { value: 'FRA', label: 'Frankfurt', region: 'de' },
  { value: 'JPX', label: 'Tokyo (JPX)', region: 'jp' },
  { value: 'HKG', label: 'HKEX', region: 'hk' },
  { value: 'ASX', label: 'ASX', region: 'au' },
  { value: 'NSI', label: 'NSE India', region: 'in' },
  { value: 'BSE', label: 'BSE India', region: 'in' },
  { value: 'PAR', label: 'Euronext Paris', region: 'fr' },
  { value: 'AMS', label: 'Euronext Amsterdam', region: 'nl' },
  { value: 'BRU', label: 'Euronext Brussels', region: 'be' },
  { value: 'LIS', label: 'Euronext Lisbon', region: 'pt' },
  { value: 'MIL', label: 'Borsa Italiana', region: 'it' },
  { value: 'MAD', label: 'BME Madrid', region: 'es' },
  { value: 'STO', label: 'Nasdaq Stockholm', region: 'se' },
  { value: 'EBS', label: 'SIX Swiss', region: 'ch' },
  { value: 'SES', label: 'SGX', region: 'sg' },
  { value: 'KSC', label: 'KOSPI', region: 'kr' },
  { value: 'KOE', label: 'KOSDAQ', region: 'kr' },
  { value: 'SAO', label: 'B3 (Bovespa)', region: 'br' },
  { value: 'MEX', label: 'BMV Mexico', region: 'mx' },
  { value: 'TAI', label: 'TWSE', region: 'tw' },
  { value: 'TWO', label: 'TPEx', region: 'tw' },
  { value: 'NZE', label: 'NZX', region: 'nz' },
]

/** Market-level groups mapping a display name to its constituent exchange codes. */
export const EXCHANGE_GROUPS = [
  { label: 'NASDAQ', codes: ['NMS', 'NGM', 'NCM'] },
  { label: 'NYSE', codes: ['NYQ'] },
  { label: 'AMEX', codes: ['ASE'] },
  { label: 'NYSE Arca', codes: ['PCX'] },
  { label: 'OTC', codes: ['PNK', 'OQB', 'OQX'] },
  { label: 'London', codes: ['LSE', 'IOB'] },
  { label: 'Toronto', codes: ['TOR', 'VAN'] },
  { label: 'XETRA', codes: ['GER', 'FRA'] },
  { label: 'Euronext', codes: ['PAR', 'AMS', 'BRU', 'LIS'] },
  { label: 'Tokyo', codes: ['JPX'] },
  { label: 'HKEX', codes: ['HKG'] },
  { label: 'ASX', codes: ['ASX'] },
  { label: 'India', codes: ['NSI', 'BSE'] },
  { label: 'Borsa Italiana', codes: ['MIL'] },
  { label: 'BME Madrid', codes: ['MAD'] },
  { label: 'Nasdaq Stockholm', codes: ['STO'] },
  { label: 'SIX Swiss', codes: ['EBS'] },
  { label: 'SGX', codes: ['SES'] },
  { label: 'Korea', codes: ['KSC', 'KOE'] },
  { label: 'B3 (Brazil)', codes: ['SAO'] },
  { label: 'BMV Mexico', codes: ['MEX'] },
  { label: 'Taiwan', codes: ['TAI', 'TWO'] },
  { label: 'NZX', codes: ['NZE'] },
]

/** Flat label lookup: exchange code or comma-joined codes -> display name. */
export const EXCHANGE_LABELS = {
  'NMS,NGM,NCM': 'NASDAQ', NYQ: 'NYSE', PCX: 'NYSE Arca',
  ASE: 'NYSE American', BTS: 'BATS', 'PNK,OQB,OQX': 'OTC',
  PAR: 'Euronext Paris', AMS: 'Euronext Amsterdam', BRU: 'Euronext Brussels',
  LIS: 'Euronext Lisbon', MIL: 'Borsa Italiana', MAD: 'BME Madrid',
  STO: 'Nasdaq Stockholm', EBS: 'SIX Swiss', SES: 'SGX',
  KSC: 'KOSPI', KOE: 'KOSDAQ', SAO: 'B3', MEX: 'BMV',
  TAI: 'TWSE', TWO: 'TPEx', NZE: 'NZX',
  LSE: 'London', IOB: 'IOB', TOR: 'TSX', VAN: 'TSX-V', CNQ: 'CSE',
  GER: 'XETRA', FRA: 'Frankfurt', JPX: 'Tokyo', HKG: 'HKEX',
  ASX: 'ASX', NSI: 'NSE', BSE: 'BSE',
}
