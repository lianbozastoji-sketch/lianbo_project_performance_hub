LIANBO PROJECT PERFORMANCE HUB
Version: v8.2_bn_station_quota_fix

FIXES
=====
1. Added Station to BN_RECORDS.
2. BN Entry now has a mandatory Station text field (examples: OP100, OP200).
3. Last saved Station is proposed together with the last BN value.
4. Google Forms Station is migrated into BN_RECORDS.
5. BN dashboard displays Station.
6. Google Sheets 429 handling now retries with exponential backoff.
7. BN Forms synchronization is throttled to once per 30 minutes per session.
8. Removed duplicate BN Forms synchronization during the same page render.
9. Existing BN_RECORDS rows are updated across columns A:N.

REQUIRED BN_RECORDS HEADER
==========================
BN_ID | Source | Source_ID | Date | Machine_ID | Project | Machine | BN_Time |
Station | Entered_By | Entered_By_Username | Entered_By_Email | Created_At | Updated_At

INSTALLATION
============
Replace these files in GitHub:
- lianbo_project_performance_hub.py
- activity_data_layer.py
- email_service.py
- requirements.txt

Then reboot the Streamlit app.

EXPECTED HEADER
===============
Version: v8.2_bn_station_quota_fix
