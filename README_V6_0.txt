LIANBO PROJECT PERFORMANCE HUB v6.0

Entrypoint: lianbo_project_performance_hub.py

Included:
- ALL_ACTIVITIES as the unified source for KPI, Evaluation and Missing Work Time
- Historical and incremental sync from Google Forms and TASK_ACTIVITY
- TASKS.Status as the only Kanban status source
- Completion notifications and duplicate protection through EMAIL_LOG
- Missing Work Time and BN checks (automatic while app is awake + manual Alerts controls)
- Stable KPI single-panel navigation and mobile input fixes
- Real Remember me browser cookie (30 days), signed and containing no password

Upload all files to the same GitHub repository folder and reboot Streamlit Cloud.
The supplied requirements.txt adds extra-streamlit-components for cookie support.
Optional Streamlit secret:
REMEMBER_ME_SECRET = "a-long-random-secret"
If omitted, the app derives a stable signing key from the service-account private key.
