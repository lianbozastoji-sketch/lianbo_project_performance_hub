import smtplib
from datetime import datetime
from email.message import EmailMessage

import streamlit as st


class EmailService:
    """Central e-mail service for Lianbo Project Performance Hub.

    Responsibilities:
    - read SMTP settings from Streamlit secrets
    - send messages through SMTP/TLS or SMTP/SSL
    - write all attempts to EMAIL_LOG Google Sheet
    - return structured status to the caller
    """

    DEFAULT_LOG_COLUMNS = [
        "Timestamp",
        "Email_Type",
        "Recipient",
        "Subject",
        "Status",
        "Related_ID",
        "Error_Message",
    ]

    def __init__(self, get_client_func, sheet_id, log_sheet_name="EMAIL_LOG", log_columns=None):
        self.get_client_func = get_client_func
        self.sheet_id = sheet_id
        self.log_sheet_name = log_sheet_name
        self.log_columns = log_columns or self.DEFAULT_LOG_COLUMNS

    @staticmethod
    def _yes_value(value):
        return str(value).strip().upper() in ["YES", "Y", "DA", "TRUE", "1", "YAS"]

    @staticmethod
    def _get_secret_value(*keys, default=""):
        """Read Streamlit secrets from root or [email]/[smtp] sections."""
        try:
            for key in keys:
                if isinstance(key, tuple) and len(key) == 2:
                    section, item = key
                    if section in st.secrets and item in st.secrets[section]:
                        return st.secrets[section][item]
                elif key in st.secrets:
                    return st.secrets[key]
        except Exception:
            pass
        return default

    def settings(self):
        host = self._get_secret_value(
            ("email", "SMTP_HOST"), ("email", "SMTP_SERVER"),
            ("smtp", "host"), ("smtp", "server"),
            "SMTP_HOST", "SMTP_SERVER", default="",
        )
        raw_port = self._get_secret_value(
            ("email", "SMTP_PORT"), ("smtp", "port"), "SMTP_PORT", default=587,
        )
        try:
            port = int(raw_port)
        except Exception:
            port = 587

        username = self._get_secret_value(
            ("email", "SMTP_USER"), ("email", "SMTP_USERNAME"),
            ("smtp", "username"), ("smtp", "user"),
            "SMTP_USER", "SMTP_USERNAME", default="",
        )
        password = self._get_secret_value(
            ("email", "SMTP_PASSWORD"), ("smtp", "password"), "SMTP_PASSWORD", default="",
        )
        sender = self._get_secret_value(
            ("email", "EMAIL_SENDER"), ("email", "FROM_EMAIL"),
            ("smtp", "sender"), ("smtp", "from_email"),
            "EMAIL_SENDER", "FROM_EMAIL", default=username,
        )
        sender_name = self._get_secret_value(
            ("email", "EMAIL_SENDER_NAME"), "EMAIL_SENDER_NAME",
            default="Lianbo Project Performance Hub",
        )
        enabled = self._yes_value(
            self._get_secret_value(("email", "EMAIL_ENABLED"), "EMAIL_ENABLED", default="YES")
        )
        use_ssl = self._yes_value(
            self._get_secret_value(("email", "SMTP_USE_SSL"), "SMTP_USE_SSL", default="YES" if port == 465 else "NO")
        )
        use_tls = self._yes_value(
            self._get_secret_value(("email", "SMTP_USE_TLS"), "SMTP_USE_TLS", default="YES" if port != 465 else "NO")
        )

        missing = []
        if not host:
            missing.append("SMTP_HOST/SMTP_SERVER")
        if not username:
            missing.append("SMTP_USER/SMTP_USERNAME")
        if not password:
            missing.append("SMTP_PASSWORD")
        if not sender:
            missing.append("EMAIL_SENDER/FROM_EMAIL")

        return {
            "host": str(host).strip(),
            "port": port,
            "username": str(username).strip(),
            "password": str(password).strip(),
            "sender": str(sender).strip(),
            "sender_name": str(sender_name).strip(),
            "enabled": enabled,
            "use_ssl": use_ssl,
            "use_tls": use_tls,
            "missing": missing,
        }

    @staticmethod
    def _safe_value(value):
        if value is None:
            return ""
        try:
            if hasattr(value, "item") and not isinstance(value, (str, bytes)):
                value = value.item()
        except Exception:
            pass
        if isinstance(value, datetime):
            return value.strftime("%d.%m.%Y %H:%M:%S")
        return value

    @staticmethod
    def _ensure_sheet_headers(ws, required_columns):
        try:
            existing = ws.row_values(1)
        except Exception:
            existing = []
        headers = [str(h).strip() for h in existing if str(h).strip()]
        if not headers:
            ws.update("A1", [required_columns])
            return list(required_columns)
        changed = False
        for col in required_columns:
            if col not in headers:
                headers.append(col)
                changed = True
        if changed:
            ws.update("A1", [headers])
        return headers

    def _ensure_log_sheet(self):
        client = self.get_client_func()
        sh = client.open_by_key(self.sheet_id)
        try:
            ws = sh.worksheet(self.log_sheet_name)
        except Exception:
            ws = sh.add_worksheet(title=self.log_sheet_name, rows=1000, cols=len(self.log_columns))
        self._ensure_sheet_headers(ws, self.log_columns)
        return ws

    def log_event(self, email_type, recipient, subject, status, related_id="", error_message=""):
        try:
            ws = self._ensure_log_sheet()
            headers = self._ensure_sheet_headers(ws, self.log_columns)
            row = {
                "Timestamp": datetime.now().strftime("%d.%m.%Y %H:%M:%S"),
                "Email_Type": email_type,
                "Recipient": recipient,
                "Subject": subject,
                "Status": status,
                "Related_ID": related_id,
                "Error_Message": error_message,
            }
            ws.append_row([self._safe_value(row.get(h, "")) for h in headers], value_input_option="USER_ENTERED")
        except Exception:
            # Never block the application if e-mail log cannot be written.
            pass

    def send_email(self, email_type, recipients, subject, body, related_id=""):
        recipients = [str(r).strip() for r in (recipients or []) if str(r).strip()]
        recipients = sorted(list(dict.fromkeys(recipients)))
        if not recipients:
            return {"sent": 0, "failed": 0, "skipped": "No recipients", "errors": []}

        cfg = self.settings()
        if not cfg["enabled"]:
            for recipient in recipients:
                self.log_event(email_type, recipient, subject, "DISABLED", related_id, "EMAIL_ENABLED is not YES")
            return {"sent": 0, "failed": 0, "skipped": "Disabled", "errors": []}

        if cfg["missing"]:
            error_text = "Missing secrets: " + ", ".join(cfg["missing"])
            for recipient in recipients:
                self.log_event(email_type, recipient, subject, "NOT_CONFIGURED", related_id, error_text)
            return {"sent": 0, "failed": 0, "skipped": "SMTP not configured", "errors": [error_text]}

        sent = 0
        failed = 0
        errors = []
        for recipient in recipients:
            try:
                msg = EmailMessage()
                msg["Subject"] = subject
                msg["From"] = f'{cfg["sender_name"]} <{cfg["sender"]}>'
                msg["To"] = recipient
                msg.set_content(body)

                if cfg["use_ssl"] or cfg["port"] == 465:
                    smtp_context = smtplib.SMTP_SSL(cfg["host"], cfg["port"], timeout=20)
                else:
                    smtp_context = smtplib.SMTP(cfg["host"], cfg["port"], timeout=20)

                with smtp_context as smtp:
                    if cfg["use_tls"] and cfg["port"] != 465:
                        smtp.starttls()
                    smtp.login(cfg["username"], cfg["password"])
                    smtp.send_message(msg)

                sent += 1
                self.log_event(email_type, recipient, subject, "SENT", related_id, "")
            except smtplib.SMTPAuthenticationError as e:
                failed += 1
                error_text = f"SMTPAuthenticationError: {e}"
                errors.append(f"{recipient}: {error_text}")
                self.log_event(email_type, recipient, subject, "FAILED", related_id, error_text)
            except Exception as e:
                failed += 1
                error_text = f"{type(e).__name__}: {e}"
                errors.append(f"{recipient}: {error_text}")
                self.log_event(email_type, recipient, subject, "FAILED", related_id, error_text)

        return {"sent": sent, "failed": failed, "skipped": "", "errors": errors}
