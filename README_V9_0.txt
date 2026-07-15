LIANBO PROJECT PERFORMANCE HUB
Version: v9.0_modular_foundation

This is the first controlled v9 modular release.

Implemented in this release:
- services/missing_work_service.py: independent, testable penalty engine
- core/config.py: first centralized configuration module
- main app delegates Missing Work Time calculation to the service
- all existing modules and Google Sheets structures remain preserved
- diagnostics always show source rows, matched rows and calculated months

Installation:
Upload the complete folder structure, including services and core folders.
GitHub web: create files using paths such as services/missing_work_service.py.
Replace lianbo_project_performance_hub.py and reboot the app.

Expected header:
Version: v9.0_modular_foundation
