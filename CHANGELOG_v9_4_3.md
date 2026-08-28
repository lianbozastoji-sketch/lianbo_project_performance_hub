# v9.4.3 — IWON weekly generation diagnostics / robustness

- Fixed misleading IWON error handling: missing weekly OEE data is no longer reported as a Google Sheet permission problem.
- `Generate / Refresh IWON` now reports the real reason when a CW cannot be generated.
- If the selected CW has no OEE_INPUT rows, the app explicitly says the week has no actual Machine OEE data.
- If the CW has data but not for the selected Project / Process, the app shows the available Project / Process combinations for that week.
- IWON matching for Project and Process is now whitespace-trimmed and case-insensitive, improving compatibility with historical naming/capitalization differences.
- Google Spreadsheet / worksheet / API errors remain separately identified without exposing a traceback.
- Existing OEE, IWON targets/results structure, Work Tickets, and v9.4.2 shift-selection behavior are unchanged.
