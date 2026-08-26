# v9.4.2 – OEE shift selection + Work Ticket timestamps

## OEE Input
- Replaced the numeric **How many shifts are included?** field for `All shifts`.
- `All shifts` now opens a bordered sub-panel with horizontal multi-select pills: **1st / 2nd / 3rd**.
- `All shifts` requires at least two selected shifts; for a single shift the normal 1st/2nd/3rd selector is used.
- `Number of shifts`, `Open time` and `Target pcs.` are calculated from the number of selected shifts.
- Added `Included_Shifts` as the last `OEE_input` column (R). It is appended automatically; existing A:Q data is not moved or rewritten.
- Individual shift rows store `1st`, `2nd` or `3rd`; combined rows store values such as `1st | 2nd` or `1st | 2nd | 3rd`.
- `Included_Shifts` is available in OEE raw/display data when present.

## Work Tickets
- Completed Kanban cards now show **Started** and **Finished** date/time in addition to Calculated total and Effective total.
- When an activity is saved, TASKS keeps the earliest recorded start time.
- When `Close task after this activity` is used, TASKS stores the actual activity end date/time as the task finish time.
- Historical completed tasks can fall back to TASK_ACTIVITY history, so cards created before v9.4.2 can also show first-start / last-end when activity data exists.

## Preserved behavior
- OEE IWON v9.4.1 logic remains unchanged.
- Machine OEE / Plant OEE formulas remain unchanged.
- Existing Work Ticket duration and ENVA calculations remain unchanged.
- Existing Google Sheets records are preserved.

## Validation
- Python compile check: PASS.
- Automated tests: **14/14 PASS**.
