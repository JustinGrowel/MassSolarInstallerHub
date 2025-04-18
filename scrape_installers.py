import requests
from bs4 import BeautifulSoup
import csv
import json
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
import time
from selenium.common.exceptions import NoSuchElementException, TimeoutException

# URL of the page to scrape
url = "https://www.energysage.com/local-data/solar-companies/ma/"

print(f"Attempting to fetch URL using Selenium: {url}")

# Selenium setup
chrome_options = Options()
# chrome_options.add_argument("--headless") # Keeping this commented out for visible browser
chrome_options.add_argument("--no-sandbox")
chrome_options.add_argument("--disable-dev-shm-usage")
chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3")

# Helper function to extract company name from page title
def extract_company_name_from_title(title):
    """Extract company name from page title patterns"""
    if not title:
        return "Unknown Company"
        
    # Pattern: "Company Name - Profile & Reviews - 2025 | EnergySage"
    if " - Profile & Reviews" in title:
        return title.split(" - Profile & Reviews")[0].strip()
    # Pattern: "Company Name: Reviews & Solar Installer Information | EnergySage"
    elif ": Reviews & Solar" in title:
        return title.split(": Reviews & Solar")[0].strip()
    # Fallback: just use the part before the pipe if present
    elif "|" in title:
        return title.split("|")[0].strip()
    else:
        return title

try:
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
except Exception as e:
    print(f"Error setting up WebDriver: {e}")
    print("Please ensure you have Chrome and the correct ChromeDriver installed.")
    print("Alternatively, install webdriver-manager: pip install webdriver-manager")
    exit()

