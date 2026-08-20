import unittest

from batches import make_batches


class MakeBatchesTests(unittest.TestCase):
    def test_keeps_a_complete_final_batch(self) -> None:
        self.assertEqual(make_batches([1, 2, 3, 4], 2), [[1, 2], [3, 4]])

    def test_keeps_a_short_final_batch(self) -> None:
        self.assertEqual(make_batches([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])


if __name__ == "__main__":
    unittest.main()
