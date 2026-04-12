import json
import unittest

from bot.utils.key_generator import generate_singbox_split_json


class SplitConfigTests(unittest.TestCase):
    def test_singbox_split_config_contains_package_and_domain_rules(self) -> None:
        config = {
            "protocol": "vless",
            "host": "example.com",
            "port": 443,
            "uuid": "11111111-1111-1111-1111-111111111111",
            "stream_settings": {
                "network": "ws",
                "security": "tls",
                "tlsSettings": {
                    "serverName": "example.com",
                    "fingerprint": "chrome",
                },
                "wsSettings": {
                    "path": "/ws",
                    "headers": {"Host": "example.com"},
                },
            },
        }
        exclusions = [
            {"rule_type": "package", "rule_value": "org.telegram.messenger"},
            {"rule_type": "domain", "rule_value": "telegram.org"},
        ]

        parsed = json.loads(generate_singbox_split_json(config, exclusions))
        rules = parsed["route"]["rules"]
        tun_inbound = parsed["inbounds"][0]

        self.assertIn(
            {"package_name": ["org.telegram.messenger"], "outbound": "direct"},
            rules,
        )
        self.assertIn(
            {"domain_suffix": ["telegram.org"], "outbound": "direct"},
            rules,
        )
        self.assertEqual("proxy", parsed["route"]["final"])
        self.assertEqual(["org.telegram.messenger"], tun_inbound["exclude_package"])
        self.assertTrue(tun_inbound["auto_route"])
        self.assertTrue(tun_inbound["strict_route"])


if __name__ == "__main__":
    unittest.main()
