import unittest

from inventory import available_units


class AvailableUnitsTests(unittest.TestCase):
    def test_subtracts_reserved_units(self) -> None:
        self.assertEqual(available_units(10, 3), 7)

    def test_all_units_can_be_reserved(self) -> None:
        self.assertEqual(available_units(4, 4), 0)


if __name__ == "__main__":
    unittest.main()
