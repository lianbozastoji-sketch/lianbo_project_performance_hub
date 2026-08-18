# Lianbo Project Performance Hub

Complete replacement package — version `v9.3_turbo_shifts_user_permissions`, built directly on the complete v9.2 package.

This package keeps the existing Google Sheets databases and application functions. Replacing the GitHub code does not delete Google Sheets records.

## What is included

- Main Streamlit application with KPI, Work Tickets/Kanban, BN, OEE, Line Verification and Admin modules.
- OEE input by exact shift: `1st shift (06:00-14:00)`, `2nd shift (14:00-22:00)`, `3rd shift (22:00-06:00)` or `All shifts`.
- `All shifts` asks for 1, 2 or 3 shifts; Open time and Target are calculated from `MASTER_DATA / 1 shift`.
- Daily/weekly/monthly/yearly OEE is calculated from summed raw shift data, not from an average of shift percentages.
- Per-user View/Edit overrides for every main application tab, independent of the user's role.
- Per-user e-mail notification switches for tasks, reminders, missing work time and BN alerts.
- `Technician_ID` as the primary link between Users, Technicians, Tasks and Task Activity.
- Technician-only Work Ticket visibility; admins/managers retain full access.
- Central Google Sheets cache, rate limiting, retry and stale-data fallback.
- Central SMTP service and `EMAIL_LOG` audit worksheet.
- Automatic weekday checks:
  - missing work-time alert for the previous workday after 11:00 Europe/Belgrade;
  - missing BN alert after 11:00 Europe/Belgrade;
  - one BN deviation summary 15 minutes after the latest BN entry;
  - one daily reminder for every task that is not Closed/Completed.
- GitHub Actions workflow that wakes a sleeping Streamlit app and clicks the Streamlit wake prompt when necessary.
- Turbo startup: normal users do not wait for ALL_ACTIVITIES/BN synchronization or scheduled notification checks; these run through the dedicated `?automation=1` background route.

## Clean GitHub replacement

Do not delete the GitHub repository itself. Delete/replace only its files. Deleting the repository also deletes the `STREAMLIT_APP_URL` Action secret and can break the existing Streamlit deployment connection.

1. Extract `Lianbo_Project_Performance_Hub_COMPLETE_v9_3.zip` on the computer.
2. Open the existing GitHub repository on branch `main`.
3. Remove the old repository files, but keep the repository itself.
4. Choose **Add file -> Upload files**.
5. Drag the contents inside the extracted `Lianbo_Project_Performance_Hub_COMPLETE` folder. Do not upload the ZIP itself and do not add an extra outer folder.
6. Confirm that `.github/workflows/wake_streamlit.yml` exists in exactly that path.
7. Commit directly to `main`.

The repository root must contain `lianbo_project_performance_hub.py` and `requirements.txt`.

## Streamlit Community Cloud

- Main file path: `lianbo_project_performance_hub.py`
- Branch: `main`
- Keep the existing Streamlit Secrets. Use `.streamlit/secrets.toml.example` only as a field-name reference.
- Never upload a real `service_account.json`, Gmail password or `secrets.toml` to GitHub.

The optional `project_department.jpg` background is no longer required. If it is absent, the app automatically uses its built-in dark gradient background.

## Required GitHub Actions secret

In the GitHub repository open:

`Settings -> Secrets and variables -> Actions -> New repository secret`

Create or verify:

- Name: `STREAMLIT_APP_URL`
- Value: the complete deployed Streamlit application URL beginning with `https://`

Optional security hardening: set the same `AUTOMATION_TOKEN` value in GitHub Actions secrets and Streamlit Secrets. If it is configured in Streamlit, the background route requires that token.

Then open `Actions -> Wake Streamlit and run alerts -> Run workflow` once manually. A successful run should be green and will upload a short-lived diagnostic screenshot artifact.

## Notification setup inside the application

Both the `Technicians` worksheet and the Administration user form can control notification delivery. The Administration form stores these per-user fields in `User&Password`:

- `Email`
- `Receive_Task_Email`
- `Receive_Task_Reminder`
- `Receive_Missing_Time_Email`
- `Receive_BN_Email`
- `Supervisor`
- `Active`

Only active people whose applicable notification flag is `YES` receive that alert. A person marked `Supervisor=YES` can receive selected alerts but is excluded from missing-time checks and evaluation penalties.

The same user row also stores `View_*` and `Edit_*` columns for Work Tickets, KPI Process, Bottleneck, OEE, Line Verification and Administration. Blank means `Role default`; `YES` and `NO` are individual overrides.

All delivery attempts are recorded in the `EMAIL_LOG` worksheet. Use the Admin/Alerts manual-check buttons for an immediate test.

## Important

- The workflow runs every 15 minutes on weekdays during the configured UTC window.
- GitHub may temporarily delay scheduled workflows; the manual **Run workflow** button remains available.
- The first Google Sheets load can be slower. Repeated navigation uses the shared cache.
- Existing Sheets and their data must not be renamed or deleted.
