# Florin Terminal — Frontend

React 19 + Vite 8 + TailwindCSS 4 single-page application for the Florin Terminal dashboard.

## Development

```bash
# Install dependencies
npm install

# Start dev server with hot reload (proxies API to http://localhost:8000)
npm run dev
```

Dev server runs at `http://localhost:5173`.

## Production Build

```bash
# Build and copy to dashboard/static/ for FastAPI to serve
npm run build
```

The build output is served by FastAPI at `http://localhost:8000`.

## Stack

- **React 19** with React Router 7 (SPA routing)
- **Vite 8** (build tooling)
- **TailwindCSS 4** (utility-first CSS)
- **Recharts** (charting library)
- **Colorblind-safe palette** via `useChartColors()` context hook

## Project Structure

```
src/
├── App.jsx              # Root routes and navigation
├── pages/               # Route-level page components
├── components/          # Reusable UI components
├── hooks/               # Custom hooks (useApi, useChartColors, etc.)
└── utils/               # Shared utilities (colors, formatting)
```
