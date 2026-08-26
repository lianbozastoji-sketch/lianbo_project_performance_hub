# v9.4 – OEE IWON

## Added
- New weekly OEE metric: **OEE IWON (Improved Weekly OEE Necessary)**.
- IWON is available in the existing OEE metric dropdown on the **Weekly** page.
- New Administration tab: **OEE IWON Targets**.
- Target definition by **Year + CW + Project + Process** (CW01–CW53).
- Connection to the dedicated IWON spreadsheet:
  - `Admin podešavanja` / `OEE_IWON_TARGETS` – target configuration.
  - `OEE_IWON` – persisted calculated target scenario.
- Balanced target calculator derives necessary Machine Availability, Performance and Quality from the real weekly Machine OEE baseline.
- IWON output is persisted first and the IWON dashboard then reads the result from `OEE_IWON`.
- Existing rows for other weeks/projects/processes are preserved when a selected IWON scenario is recalculated.

## Management-display rule
IWON intentionally displays **only**:
- OEE IWON
- Availability
- Performance
- Q-rate

Actual OEE, actual A/P/Q, gap and improvement are not shown in the IWON view.

## Existing OEE protection
Machine OEE CT, Plant OEE CT, Machine OEE Target and Plant OEE Target formulas were not changed.

## Deployment note
The new IWON Google Spreadsheet must be shared with the same Google service-account e-mail already used by the Streamlit application.
