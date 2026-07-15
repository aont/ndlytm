import unittest

from server import parse_catalogue_name


class ParseCatalogueNameTest(unittest.TestCase):
    def test_full_width_parentheses(self):
        self.assertEqual(
            parse_catalogue_name("Album Title（Album Artist）", "Track Artist"),
            ("Album Title", "Album Artist"),
        )

    def test_ascii_parentheses(self):
        self.assertEqual(
            parse_catalogue_name("Album Title (Album Artist)", "Track Artist"),
            ("Album Title", "Album Artist"),
        )

    def test_unrecognized_format_uses_catalogue_name_and_fallback_artist(self):
        self.assertEqual(
            parse_catalogue_name("Album Title", "Track Artist"),
            ("Album Title", "Track Artist"),
        )

    def test_empty_catalogue_name_uses_unknown_album_and_fallback_artist(self):
        self.assertEqual(
            parse_catalogue_name(None, "Track Artist"),
            ("Unknown Album", "Track Artist"),
        )


if __name__ == "__main__":
    unittest.main()
