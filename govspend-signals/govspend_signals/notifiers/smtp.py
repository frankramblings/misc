"""SMTP email notifier — supports both SMTP_SSL (port 465) and STARTTLS (port 587)."""
from __future__ import annotations

import smtplib
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from ..config import SmtpConfig
from ..signal import Signal


def _build_subject(signal: Signal) -> str:
    return f"[govspend] {signal.signal_type.upper()}: {signal.title[:80]}"


def _build_body(signal: Signal) -> str:
    amount_str = f"${signal.amount_usd:,.0f}" if signal.amount_usd is not None else "N/A"
    return (
        f"Signal: {signal.title}\n"
        f"Type: {signal.signal_type}\n"
        f"Source: {signal.source}\n"
        f"Published: {signal.published}\n"
        f"Ticker: {signal.ticker or 'N/A'}\n"
        f"Company: {signal.company or 'N/A'}\n"
        f"Amount: {amount_str}\n"
        f"URL: {signal.url}\n"
    )


def _send(config: SmtpConfig, subject: str, body: str) -> None:
    from_addr = config.from_addr or config.username

    msg = MIMEMultipart()
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = config.to
    msg.attach(MIMEText(body, "plain", "utf-8"))

    try:
        if config.port == 465:
            with smtplib.SMTP_SSL(config.host, config.port) as smtp:
                smtp.login(config.username, config.password)
                smtp.sendmail(from_addr, [config.to], msg.as_string())
        else:
            with smtplib.SMTP(config.host, config.port) as smtp:
                smtp.ehlo()
                smtp.starttls()
                smtp.ehlo()
                smtp.login(config.username, config.password)
                smtp.sendmail(from_addr, [config.to], msg.as_string())
    except Exception as exc:  # noqa: BLE001
        print(f"[smtp] error: {exc}", file=sys.stderr, flush=True)


class SmtpNotifier:
    """Sends each signal as an email via SMTP (TLS)."""

    def __init__(self, config: SmtpConfig) -> None:
        self._config = config

    def emit(self, signal: Signal) -> None:
        _send(self._config, _build_subject(signal), _build_body(signal))

    def emit_digest(self, subject: str, body: str) -> None:
        """Send a preformatted email (used by morning digest)."""
        _send(self._config, subject, body)
