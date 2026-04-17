import unittest

from bot.utils.panel_url import parse_panel_url


class PanelUrlParseTests(unittest.TestCase):
    def test_without_scheme_defaults_to_https(self) -> None:
        parsed = parse_panel_url("150.251.155.217:2053/api")
        self.assertEqual("https", parsed["protocol"])
        self.assertEqual("150.251.155.217", parsed["host"])
        self.assertEqual(2053, parsed["port"])
        self.assertEqual("/api/", parsed["web_base_path"])

    def test_without_scheme_port_80_defaults_to_http(self) -> None:
        parsed = parse_panel_url("150.251.155.217:80")
        self.assertEqual("http", parsed["protocol"])
        self.assertEqual(80, parsed["port"])
        self.assertEqual("/", parsed["web_base_path"])

    def test_keeps_explicit_http(self) -> None:
        parsed = parse_panel_url("http://example.com:8080/secret/")
        self.assertEqual("http", parsed["protocol"])
        self.assertEqual("example.com", parsed["host"])
        self.assertEqual(8080, parsed["port"])
        self.assertEqual("/secret/", parsed["web_base_path"])


if __name__ == "__main__":
    unittest.main()
