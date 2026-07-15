LIANBO PROJECT PERFORMANCE HUB
Version: v8.3_bn_master_header_fix

FIX
===
BN_MACHINES now reads headers case-insensitively.

The following header variants are accepted:
- Machine_ID / machine_id / MACHINE_ID
- Project / project / PROJECT
- Machine / machine / MACHINE
- Active / active / ACTIVE

This fixes the case where the Google Sheet contained:
Machine_ID | project | machine | active

but the application expected:
Machine_ID | Project | Machine | Active

BN_RECORDS headers are also normalized case-insensitively.

No Google Sheet data or structure needs to be changed.

INSTALLATION
============
Replace these files in GitHub:
- lianbo_project_performance_hub.py
- activity_data_layer.py
- email_service.py
- requirements.txt

Then reboot the Streamlit application or click "Osveži sve module".

EXPECTED HEADER
===============
Version: v8.3_bn_master_header_fix
