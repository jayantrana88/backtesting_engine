import pandas as pd
import json


# Default column order when the CSV has no headers.
# Most data providers (Binance, Yahoo, etc.) export in this order.
_DEFAULT_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]

# Known aliases for each standard column name.
_COLUMN_ALIASES = {
    "timestamp": ["timestamp", "date", "datetime", "time", "dt"],
    "open":      ["open", "o"],
    "high":      ["high", "h"],
    "low":       ["low", "l"],
    "close":     ["close", "c", "ltp", "last"],
    "volume":    ["volume", "vol", "v"],
}


class csv_data:

    def __init__(self):
        with open("config.json", "r") as f:
            self.config = json.load(f)
        csv_path = self.config.get("data", {}).get("csv_file_path")
        self.df = self._load_csv(csv_path)

    def _load_csv(self, csv_path: str) -> pd.DataFrame:
        """
        Loads a CSV file with automatic header detection.

        If the first row looks like data (all values are numeric or
        epoch-like) rather than column names, we assume a headerless CSV
        and assign default column names: timestamp, open, high, low, close, volume.
        """
        # Peek at the first row to decide if headers exist
        peek = pd.read_csv(csv_path, nrows=1, header=None)
        first_row = peek.iloc[0]

        has_header = self._row_looks_like_header(first_row)

        if has_header:
            df = pd.read_csv(csv_path)
            print(f"  CSV loaded with headers: {list(df.columns)}")
        else:
            # Headerless CSV — assign default column names
            df = pd.read_csv(csv_path, header=None)
            n_cols = len(df.columns)

            if n_cols < len(_DEFAULT_COLUMNS):
                # Fewer columns than expected — assign what we can
                df.columns = _DEFAULT_COLUMNS[:n_cols]
                print(f"  CSV loaded without headers ({n_cols} columns). "
                      f"Assigned: {list(df.columns)}")
            elif n_cols == len(_DEFAULT_COLUMNS):
                df.columns = _DEFAULT_COLUMNS
                print(f"  CSV loaded without headers. "
                      f"Assigned default: {_DEFAULT_COLUMNS}")
            else:
                # More columns than expected — assign defaults + extras
                extra = [f"col_{i}" for i in range(n_cols - len(_DEFAULT_COLUMNS))]
                df.columns = _DEFAULT_COLUMNS + extra
                print(f"  CSV loaded without headers ({n_cols} columns). "
                      f"Assigned defaults + {len(extra)} extra column(s).")

        return df

    @staticmethod
    def _row_looks_like_header(row: pd.Series) -> bool:
        """
        Heuristic: a row is a header if at least half its values are
        non-numeric strings. A data row will be all numbers (or
        epoch timestamps which are large integers).
        """
        non_numeric_count = 0
        for val in row:
            try:
                float(val)
            except (ValueError, TypeError):
                non_numeric_count += 1
        # If more than half the values can't be parsed as numbers, it's a header
        return non_numeric_count > len(row) / 2

    def get_data(self):
        """
        Standardizes column names and converts timestamps.

        Handles:
            - Column alias mapping (e.g., 'Date' → 'timestamp', 'Vol' → 'volume')
            - Millisecond/second epoch timestamps → datetime conversion
        """
        df = self.df.copy()
        df.columns = df.columns.str.lower().str.strip()

        # --- Column Alias Resolution ---
        rename_map = {}
        for standard_name, aliases in _COLUMN_ALIASES.items():
            for alias in aliases:
                if alias in df.columns:
                    rename_map[alias] = standard_name
                    break

        # If timestamp column wasn't found by alias, check if it's already
        # named 'timestamp' (from default assignment in headerless mode)
        if "timestamp" not in rename_map.values() and "timestamp" not in df.columns:
            raise ValueError(
                f"Could not find a timestamp column in {list(df.columns)}. "
                f"Expected one of: {_COLUMN_ALIASES['timestamp']}"
            )

        df = df.rename(columns=rename_map)

        # Keep only the standard columns that exist
        available = [col for col in _COLUMN_ALIASES.keys() if col in df.columns]
        df = df[available]

        # --- Timestamp Conversion ---
        df["timestamp"] = self._convert_timestamps(df["timestamp"])

        self._validate_data(df)

        return df

    @staticmethod
    def _convert_timestamps(series: pd.Series) -> pd.Series:
        """
        Converts a timestamp column to proper datetime objects.

        Detects and handles:
            - Millisecond epoch (e.g., 1704067200000) → datetime
            - Second epoch (e.g., 1704067200) → datetime
            - Already-formatted datetime strings → parsed as-is
        """
        # Check the first non-null value to determine format
        sample = series.dropna().iloc[0] if not series.dropna().empty else None
        if sample is None:
            return pd.to_datetime(series)

        # If it's already a datetime type, return as-is
        if isinstance(sample, pd.Timestamp):
            return series

        # Check if it looks like a numeric epoch
        try:
            numeric_val = float(sample)

            # Millisecond epoch: typically 13 digits (e.g., 1704067200000)
            # Second epoch: typically 10 digits (e.g., 1704067200)
            if numeric_val > 1e12:
                print("  Timestamp detected as millisecond epoch → converting to datetime")
                return pd.to_datetime(series, unit="ms", utc=True)
            elif numeric_val > 1e9:
                print("  Timestamp detected as second epoch → converting to datetime")
                return pd.to_datetime(series, unit="s", utc=True)
        except (ValueError, TypeError):
            pass

        # Fall through: treat as a string datetime
        return pd.to_datetime(series)

    @staticmethod
    def _validate_data(df: pd.DataFrame):
        """
        Validates the loaded DataFrame for common data corruption issues.
        Raises a ValueError if data is malformed.
        """
        # 1. Check for required columns
        required_cols = ["timestamp", "open", "high", "low", "close"]
        missing = [col for col in required_cols if col not in df.columns]
        if missing:
            raise ValueError(f"CRITICAL ERROR: Missing required columns: {missing}")

        # 2. Check for NaNs in required columns
        for col in required_cols:
            if df[col].isnull().any():
                raise ValueError(f"CRITICAL ERROR: CSV contains missing (NaN) values in column '{col}'. Please clean your data.")

        # 3. Check for duplicate timestamps
        if df['timestamp'].duplicated().any():
            raise ValueError("CRITICAL ERROR: CSV contains duplicate timestamps. Please ensure each row has a unique timestamp.")

        # 4. Check for negative or zero prices
        for col in ["open", "high", "low", "close"]:
            if (df[col] <= 0).any():
                raise ValueError(f"CRITICAL ERROR: CSV contains zero or negative prices in column '{col}'.")

        # 5. Check OHLC integrity
        if (df['high'] < df['low']).any():
            raise ValueError("CRITICAL ERROR: OHLC Integrity failure - 'high' is less than 'low' in some rows.")
        if (df['close'] > df['high']).any() or (df['close'] < df['low']).any():
            raise ValueError("CRITICAL ERROR: OHLC Integrity failure - 'close' price is outside the high-low range in some rows.")
        if (df['open'] > df['high']).any() or (df['open'] < df['low']).any():
            raise ValueError("CRITICAL ERROR: OHLC Integrity failure - 'open' price is outside the high-low range in some rows.")

        print("  Data validation passed successfully.")