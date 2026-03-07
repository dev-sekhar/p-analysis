# Portfolio Dashboard - Future Enhancements (TODO)

This document tracks potential future enhancements to transition the dashboard from a stateless point-in-time analyzer to a stateful time-series historical tracker.

## 1. Persistent Storage Implementation
- [ ] Evaluate and select a lightweight local database (SQLite) or structured file format (Parquet, Master CSV).
- [ ] Design the database schema/file structure to store data persistently (e.g., a `holdings_history` table).

## 2. Daily Snapshot & Data Ingestion System
- [ ] Develop a mechanism to read the uploaded Summary CSV.
- [ ] Add a `Snapshot_Date` column to the parsed data, stamped with the current date (or extract from the file if possible).
- [ ] Implement logic to append this new daily snapshot data block into the persistent storage (e.g., `holdings_history` table).

## 3. Time-Series Analytics Engine
- [ ] **Total Portfolio Trend:** Implement a query to calculate the sum of `Market Value` grouped by `Snapshot_Date`.
- [ ] Create a continuous line chart visualization of total portfolio wealth over time.
- [ ] **P/L Trajectory:** Track and visualize daily movements of `Unrealized P/L %` using an area chart.
- [ ] **Allocation Drift:** Create visualizations (e.g., stacked area chart) to show how the percentage weights of top holdings expand/contract over time.

## 4. Handling Missing Data (Gaps in Uploads)
- [ ] Implement mathematical backfilling (forward fill/interpolation) using historical closing prices from Yahoo Finance to estimate portfolio value on days where a CSV was not uploaded.
  *OR*
- [ ] Implement sparse plotting logic to only draw charts connecting the specific dates where data was uploaded.

## 5. Fully Automated Evolution (Long-term)
- [ ] Investigate broker API availability and capabilities.
- [ ] Develop a background script or task scheduler (e.g., running daily at 4:30 PM post-market close) to automatically pull holdings and log them into the database, eliminating the need for manual CSV uploads.
