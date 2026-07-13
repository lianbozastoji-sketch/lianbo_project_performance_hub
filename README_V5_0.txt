Lianbo Project Performance Hub v5.0 — ALL_ACTIVITIES Phase 1

Files that must be committed together:
1. lianbo_project_performance_hub_v5_0_all_activities_phase1.py
2. activity_data_layer.py
3. email_service.py

ALL_ACTIVITIES configuration already included in the main file:
Spreadsheet ID: 1lclk5I5XGil-c-TDJ08WIhkA3Pk0q-kqcBrMxm09i9M
Worksheet: all_activities

Required worksheet columns (A:N):
Activity_ID, Source, Source_ID, Technician_ID, Technician_Name, Work_Date,
Start_Time, End_Time, Calculated_Duration, Effective_Duration, Process,
Task_Title, Task_ID, Imported_At

Behavior:
- Existing Google Forms sheet is read-only and synchronized as Source=FORM.
- Existing TASK_ACTIVITY sheet is read-only and synchronized as Source=APP.
- Deterministic Source_ID prevents duplicate imports.
- KPI Process, Technician Evaluation and Missing Work Time read ALL_ACTIVITIES.
- The Refresh Data button clears caches and runs a fresh synchronization.
- Existing source sheets and historical data are preserved.

Deployment:
Set the Streamlit entrypoint to:
lianbo_project_performance_hub_v5_0_all_activities_phase1.py