try:
    # Use Selenium to load the MAIN LIST page first
    driver.get(url)
    print("Loading main page. You should see the browser window open...")
    WebDriverWait(driver, 15).until(
        EC.presence_of_element_located((By.TAG_NAME, "body")) 
    )
    print("Successfully loaded the main list page with Selenium.")
    
    # Debug: Output the page title to confirm correct page loading
    print(f"Page title: {driver.title}")
    
    # Add visual pause to see the page
    time.sleep(3)
    
    installers_links = []
    processed_links = set()  # To avoid duplicates
    
    # Initialize page counter
    current_page = 1
    total_pages = 8  # From the pagination component we saw
    
    # Process all pages
    while current_page <= total_pages:
        print(f"\n--- Processing Page {current_page} of {total_pages} ---")
        
        # Wait for page content to load
        time.sleep(3)
        
        # Find the paginated list container that has all installers
        installer_list = driver.find_elements(By.CSS_SELECTOR, "ul#paginated-list")
        
        if installer_list:
            print(f"Found installer list container")
            
            # Find all installer list items within the container
            installer_items = driver.find_elements(By.CSS_SELECTOR, "ul#paginated-list > li")
            
            if installer_items:
                print(f"Found {len(installer_items)} installer items on this page")
                
                # Process each installer item
                for idx, item in enumerate(installer_items):
                    try:
                        # Try to find the company name link
                        company_link = item.find_elements(By.CSS_SELECTOR, "a.d-block.font-weight-bold")
                        
                        if company_link:
                            # Extract company information
                            company_name = company_link[0].text.strip()
                            profile_url = company_link[0].get_attribute('href')
                            
                            # Visual feedback
                            print(f"  - Found installer {idx+1}: {company_name}")
                            
                            # Basic validation and avoid duplicates
                            if company_name and profile_url and profile_url not in processed_links:
                                installers_links.append({
                                    'name': company_name,
                                    'profile_url': profile_url
                                })
                                processed_links.add(profile_url)
                                print(f"  -> Added company: {company_name} (from page listing)")
                    except Exception as e:
                        print(f"  Error processing installer item {idx+1}: {e}")
            else:
                print("No installer items found in the list container")
        else:
            print("Could not find the installer list container")
        
        print(f"--- Found {len(installers_links)} unique company profile links so far ---")
        
        # Check if there are more pages to process
        if current_page < total_pages:
            print(f"\nAttempting to navigate to page {current_page + 1}...")
            
            try:
                # Look for the Next Page button and click it
                next_button = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, "button[data-pc-section='nextpagebutton']"))
                )
                
                # Click the next button
                next_button.click()
                print(f"Clicked 'Next Page' button to navigate to page {current_page + 1}")
                
                # Wait for page to load after navigation
                time.sleep(3)
                
                # Increment page counter
                current_page += 1
            except (NoSuchElementException, TimeoutException) as e:
                print(f"Error finding or clicking next page button: {e}")
                print("Unable to navigate to next page. Stopping pagination.")
                break
        else:
            print("\nReached the last page. Finished collecting company links.")
            break

    print(f"\n--- Found {len(installers_links)} unique company profile links across all pages ---")

    # --- Step 2: Visit Individual Pages and Scrape Details --- 
    print("\n--- Scraping Individual Company Pages ---")
    all_installers_data = []

    for index, installer_info in enumerate(installers_links):
        profile_url = installer_info['profile_url']
        company_name = installer_info['name']
        # Assign a numerical ID (starting from 1)
        company_id = index + 1
        print(f"\nScraping ({company_id}/{len(installers_links)}): {company_name}")
        print(f"Navigating to: {profile_url}")

        try:
            # Navigate to the profile page
            driver.get(profile_url)
            # Wait for page to load
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            
            # Get the page title to extract accurate company name if needed
            if company_name == "Unknown Company":
                company_name = extract_company_name_from_title(driver.title)
            
            # Small delay to ensure content loads
            time.sleep(2)
            
            # Parse with BeautifulSoup
            profile_page_source = driver.page_source
            profile_soup = BeautifulSoup(profile_page_source, 'html.parser')

            # Description: Try multiple potential selectors
            description = 'N/A'
            desc_selectors = [
                {'type': 'id', 'value': 'collapsablePitch'},
                {'type': 'class', 'value': 'supplier-description'},
                {'type': 'class', 'value': 'company-description'},
                {'type': 'class', 'value': 'about-description'},
                {'type': 'class', 'value': 'supplier-pitch'}
            ]
            
            for selector in desc_selectors:
                if selector['type'] == 'id':
                    desc_div = profile_soup.find('div', id=selector['value'])
                else:
                    desc_div = profile_soup.find('div', class_=selector['value'])
                    
                if desc_div:
                    description = ' '.join(desc_div.stripped_strings)
                    print(f"Found description using {selector['type']}='{selector['value']}'")
                    break

            # Store collected data in a well-structured format - only the fields we need
            installer_data = {
                'id': company_id,
                'company_name': company_name,
                'description': description,
                'profile_url': profile_url
            }
            all_installers_data.append(installer_data)
            
            print(f"  -> ID: {company_id}")
            print(f"  -> Description: {description[:50]}..." if len(description) > 50 else f"  -> Description: {description}")

            # Add a small delay to avoid overwhelming the server
            time.sleep(1.5)

        except Exception as page_error:
            print(f"  -> Error scraping {profile_url}: {page_error}")
            # Add placeholder data on error
            all_installers_data.append({
                'id': company_id,
                'company_name': company_name,
                'description': 'Error retrieving',
                'profile_url': profile_url
            })
            time.sleep(1)

    # --- Step 3: Output Final Data --- 
    print("\n--- Scraping Complete --- ")
    print(f"Successfully scraped details for {len(all_installers_data)} companies.")

    # Output data in multiple formats for easy website integration
    if all_installers_data:
        base_filename = 'massachusetts_solar_installers'
        
        # 1. CSV Export with proper quoting to handle lists
        csv_filename = f'{base_filename}.csv'
        print(f"\nSaving data to {csv_filename}...")
        
        # Define field names - including the new ID field
        fieldnames = [
            'id', 'company_name', 'description', 'profile_url'
        ]
        
        with open(csv_filename, 'w', newline='', encoding='utf-8') as output_file:
            # Use DictWriter with proper quoting to handle text with commas
            writer = csv.DictWriter(
                output_file, 
                fieldnames=fieldnames,
                quoting=csv.QUOTE_ALL  # Quote all fields to prevent delimiter issues
            )
            # Write header
            writer.writeheader()
            # Write data rows - including the new ID field
            for installer in all_installers_data:
                writer.writerow({
                    'id': installer['id'],
                    'company_name': installer['company_name'],
                    'description': installer['description'],
                    'profile_url': installer['profile_url']
                })
        
        # 2. JSON Export
        json_filename = f'{base_filename}.json'
        print(f"Saving data to {json_filename}...")
        
        with open(json_filename, 'w', encoding='utf-8') as json_file:
            json.dump(all_installers_data, json_file, indent=2, ensure_ascii=False)
        
        print(f"Data successfully saved to {csv_filename} and {json_filename}")
        print("\nTo use this data in your website:")
        print("1. For CSV: Use pandas or csv module to read the data")
        print("2. For JSON: Use the built-in json module to load the data structure")
        print("3. JSON format is recommended for easier web integration")
        
    else:
        print("No installer data was successfully scraped or processed.")

except Exception as e:
    print(f"An error occurred during scraping: {e}")
finally:
    # Ensure the browser is closed even if errors occur
    if 'driver' in locals():
        print("Scraping complete. Closing browser in 5 seconds...")
        time.sleep(5)  # Give user time to see the final state
        driver.quit()
        print("Closed Selenium browser.") 