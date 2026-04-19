import unittest

import pandas as pd

from ptrade_t0_ml.model import split_train_test


class ModelSplitTests(unittest.TestCase):
    def test_split_train_test_keeps_chronological_order(self) -> None:
        df = pd.DataFrame({"value": range(10)})
        train_df, test_df = split_train_test(df, test_ratio=0.2)
        self.assertEqual(train_df["value"].tolist(), list(range(8)))
        self.assertEqual(test_df["value"].tolist(), [8, 9])


if __name__ == "__main__":
    unittest.main()
