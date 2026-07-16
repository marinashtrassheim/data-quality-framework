import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import List, Dict, Any, Optional

log = logging.getLogger(__name__)


class EmailNotifier:
    """Sends batch failure alerts via SMTP."""

    def __init__(
            self,
            smtp_host: str,
            smtp_port: int,
            sender_email: str,
            sender_password: Optional[str] = None,
            default_recipients: Optional[List[str]] = None,
            use_tls: bool = True,
    ):
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.sender_email = sender_email
        self.sender_password = sender_password
        self.default_recipients = default_recipients or []
        self.use_tls = use_tls

    def send_alert(
            self,
            subject: str,
            body: str,
            recipients: Optional[List[str]] = None,
            html_body: Optional[str] = None,
    ) -> None:
        recipients = recipients or self.default_recipients
        if not recipients:
            log.warning("No recipients specified, skipping email send.")
            return
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self.sender_email
        msg["To"] = ", ".join(recipients)

        msg.attach(MIMEText(body, "plain"))
        if html_body:
            msg.attach(MIMEText(html_body, "html"))

        try:
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                if self.use_tls:
                    server.starttls()
                if self.sender_password:
                    server.login(self.sender_email, self.sender_password)
                server.sendmail(self.sender_email, recipients, msg.as_string())
            log.info("Email sent successfully to %s", recipients)
        except Exception as e:
            log.error("Email send failed to %s: %s", recipients, e)
            raise

    @classmethod
    def from_env(cls) -> "EmailNotifier":
        smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
        smtp_port = int(os.getenv("SMTP_PORT", "587"))
        sender_email = os.getenv("EMAIL_SENDER", "")
        sender_password = os.getenv("EMAIL_PASSWORD", None)
        use_tls = os.getenv("SMTP_USE_TLS", "true").lower() == "true"
        recipients_str = os.getenv("EMAIL_RECIPIENTS", "")
        default_recipients = [r.strip() for r in recipients_str.split(",") if r.strip()]
        return cls(
            smtp_host=smtp_host,
            smtp_port=smtp_port,
            sender_email=sender_email,
            sender_password=sender_password,
            default_recipients=default_recipients,
            use_tls=use_tls,
        )

    @staticmethod
    def format_failure_email(
            file_key: str,
            failed_checks: List[str],
            extra_details: Optional[Dict[str, Any]] = None,
    ) -> str:
        lines = [
            "DATA QUALITY FAILURE",
            "",
            f"File: {file_key}",
            "",
            "Failed checks:",
        ]
        for check in failed_checks:
            lines.append(f"  - {check}")
        if extra_details:
            lines.append("\nDetails:")
            for key, value in extra_details.items():
                lines.append(f"  {key}: {value}")
        return "\n".join(lines)

    @staticmethod
    def format_batch_failure_email(summary: Dict[str, Any]) -> str:
        lines = [
            "DATA QUALITY BATCH REPORT",
            "",
            f"Total files: {summary.get('total_files', 0)}",
            f"Processed: {summary.get('processed', 0)}",
            f"Failed: {summary.get('failed', 0)}",
            "",
            "Failed files:",
        ]

        for error in summary.get("errors", []):
            file_name = Path(error.get("file", "unknown")).name
            stage = error.get("stage", "unknown")
            checks = error.get("checks") or []
            lines.append(f"  - {file_name} [{stage}]")
            for check in checks:
                lines.append(f"      * {check}")
            details = error.get("details") or {}
            for key, value in details.items():
                lines.append(f"      ({key}: {value})")

        return "\n".join(lines)
