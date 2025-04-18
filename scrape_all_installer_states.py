import csv
import json
import time
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup
import shutil

def scrape_states_served(profile_url, driver):
    """
    Scrape 'states served' information from an installer's page
    
    Args:
        profile_url: URL of the installer's profile page
        driver: Existing Selenium WebDriver instance
        
    Returns:
        List of states served
    """
    states_served = []
    
    try:
        print(f"Navigating to: {profile_url}")
        driver.get(profile_url)
        
        # Wait for page to load
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        
        print("Page loaded. Looking for states served data...")
        time.sleep(2)  # Give the page a moment to fully render
        
        # Parse with BeautifulSoup
        page_source = driver.page_source
        soup = BeautifulSoup(page_source, 'html.parser')
        
        # Try multiple potential selectors for states served
        states_selectors = [
            {'type': 'class', 'value': 'states-served'},
            {'type': 'class', 'value': 'service-states'},
            {'type': 'class', 'value': 'states'},
            {'type': 'class', 'value': 'coverage-area'}
        ]
        
        for selector in states_selectors:
            states_div = soup.find('div', class_=selector['value'])
            if states_div:
                print(f"Found states using class='{selector['value']}'")
                
                # Try to find state links inside the container
                state_links = states_div.find_all('a')
                if state_links:
                    states = [link.get_text(strip=True) for link in state_links if link.get_text(strip=True)]
                    states_served = sorted(list(set(states)))  # Remove duplicates and sort
                    break
                
                # If no links found, try to get text directly
                if not states_served and states_div.text.strip():
                    states_text = states_div.text.strip()
                    print(f"Found states text: {states_text}")
                    # Try to parse states from text (comma-separated list)
                    if ',' in states_text:
                        states = [state.strip() for state in states_text.split(',')]
                        states_served = sorted(list(set(states)))
                        break
        
        if states_served:
            print(f"Found {len(states_served)} states served: {', '.join(states_served)}")
        else:
            print("No states served information found.")
            
            # Attempt to look for any text containing state abbreviations
            page_text = soup.get_text()
            common_states = ['MA', 'NH', 'VT', 'CT', 'RI', 'ME', 'NY', 'NJ', 'PA']
            
            print("Looking for state abbreviations in page content...")
            found_states = []
            for state in common_states:
                # Look for state abbreviation as a word or with comma
                if f" {state} " in page_text or f"{state}," in page_text:
                    found_states.append(state)
            
            if found_states:
                print(f"Potential states found in text: {', '.join(found_states)}")
                states_served = found_states
            
    except Exception as e:
        print(f"Error during scraping: {e}")
        
    return states_served

def main():
    # Input and output files - now using the same file for input and output
    csv_file = 'massachusetts_solar_installers.csv'
    json_file = 'massachusetts_solar_installers.json'
    
    # Set up WebDriver once for all companies
    print("Setting up WebDriver...")
    chrome_options = Options()
    # chrome_options.add_argument("--headless") # Keeping this commented out for visible browser
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3")
    
    try:
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
    except Exception as e:
        print(f"Error setting up WebDriver: {e}")
        print("Please ensure you have Chrome and the correct ChromeDriver installed.")
        return
    
    try:
        # Read all installers from the CSV file
        installers = []
        with open(csv_file, 'r', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            # Save field names from original file
            original_fieldnames = reader.fieldnames
            installers = list(reader)
        
        print(f"Loaded {len(installers)} installers from CSV file.")
        
        # Process each installer
        updated_installers = []
        for i, installer in enumerate(installers):
            print(f"\nProcessing installer {i+1}/{len(installers)}: {installer['company_name']}")
            
            # Scrape states served
            states_served = scrape_states_served(installer['profile_url'], driver)
            
            # Create updated installer data - add states_served to existing data
            updated_installer = installer.copy()
            updated_installer['states_served'] = '|'.join(states_served) if states_served else ''
            updated_installers.append(updated_installer)
            
            # Add a pause between requests to avoid overloading the server
            if i < len(installers) - 1:  # Don't sleep after the last one
                print("Pausing before next company...")
                time.sleep(2)
        
        # Create a backup of the original file
        print(f"Creating backup of original CSV at {csv_file}.bak")
        shutil.copy2(csv_file, f"{csv_file}.bak")
                
        # Update the CSV file - add states_served to field names if not already present
        fieldnames = list(original_fieldnames)
        if 'states_served' not in fieldnames:
            fieldnames.append('states_served')
        
        # Write updated data back to the original CSV file
        print(f"Updating original CSV file with states served data: {csv_file}")
        with open(csv_file, 'w', newline='', encoding='utf-8') as file:
            writer = csv.DictWriter(
                file, 
                fieldnames=fieldnames,
                quoting=csv.QUOTE_ALL  # Quote all fields
            )
            writer.writeheader()
            for installer in updated_installers:
                writer.writerow(installer)
        
        # Also update the JSON file
        print(f"Updating original JSON file: {json_file}")
        # First read the original JSON to preserve structure
        with open(json_file, 'r', encoding='utf-8') as file:
            original_json = json.load(file)
        
        # Update with states_served information
        for i, installer in enumerate(original_json):
            if i < len(updated_installers):  # Safety check
                states = updated_installers[i]['states_served'].split('|') if updated_installers[i]['states_served'] else []
                installer['states_served'] = states
        
        # Write back to the JSON file
        with open(json_file, 'w', encoding='utf-8') as file:
            json.dump(original_json, file, indent=2, ensure_ascii=False)
        
        print(f"\nScraping complete!")
        print(f"Updated original data files:")
        print(f"  - CSV: {csv_file}")
        print(f"  - JSON: {json_file}")
        print(f"Original CSV backed up at: {csv_file}.bak")
            
    except Exception as e:
        print(f"Error: {e}")
    finally:
        print("Closing browser...")
        driver.quit()

if __name__ == "__main__":
    main() 