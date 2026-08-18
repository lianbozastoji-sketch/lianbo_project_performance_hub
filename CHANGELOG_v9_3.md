# v9.3 Turbo / OEE shifts / per-user permissions

This package is based directly on `Lianbo_Project_Performance_Hub_COMPLETE_v9_2.zip`.

## OEE

- Replaced the free `Number of shifts` UI with exact shift choices:
  - `1st shift (06:00-14:00)`
  - `2nd shift (14:00-22:00)`
  - `3rd shift (22:00-06:00)`
  - `All shifts`
- `All shifts` asks for 1, 2 or 3 shifts.
- Individual shifts always use one `MASTER_DATA / 1 shift` Open time.
- Duplicate key is now Date + Project + Process + Machine + Shift.
- Individual shifts can coexist. `All shifts` cannot be mixed with individual rows for the same daily key, which prevents double counting.
- Existing rows with a blank Shift are treated as `All shifts`.
- Daily and longer-period metrics are calculated from summed raw Open time, losses, OK/NOK and Target values.

## Per-user access

- Administration -> Users & Passwords now includes individual View and Edit/Input settings for every main module.
- Each setting can use `Role default`, `Allowed` or `Blocked`.
- Per-user overrides work independently of the selected role.
- View-blocked modules are hidden and direct access is rejected.
- Edit-blocked users receive read-only screens; application writes are removed/disabled for Work Tickets, KPI Admin/Alerts, BN, OEE and Administration.

## Notifications

- User administration includes task e-mail, task reminder, missing-time and BN notification switches.
- Active recipients are combined and de-duplicated from `Technicians` and `User&Password`.
- Explicit per-user task e-mail opt-out is respected for assignment and completion e-mails.

## Turbo

- Normal page loads no longer run ALL_ACTIVITIES synchronization and all scheduled e-mail checks before login.
- GitHub Actions uses the separate `?automation=1` route for synchronization and alerts.
- Plotly and the e-mail service are imported only when needed.
- Spreadsheet and worksheet handles are reused.
- Google Sheets reads have a longer cache and faster controlled request cadence.
- KPI/BN automatic sync is background-managed; authorized users still have manual sync controls.
- Multi-cell updates use batch requests and OEE calculations are vectorized.

## Automatic sheet migration

- `OEE_input`: a `Shift` column is appended; legacy columns and rows are not moved.
- `User&Password`: missing `View_*`, `Edit_*` and `Receive_*` columns are appended when Administration loads.
- Blank `View_*`/`Edit_*` means role default, preserving existing role behavior.
