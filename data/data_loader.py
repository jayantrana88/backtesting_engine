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
        """Loads data from Zerodha based on config settings."""
        print("Loading data from Zerodha...")
        symbol = self.data_config.get("symbol")
        exchange = self.data_config.get("exchange", "NSE")
        from_date = self.data_config.get("from_date")
        to_date = self.data_config.get("to_date")
        
        if not all([symbol, from_date, to_date]):
            print("Error: 'symbol', 'from_date', and 'to_date' are required in config for Zerodha.")
            return None
            
        # Determine appropriate fetch interval based on timeframe
        # We fetch raw data and rely on _resample_data to aggregate it up
        tf = self.data_config.get("timeframe", "5min").lower()
        if "d" in tf:
            fetch_interval = "day"
        elif "h" in tf or int(''.join(filter(str.isdigit, tf)) or 0) >= 60:
            fetch_interval = "60minute"
        elif "min" in tf and int(''.join(filter(str.isdigit, tf)) or 0) >= 15:
            fetch_interval = "15minute"
        else:
            fetch_interval = "5minute" # safe default for intraday

        try:
            client = Zerodha()
            token = client.get_access_token()
            if not token:
                print("Failed to authenticate with Zerodha.")
                return None
                
            instruments = client.instrument_token(exchange)
            if not instruments:
                print(f"Failed to fetch instruments for exchange {exchange}.")
                return None
                
            # Find the token for the requested symbol
            inst_df = pd.DataFrame(instruments)
            matched = inst_df[inst_df['tradingsymbol'] == symbol]
            if matched.empty:
                print(f"Symbol {symbol} not found in exchange {exchange}.")
                return None
                
            inst_token = matched.iloc[0]['instrument_token']
            
            # Fetch historical data
            df = client.fetch_historical_data(inst_token, from_date, to_date, fetch_interval)
            
            if df is not None and not df.empty:
                # Standardize date column for resampling
                if 'date' in df.columns:
                    df.rename(columns={'date': 'timestamp'}, inplace=True)
                return df
            else:
                print("No data returned from Zerodha.")
                return None
                
        except Exception as e:
            print(f"Error integrating with Zerodha: {e}")
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