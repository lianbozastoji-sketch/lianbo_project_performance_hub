# Lianbo Project Performance Hub

Complete replacement package — version `v9.2_complete_replacement`.

This package keeps the existing Google Sheets databases and application functions. Replacing the GitHub code does not delete Google Sheets records.

## What is included

- Main Streamlit application with KPI, Work Tickets/Kanban, BN, OEE, Line Verification and Admin modules.
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

## Clean GitHub replacement

Do not delete the GitHub repository itself. Delete/replace only its files. Deleting the repository also deletes the `STREAMLIT_APP_URL` Action secret and can break the existing Streamlit deployment connection.

1. Extract `Lianbo_Project_Performance_Hub_COMPLETE.zip` on the computer.
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

Then open `Actions -> Wake Streamlit and run alerts -> Run workflow` once manually. A successful run should be green and will upload a short-lived diagnostic screenshot artifact.

## Notification setup inside the application

The `Technicians` worksheet/admin form uses these fields:

- `Email`
- `Receive_Task_Email`
- `Receive_Task_Reminder`
- `Receive_Missing_Time_Email`
- `Receive_BN_Email`
- `Supervisor`
- `Active`

Only active people whose applicable notification flag is `YES` receive that alert. A person marked `Supervisor=YES` can receive selected alerts but is excluded from missing-time checks and evaluation penalties.

All delivery attempts are recorded in the `EMAIL_LOG` worksheet. Use the Admin/Alerts manual-check buttons for an immediate test.

## Important

- The workflow runs every 15 minutes on weekdays during the configured UTC window.
- GitHub may temporarily delay scheduled workflows; the manual **Run workflow** button remains available.
- The first Google Sheets load can be slower. Repeated navigation uses the shared cache.
- Existing Sheets and their data must not be renamed or deleted.

