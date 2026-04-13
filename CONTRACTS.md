# Oracle Labs V2 — Contracts & Schedules

## Forecast Cycle

The main forecast pipeline runs **every 4 hours** via GitHub Actions (`5 */4 * * *`):

> 00:05, 04:05, 08:05, 12:05, 16:05, 20:05 UTC

Each cycle: gathers news → updates state → fetches rolling contracts → pulls market data (Hyperliquid, weather, GDELT, order flow) → runs LLM forecasts → runs agent forecasts → evaluates → reports.

**Agent iteration** runs once daily at **05:00 UTC** to update agent weights and the LLM forecaster.

---

## Static Contracts

### Geopolitics — reforecast every 12h

| # | Contract | Type | End Date |
|---|----------|------|----------|
| 1 | US-Iran nuclear deal before 2027 | Binary | 2026-12-31 |
| 2 | US-Iran nuclear deal by April 30 | Binary | 2026-04-30 |
| 3 | Strait of Hormuz traffic normalizes by April 30 | Binary | 2026-04-30 |
| 4 | Will Iran close the Strait of Hormuz | Multi-outcome | 2026-12-31 |
| 5 | Which world leaders will leave office | Multi-outcome | 2026-12-31 |
| 6 | SAVE Act becomes law in 2026 | Binary | 2026-12-31 |

### Economics — reforecast every 12h

| # | Contract | Type | End Date |
|---|----------|------|----------|
| 7 | US recession by end of 2026 | Binary | 2027-01-31 |
| 8 | Fed decision in April | Multi-outcome | 2026-04-29 |
| 9 | CPI year-over-year in March | Multi-outcome | 2026-04-10 |
| 10 | Bitcoin price targets 2026 | Binary | 2027-01-01 |
| 11 | Gas prices end of March | Binary | 2026-03-31 |

### Politics — reforecast every 12h

| # | Contract | Type | End Date |
|---|----------|------|----------|
| 12 | Powell out as Fed chair | Binary | 2026-05-14 |
| 13 | Who will be confirmed as Fed Chair | Multi-outcome | 2026-10-31 |
| 14 | 2026 midterms — House winner | Multi-outcome | 2026-11-03 |
| 15 | 2026 midterms — Balance of Power | Binary | 2026-11-03 |

### Sports — reforecast every 24h

| # | Contract | Type | End Date |
|---|----------|------|----------|
| 16 | FIFA World Cup 2026 winner | Multi-outcome | 2026-07-20 |
| 17 | NBA Finals 2026 winner | Multi-outcome | 2026-07-01 |

### Tech — reforecast every 24h

| # | Contract | Type | End Date |
|---|----------|------|----------|
| 18 | Top AI model this month | Multi-outcome | 2026-03-31 |
| 19 | Best AI coding model end of March | Multi-outcome | 2026-03-31 |
| 20 | US confirms aliens exist before 2027 | Binary | 2026-12-31 |

### Entertainment — reforecast every 24h (except Survivor)

| # | Contract | Type | End Date | Frequency |
|---|----------|------|----------|-----------|
| 21 | Survivor season 50 winner | Multi-outcome | 2026-05-20 | Weekly |
| 22 | Stranger Things new episode release date | Binary | 2026-01-07 | Every 24h |
| 23 | GTA 6 launch postponed again | Binary | 2026-11-19 | Every 24h |

---

## Rolling Daily Contracts — reforecast once each morning

These are generated fresh each day with the date baked into the slug.

| Contract | Slug Template | Type |
|----------|---------------|------|
| Bitcoin Up or Down | `bitcoin-up-or-down-on-{month}-{day}-{year}` | Binary |
| Crude Oil (CL) Up or Down | `cl-up-or-down-on-{month}-{day}-{year}` | Binary |
| Highest temperature in NYC | `highest-temperature-in-nyc-on-{month}-{day}-{year}` | Multi-outcome |
| Highest temperature in Miami | `highest-temperature-in-miami-on-{month}-{day}-{year}` | Multi-outcome |

---

## Reforecast Frequency Summary

| Frequency | Count | Categories |
|-----------|-------|------------|
| Every 12h | 15 | Geopolitics, Economics, Politics |
| Every 24h | 7 | Sports, Tech, Entertainment |
| Once each morning | 4 | Rolling daily (Bitcoin, Oil, Weather) |
| Once per week | 1 | Survivor |
| **Total** | **27** | |
