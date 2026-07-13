Lianbo Project Performance Hub v5.1 - ALL_ACTIVITIES Initialization

ENTRYPOINT
- lianbo_project_performance_hub_v5_1_all_activities_initialization.py

FILES REQUIRED IN THE SAME REPOSITORY FOLDER
- lianbo_project_performance_hub_v5_1_all_activities_initialization.py
- activity_data_layer.py
- email_service.py

FIRST RUN
1. Log in as an administrator.
2. The application detects that all_activities has no data rows.
3. Click "Initialize ALL_ACTIVITIES".
4. The app imports the complete available history from:
   - Google Forms response sheet
   - TASK_ACTIVITY
5. A migration report shows Forms imported, App imported, duplicates skipped, and total rows.
6. After initialization the button disappears and future runs synchronize only new records.

SAFETY
- Existing Forms and TASK_ACTIVITY data are read-only during migration.
- Deterministic Source_ID prevents duplicate imports.
- KPI, Evaluation, and Missing Work Time wait until initialization is complete.
