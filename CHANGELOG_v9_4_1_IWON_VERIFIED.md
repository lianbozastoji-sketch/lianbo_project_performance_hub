# v9.4.1 – OEE IWON verified build

## Verification corrections
- Weekly **OEE IWON is now strictly read-only**. Opening the IWON metric never recalculates or writes Google Sheets.
- IWON generation/refresh is restricted to **Administration → OEE IWON Targets**.
- Added a **CW01–CW53 yearly target editor** per Year + Project + Process.
- Added **Generate / Refresh IWON** for the selected CW. It reloads the latest real OEE data before calculation.
- Added a **GLOBAL** process scenario that follows the existing `Machine = Sve` rule: it is calculated from summed raw process data, not from an average of machine OEE values.
- Individual machine target scenarios are also stored for machine-level selection.
- IWON result writes are now **row-scoped**. The application no longer clears the entire `OEE_IWON` worksheet, protecting formulas/charts/analysis elsewhere in the spreadsheet.
- A/P/Q target calculation uses the same proportional balancing concept but allows components up to 100%, consistent with the existing OEE component rules. Target OEE remains limited to 99%.
- IWON view still shows **target values only**: OEE IWON, Availability, Performance and Q-rate. No Actual, gap or Improvement values are displayed.
- Added IWON unit/static tests.

## Validation
- Python compile check: PASS.
- Automated tests: **10/10 PASS**.
- Existing Machine OEE / Plant OEE calculation code remains unchanged.
