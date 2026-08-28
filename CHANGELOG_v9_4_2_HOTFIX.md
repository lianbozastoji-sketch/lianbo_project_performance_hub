# v9.4.2 Hotfix

- Corrected the OEE IWON Google Spreadsheet ID. The previous build used an uppercase `I` where the actual spreadsheet ID contains a lowercase `l`, which caused `SpreadsheetNotFound: 404` despite correct sharing permissions.
- Removed raw exception output from the IWON Administration UI; users now receive a clean error message instead of a full Streamlit traceback for IWON access failures.
