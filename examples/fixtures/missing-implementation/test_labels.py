import unittest

from labels import format_label


class FormatLabelTests(unittest.TestCase):
    def test_formats_a_positive_score(self) -> None:
        self.assertEqual(format_label("Ada", 12), "Ada: 12 points")

    def test_formats_zero(self) -> None:
        self.assertEqual(format_label("Lin", 0), "Lin: 0 points")


if __name__ == "__main__":
    unittest.main()
