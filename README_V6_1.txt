Lianbo Project Performance Hub v6.1 - Supervisor and Missing Penalty Fix

Changes:
1. Technicians.Supervisor is now supported.
2. Supervisor=YES means alert-only:
   - receives e-mails according to Receive_* columns;
   - is excluded from Missing Work Time checks;
   - is excluded from Missing Work Time penalties;
   - is excluded from the active technician list used for technician evaluation.
3. Administration > Technician form now includes "Supervisor / Alert only".
4. Missing Work Time penalty reads fresh MISSING_WORK_TIME data.
5. Penalty matching is robust by Technician_ID and normalized technician name.
6. Duplicate missing-date rows do not create duplicate penalties.
7. Months with missing entries but no activity are retained in Technician Evaluation.
8. Version label: v6.1_supervisor_penalty_fix

Upload/replace these files in GitHub:
- lianbo_project_performance_hub.py
- activity_data_layer.py
- email_service.py
- requirements.txt

Then reboot the Streamlit app.
