LIANBO STREAMLIT SCHEDULER

PURPOSE
-------
This GitHub Actions workflow opens the Streamlit application with a real
headless Chromium browser. This creates an actual Streamlit session and gives
the application time to execute its automatic Missing Work Time and Missing BN
checks.

FILES
-----
wake_streamlit.py
.github/workflows/wake_streamlit.yml

INSTALLATION
------------
1. Copy both files into the root of the GitHub repository.
   Keep the .github/workflows folder structure exactly as supplied.

2. In GitHub open:
   Repository -> Settings -> Secrets and variables -> Actions

3. Create a new repository secret:
   Name: STREAMLIT_APP_URL
   Value: the full Streamlit URL, for example:
   https://your-app-name.streamlit.app

4. Commit the files.

5. Open the repository Actions tab.
   Select "Wake Streamlit and run alerts".
   Click "Run workflow" once to test it manually.

SCHEDULE
--------
The workflow runs Monday-Friday at:
- 09:05 UTC
- 10:05 UTC

This covers both Serbian summer and winter time. The application itself checks
Europe/Belgrade local time and does nothing before 11:00. EMAIL_LOG must prevent
the same alert from being sent twice.

IMPORTANT
---------
The repository Actions feature must be enabled.
The Streamlit app must contain the automatic checks on application/session load.
Do not put Gmail, Google service-account, or Streamlit secrets in this workflow.
They remain stored in Streamlit Secrets.

TEST
----
After a manual run:
1. Open GitHub -> Actions -> selected run.
2. Confirm "Wake cycle completed."
3. Check the uploaded diagnostic screenshot artifact.
4. Check EMAIL_LOG and received emails.
