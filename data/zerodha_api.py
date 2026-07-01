import time
from urllib.parse import urlparse, parse_qs
import os
import pyotp
import pandas as pd
from dotenv import load_dotenv
from kiteconnect import KiteConnect

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

class Zerodha:

    def __init__(self):
        # 1. Load Credentials
        load_dotenv()
        self.api_key = os.getenv("api_key")
        self.api_secret = os.getenv("api_secret")
        self.user_id = os.getenv("user_id")
        self.password = os.getenv("password")
        self.totp_secret = os.getenv("totp_secret")
        
        # 2. Initialize the master KiteConnect instance
        self.kite = KiteConnect(api_key=self.api_key)

    def get_access_token(self):
        """
        Automates the Kite login process.
        Saves the generated access token directly into the self.kite instance.
        """
        login_url = self.kite.login_url()

        # Setup Chrome Options
        chrome_options = Options()
        chrome_options.add_argument("--headless") 
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--window-size=1200,800")
        
        print("Starting Chrome Browser...")
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        
        try:
            driver.get(login_url)
            wait = WebDriverWait(driver, 20)
            
            # 1. Enter User ID
            print("Entering User ID...")
            userid_field = wait.until(EC.presence_of_element_located((By.ID, "userid")))
            userid_field.send_keys(self.user_id)
            
            # 2. Enter Password
            print("Entering Password...")
            password_field = wait.until(EC.presence_of_element_located((By.ID, "password")))
            password_field.send_keys(self.password)
            
            # Click Login
            login_btn = driver.find_element(By.XPATH, "//button[@type='submit']")
            login_btn.click()
            
            # 3. Enter TOTP
            print("Generating and entering TOTP...")
            totp_code = pyotp.TOTP(self.totp_secret).now()
            
            # Improved selector targeting Kite's 2FA text/number input boxes
            totp_field = wait.until(EC.element_to_be_clickable((By.XPATH, "//input[@type='text' or @type='number']")))
            
            time.sleep(1.0)
            totp_field.click()
            totp_field.send_keys(totp_code + Keys.RETURN)
            
            # 4. Wait for redirect
            print("Waiting for Zerodha to redirect...")
            wait.until(EC.url_contains("request_token="))
            
            current_url = driver.current_url
            parsed_url = urlparse(current_url)
            request_token = parse_qs(parsed_url.query)['request_token'][0]
            
            print(f"Success! Got Request Token: {request_token}")
            
            # 5. Generate session and set it directly to the master instance
            data = self.kite.generate_session(request_token, api_secret=self.api_secret)
            access_token = data["access_token"]
            self.kite.set_access_token(access_token)
            
            print("\n" + "="*60)
            print("AUTHENTICATION COMPLETE & SET TO INSTANCE")
            print("="*60 + "\n")
                
            return access_token
            
        except Exception as e:
            print(f"An error occurred during automated login: {e}")
            return None
            
        finally:
            driver.quit()

    def instrument_token(self, exchange):
        """
        Fetches available instrument tokens for given exchange.
        Assumes get_access_token() has already run successfully.
        """
        try:
            return self.kite.instruments(exchange)
        
        except Exception as e:
            print(f"Error fetching tokens: {e}. Did you run get_access_token() first?")
            return None

    def fetch_historical_data(self, instrument_token, from_date, to_date, interval):
        """
        Fetches historical data using the authenticated master instance.
        """
        try:
            print(f"Fetching historical data for token {instrument_token}...")
            data = self.kite.historical_data(instrument_token, from_date, to_date, interval)
            print(f"Fetched {len(data)} records.")
            
            df = pd.DataFrame(data)
            df.to_csv(f"historical_data_{instrument_token}_{from_date}_{to_date}.csv", index=False)
            return df
        
        except Exception as e:
            print(f"Error fetching historical data: {e}")
            return None