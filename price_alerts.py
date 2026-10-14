"""Price alert checker: fetches product pages and emails when a price reaches the target.

Uses only the Python standard library. Run with `python price_alerts.py`.
Without SMTP_HOST set, alerts are printed instead of emailed (dry run).
"""

from __future__ import annotations

import json
import os
import re
import smtplib
import urllib.request
from email.message import EmailMessage
from pathlib import Path
from typing import Callable

HERE = Path(__file__).resolve().parent
CONFIG_PATH = HERE / "config.json"
STATE_PATH = HERE / "state.json"
USER_AGENT = "Mozilla/5.0 (personal price-alert checker)"


def fetch_html(url: str, timeout: int = 20) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def parse_price(html: str, pattern: str) -> float | None:
    """Return the first capture group of `pattern` as a float, or None if absent."""
    match = re.search(pattern, html)
    if match is None:
        return None
    return float(match.group(1).replace(",", ""))


def run_checks(
    products: list[dict],
    state: dict[str, float],
    fetch: Callable[[str], str] = fetch_html,
) -> list[str]:
    """Check each product and return alert lines. Mutates `state` (last alerted price per product)."""
    alerts: list[str] = []
    for product in products:
        name = product["name"]
        try:
            html = fetch(product["url"])
        except Exception as exc:  # network errors should not stop the other products
            print(f"[error] {name}: {exc}")
            continue

        price = parse_price(html, product["price_pattern"])
        if price is None:
            print(f"[warn] {name}: price pattern not found on page")
            continue

        target = float(product["target_price"])
        last_alerted = state.get(name)
        if price > target:
            state.pop(name, None)  # re-arm once the price rises above target again
            print(f"[ok] {name}: {price} (target {target})")
        elif last_alerted is None or price < last_alerted:
            alerts.append(f"{name}: now {price} (target {target}) {product['url']}")
            state[name] = price
        else:
            print(f"[ok] {name}: {price} already alerted at {last_alerted}")
    return alerts


def send_email(subject: str, body: str) -> None:
    host = os.environ.get("SMTP_HOST")
    if not host:
        print(f"[dry-run] {subject}\n{body}")
        return

    user = os.environ["SMTP_USER"]
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = user
    message["To"] = os.environ["ALERT_TO"]
    message.set_content(body)

    port = int(os.environ.get("SMTP_PORT", "587"))
    with smtplib.SMTP(host, port, timeout=30) as smtp:
        smtp.starttls()
        smtp.login(user, os.environ["SMTP_PASSWORD"])
        smtp.send_message(message)


def send_discord(message: str) -> None:
    """Post `message` to the Discord webhook in DISCORD_WEBHOOK_URL. Does nothing if unset."""
    url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not url:
        return

    payload = json.dumps({"content": message[:2000]}).encode("utf-8")  # Discord's message limit
    request = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(request, timeout=20):
        pass


def main() -> int:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    state: dict[str, float] = (
        json.loads(STATE_PATH.read_text(encoding="utf-8")) if STATE_PATH.exists() else {}
    )

    alerts = run_checks(config["products"], state)
    if alerts:
        # Send before saving state: if the email fails, the alert is retried next run.
        body = "\n".join(alerts)
        send_email("Price alert", body)
        send_discord(body)
    else:
        print("No new alerts.")

    STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
