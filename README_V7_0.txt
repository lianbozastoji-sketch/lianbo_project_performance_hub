LIANBO PROJECT PERFORMANCE HUB
Version: v7.0_data_engine_global_refresh

WHAT CHANGED
============
1. GLOBAL REFRESH
   The sidebar button is now "Osveži sve module".
   It invalidates data and resource caches for the complete application:
   - Work Tickets / Kanban
   - KPI Process
   - Technician Evaluation
   - BN
   - OEE
   - Bottleneck
   - Line Verification
   - Administration
   - ALL_ACTIVITIES synchronization

2. LOGIN IS PRESERVED
   Global refresh does not remove:
   - authenticated user
   - permissions
   - selected module
   - Remember me browser cookie

3. GOOGLE SHEETS OPTIMIZATION
   Spreadsheet objects are opened through one cached resource layer.
   Repeated open_by_key calls were removed from the main application.
   Frequently used master data has a longer cache TTL to reduce API quota usage.

4. COMPLETE CACHE REBUILD
   Global refresh clears:
   - st.cache_data
   - st.cache_resource
   - ALL_ACTIVITIES sync markers
   - automatic alert check markers
   - task status synchronization markers
   - module-specific cache markers

5. REFRESH FEEDBACK
   After refresh the application shows a success toast and stores the local
   Europe/Belgrade refresh timestamp in the sidebar.

INSTALLATION
============
Replace these files in the GitHub repository:
- lianbo_project_performance_hub.py
- activity_data_layer.py
- email_service.py
- requirements.txt

Then reboot the Streamlit app.

EXPECTED HEADER
===============
Version: v7.0_data_engine_global_refresh

IMPORTANT
=========
No Google Sheet structure or existing data is changed by this update.
The GitHub Actions wake scheduler remains unchanged.
