LIANBO PROJECT PERFORMANCE HUB
Version: v8.4_ui_penalty_bn_batch_fix

FIXES
=====
1. OEE horizontal selector label is collapsed and CSS prevents vertical text.
2. Technician Evaluation now shows missing-entry penalties even when the technician has no activities in that month.
3. Penalty display no longer shows -0.0.
4. BN deviation alerts are batched into one e-mail.
5. The batch is sent 15 minutes after the latest BN entry.
6. Only changes greater than +/-3 seconds compared with the exact previous calendar day are included.
7. Immediate one-email-per-BN notifications are removed.
8. Automatic notification checks run before login, allowing GitHub scheduler wake-ups to execute them.
9. GitHub Actions scheduler is updated to wake the app every 15 minutes on weekdays.

INSTALLATION
============
Replace the application files and also replace:
.github/workflows/wake_streamlit.yml
wake_streamlit.py

Keep GitHub repository secret STREAMLIT_APP_URL.
Then reboot Streamlit.

EXPECTED VERSION
================
v8.4_ui_penalty_bn_batch_fix
