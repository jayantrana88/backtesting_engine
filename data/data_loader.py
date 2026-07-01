import json
import pandas as pd
from data.csv_data import csv_data
from data.zerodha_api import Zerodha


class DataLoader:

    def __init__(self, config_path="config.json"):
        with open(config_path, "r") as f:
            self.config = json.load(f)
        self.data_config = self.config.get("data", {})

    def get_data(self):
        """
        Loads, validates, and resamples data based on the source specified in config.json.
        This is the only method the user needs to call.
        """
        source = self.data_config.get("source", "csv")

        if source == "zerodha":
            raw_df = self._load_from_zerodha()
        elif source == "csv":
            raw_df = self._load_from_csv()
        else:
            raise ValueError(f"Unknown data source specified in config: '{source}'")

        if raw_df is None or raw_df.empty:
            print("Failed to load raw data.")
            return None

        resampled_df = self._resample_data(raw_df)
        return resampled_df

    # --- Internal (Private) Helper Methods ---

    def _load_from_csv(self):
        """Internal function to handle loading from a CSV file."""
        print("Loading data from CSV...")
        try:
            csv_loader = csv_data()
            return csv_loader.get_data()
        except FileNotFoundError:
            print(f"Error: CSV file not found at path specified in config.json: '{self.data_config.get('csv_file_path')}'")
            return None
        except Exception as e:
            print(f"An error occurred while loading CSV data: {e}")
            return None

    def _load_from_zerodha(self):
        """Placeholder for loading data from Zerodha."""
        print("NOTICE: Zerodha data loading is not fully implemented yet.")
        return None

    def _resample_data(self, df):
        """
        Resamples the given DataFrame to the specified interval.
        """
        interval = self.data_config.get('timeframe', '5min')
        # csv_data standardizes the date column to 'timestamp'
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df = df.set_index('timestamp')

        print(f"Resampling data to '{interval}' timeframe...")
        resampling_rules = {'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'}
        resampled_df = df.resample(interval).agg(resampling_rules).dropna(how='all')
        return resampled_df.reset_index()