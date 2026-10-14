import json
import os
import unittest
from unittest import mock

from price_alerts import parse_price, run_checks, send_discord

PATTERN = r'"price"\s*:\s*"?([\d,]+\.?\d*)'


def page(price: str) -> str:
    return f'<html><script>{{"price": "{price}"}}</script></html>'


class ParsePriceTests(unittest.TestCase):
    def test_reads_price_with_thousands_separator(self):
        self.assertEqual(parse_price(page("1,299.99"), PATTERN), 1299.99)

    def test_returns_none_when_pattern_missing(self):
        self.assertIsNone(parse_price("<html>no price</html>", PATTERN))


class RunChecksTests(unittest.TestCase):
    def product(self, target: float = 50.0) -> list[dict]:
        return [{"name": "Headphones", "url": "https://x", "price_pattern": PATTERN, "target_price": target}]

    def test_alerts_when_price_at_or_below_target(self):
        state: dict[str, float] = {}
        alerts = run_checks(self.product(), state, fetch=lambda url: page("45.00"))
        self.assertEqual(len(alerts), 1)
        self.assertEqual(state, {"Headphones": 45.0})

    def test_no_alert_when_price_above_target(self):
        state: dict[str, float] = {}
        alerts = run_checks(self.product(), state, fetch=lambda url: page("60.00"))
        self.assertEqual(alerts, [])
        self.assertEqual(state, {})

    def test_does_not_repeat_alert_at_same_price(self):
        state = {"Headphones": 45.0}
        alerts = run_checks(self.product(), state, fetch=lambda url: page("45.00"))
        self.assertEqual(alerts, [])

    def test_alerts_again_after_further_drop(self):
        state = {"Headphones": 45.0}
        alerts = run_checks(self.product(), state, fetch=lambda url: page("40.00"))
        self.assertEqual(len(alerts), 1)
        self.assertEqual(state, {"Headphones": 40.0})

    def test_rearms_after_price_rises_above_target(self):
        state = {"Headphones": 45.0}
        run_checks(self.product(), state, fetch=lambda url: page("60.00"))
        self.assertEqual(state, {})
        alerts = run_checks(self.product(), state, fetch=lambda url: page("45.00"))
        self.assertEqual(len(alerts), 1)

    def test_fetch_error_skips_product_without_crashing(self):
        def broken(url: str) -> str:
            raise OSError("network down")

        state: dict[str, float] = {}
        self.assertEqual(run_checks(self.product(), state, fetch=broken), [])
        self.assertEqual(state, {})


class SendDiscordTests(unittest.TestCase):
    def test_no_webhook_configured_sends_nothing(self):
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch("price_alerts.urllib.request.urlopen") as urlopen:
            send_discord("hello")
        urlopen.assert_not_called()

    def test_posts_json_content_to_webhook(self):
        env = {"DISCORD_WEBHOOK_URL": "https://discord.example/webhook"}
        with mock.patch.dict(os.environ, env, clear=True), mock.patch("price_alerts.urllib.request.urlopen") as urlopen:
            send_discord("hello")
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://discord.example/webhook")
        self.assertEqual(request.get_header("Content-type"), "application/json")
        self.assertEqual(json.loads(request.data), {"content": "hello"})

    def test_truncates_message_to_discord_limit(self):
        env = {"DISCORD_WEBHOOK_URL": "https://discord.example/webhook"}
        with mock.patch.dict(os.environ, env, clear=True), mock.patch("price_alerts.urllib.request.urlopen") as urlopen:
            send_discord("x" * 5000)
        self.assertEqual(len(json.loads(urlopen.call_args.args[0].data)["content"]), 2000)


if __name__ == "__main__":
    unittest.main()
