LIANBO PROJECT PERFORMANCE HUB
Version: v8.5_penalty_engine_fix

FIX
===
The Missing Work Time penalty engine was rewritten to read the sheet directly
and robustly.

Accepted MISSING_WORK_TIME header variants include:
- Technician_ID
- Technician_Name / Technician_Nam / Technician
- Missing_Date / Date
- Note / Notes

Technician IDs are normalized, so TECH-000002, TECH 000002 and TECH_000002 map
to the same technician.

Rules:
- Duplicate Technician_ID + Missing_Date rows count once.
- Latest row wins, so an admin Note immediately changes the record to justified.
- Blank Note = unjustified.
- Non-empty Note = justified.
- Weekend dates are ignored.
- First five unjustified dates per month = 0.5 points each.
- Additional dates = 1.0 point each.

An admin-only diagnostics expander was added under Missing Entry Penalty.

INSTALLATION
============
Replace:
- lianbo_project_performance_hub.py
- activity_data_layer.py
- email_service.py
- requirements.txt

Then reboot the Streamlit app and click "Osveži sve module".

EXPECTED HEADER
===============
Version: v8.5_penalty_engine_fix
