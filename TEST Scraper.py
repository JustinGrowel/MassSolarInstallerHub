import csv
import json
import time
import os
import requests
import urllib.parse
import re  # Ensure re is imported for regex use
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, StaleElementReferenceException
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup

def clean_text(text):
    """
    Clean and normalize text by removing excessive whitespace, newlines, and tabs.
    
    Args:
        text: The text to clean
        
    Returns:
        Cleaned text with normalized whitespace
    """
    if not text:
        return ""
        
    # Replace newlines and tabs with spaces
    text = text.replace('\n', ' ').replace('\t', ' ')
    
    # Replace multiple spaces with a single space using regex
    text = re.sub(r'\s+', ' ', text)
    
    # Strip leading/trailing whitespace
    return text.strip()

def scrape_installer_gallery(driver, company_id, company_name):
    """
    Function to scrape the installer's photo gallery
    
    Args:
        driver: Selenium WebDriver instance
        company_id: ID of the company
        company_name: Name of the company for folder naming
    
    Returns:
        List of dictionaries containing media information (id, url, path, type)
    """
    print("\nAttempting to access photo gallery...")
    
    # Create directories to store the media content
    company_folder = f"images/{company_id}_{company_name.replace(' ', '_')}"
    os.makedirs(company_folder, exist_ok=True)
    
    # Create separate folders for images and videos
    images_folder = os.path.join(company_folder, "images")
    videos_folder = os.path.join(company_folder, "videos")
    os.makedirs(images_folder, exist_ok=True)
    os.makedirs(videos_folder, exist_ok=True)
    
    downloaded_media = []
    
    try:
        # Look for the "See all" button
        try:
            # Wait for the gallery button to be present and click it
            gallery_button = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "a.gallery-link, a.btn.btn-primary.btn-sm.gallery-link"))
            )
            print(f"Found gallery button: {gallery_button.get_attribute('href')}")
            
            # Get the href attribute instead of clicking to avoid potential navigation issues
            gallery_url = gallery_button.get_attribute('href')
            
            # If the URL is relative, make it absolute
            if gallery_url.startswith('/'):
                parsed_url = urllib.parse.urlparse(driver.current_url)
                base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
                gallery_url = base_url + gallery_url
            
            print(f"Navigating to gallery page: {gallery_url}")
            driver.get(gallery_url)
            
            # Wait for gallery page to load
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            print("Gallery page loaded successfully")
            time.sleep(2)  # Give the gallery a moment to fully load
            
            # Parse the gallery page with BeautifulSoup
            gallery_source = driver.page_source
            gallery_soup = BeautifulSoup(gallery_source, 'html.parser')
            
            # Find all image and video elements in the gallery
            media_elements = []
            
            # Find images
            img_elements = gallery_soup.select('div.gallery img, div.photo-gallery img, img.gallery-image')
            if not img_elements:
                # Try alternative selectors if the specific ones don't work
                img_elements = gallery_soup.select('img[src*="gallery"], img[src*="photo"]')
            if not img_elements:
                # Last resort: get all images on the page
                img_elements = gallery_soup.select('img[src]')
            
            # Find video elements or links to videos
            video_elements = gallery_soup.select('video, iframe[src*="youtube"], iframe[src*="vimeo"], a[href*="youtube"], a[href*="vimeo"]')
            
            # Add media elements to the list with their type
            for img in img_elements:
                media_elements.append({"element": img, "type": "image"})
            
            for video in video_elements:
                media_elements.append({"element": video, "type": "video"})
            
            print(f"Found {len(media_elements)} potential media items in the gallery")
            
            # Keep track of media hashes to avoid duplicates
            media_hashes = set()
            
            # Process and download each media item
            for index, media_item in enumerate(media_elements):
                element = media_item["element"]
                media_type = media_item["type"]
                
                # Generate a unique ID for the media
                # Format: company_id + timestamp + index
                media_id = f"{company_id}_{int(time.time())}_{index+1}"
                
                # Process based on media type
                if media_type == "image":
                    # Process image
                    img_url = element.get('src') or element.get('data-src')
                    
                    if not img_url:
                        print(f"No source URL found for image {index+1}, skipping")
                        continue
                    
                    # Make relative URLs absolute
                    if img_url.startswith('/'):
                        parsed_url = urllib.parse.urlparse(driver.current_url)
                        base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
                        img_url = base_url + img_url
                    
                    # Check if this is actually a video thumbnail (e.g., YouTube)
                    is_youtube_thumbnail = False
                    video_id = None
                    video_platform = None
                    video_url = None
                    
                    # YouTube thumbnail detection
                    youtube_patterns = [
                        r'img\.youtube\.com/vi/([^/]+)/',  # Standard YouTube thumbnail URL
                        r'i\.ytimg\.com/vi/([^/]+)/'       # Alternative YouTube thumbnail URL
                    ]
                    
                    for pattern in youtube_patterns:
                        match = re.search(pattern, img_url)
                        if match:
                            is_youtube_thumbnail = True
                            video_id = match.group(1)
                            video_platform = "youtube"
                            video_url = f"https://www.youtube.com/watch?v={video_id}"
                            print(f"Detected YouTube video (ID: {video_id}) from thumbnail: {img_url}")
                            break
                    
                    if is_youtube_thumbnail:
                        # It's a video, not an image - create video metadata
                        video_filename = f"{media_id}_youtube_{video_id}.jpg"  # Still save the thumbnail
                        video_path = os.path.join(videos_folder, video_filename)
                        
                        try:
                            # Download the thumbnail
                            print(f"Downloading video thumbnail {index+1} (ID: {media_id}): {img_url}")
                            response = requests.get(img_url, stream=True, timeout=10)
                            
                            if response.status_code == 200:
                                # Calculate a simple hash to detect duplicates
                                content = response.content
                                content_hash = hash(content)
                                
                                if content_hash in media_hashes:
                                    print(f"Skipping duplicate video {index+1}")
                                    continue
                                
                                media_hashes.add(content_hash)
                                
                                with open(video_path, 'wb') as img_file:
                                    img_file.write(content)
                                
                                print(f"Successfully saved video thumbnail to {video_path}")
                                
                                # Store video information
                                video_info = {
                                    'id': media_id,
                                    'type': 'video',
                                    'platform': video_platform,
                                    'video_id': video_id,
                                    'video_url': video_url,
                                    'thumbnail_url': img_url,
                                    'thumbnail_path': video_path,
                                    'filename': video_filename
                                }
                                downloaded_media.append(video_info)
                            else:
                                print(f"Failed to download video thumbnail {index+1}: HTTP status {response.status_code}")
                        
                        except Exception as e:
                            print(f"Error downloading video thumbnail {index+1}: {e}")
                            
                    else:
                        # It's a regular image
                        # Skip tiny thumbnails or icons
                        if 'icon' in img_url.lower() or 'thumb' in img_url.lower():
                            # Try to find a larger version
                            data_full = element.get('data-full') or element.parent.get('href')
                            if data_full:
                                if data_full.startswith('/'):
                                    parsed_url = urllib.parse.urlparse(driver.current_url)
                                    base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
                                    img_url = base_url + data_full
                                else:
                                    img_url = data_full
                        
                        # Extract a descriptive part from the URL for the filename if possible
                        url_parts = img_url.split('/')
                        file_part = url_parts[-1].split('?')[0]  # Remove any query parameters
                        
                        # If the URL doesn't provide a meaningful name, use the ID
                        if len(file_part) > 5 and '.' in file_part:
                            # Use the original file name part but ensure it ends with .jpg
                            base_name = file_part.rsplit('.', 1)[0]
                            img_filename = f"{media_id}_{base_name}.jpg"
                        else:
                            img_filename = f"{media_id}.jpg"
                        
                        img_path = os.path.join(images_folder, img_filename)
                        
                        try:
                            # Download the image
                            print(f"Downloading image {index+1} (ID: {media_id}): {img_url}")
                            response = requests.get(img_url, stream=True, timeout=10)
                            
                            if response.status_code == 200:
                                # Calculate a simple hash of the image data to detect duplicates
                                content = response.content
                                content_hash = hash(content)
                                
                                if content_hash in media_hashes:
                                    print(f"Skipping duplicate image {index+1}")
                                    continue
                                
                                media_hashes.add(content_hash)
                                
                                with open(img_path, 'wb') as img_file:
                                    img_file.write(content)
                                
                                print(f"Successfully saved image to {img_path}")
                                
                                # Store image information including ID, URL and local path
                                image_info = {
                                    'id': media_id,
                                    'type': 'image',
                                    'url': img_url,
                                    'path': img_path,
                                    'filename': img_filename
                                }
                                downloaded_media.append(image_info)
                            else:
                                print(f"Failed to download image {index+1}: HTTP status {response.status_code}")
                        
                        except Exception as e:
                            print(f"Error downloading image {index+1}: {e}")
                
                elif media_type == "video":
                    # Process video element
                    video_url = None
                    video_id = None
                    video_platform = None
                    
                    # Check if it's an iframe
                    if element.name == 'iframe':
                        src = element.get('src', '')
                        if 'youtube' in src:
                            # Extract YouTube video ID
                            youtube_id_match = re.search(r'(?:embed|v)/([^/?]+)', src)
                            if youtube_id_match:
                                video_id = youtube_id_match.group(1)
                                video_platform = "youtube"
                                video_url = f"https://www.youtube.com/watch?v={video_id}"
                        elif 'vimeo' in src:
                            # Extract Vimeo video ID
                            vimeo_id_match = re.search(r'video/(\d+)', src)
                            if vimeo_id_match:
                                video_id = vimeo_id_match.group(1)
                                video_platform = "vimeo"
                                video_url = f"https://vimeo.com/{video_id}"
                    
                    # Check if it's a link
                    elif element.name == 'a':
                        href = element.get('href', '')
                        if 'youtube' in href or 'youtu.be' in href:
                            # Extract YouTube video ID
                            if 'youtu.be' in href:
                                youtube_id_match = re.search(r'youtu\.be/([^/?]+)', href)
                            else:
                                youtube_id_match = re.search(r'(?:v=|v/|embed/|youtu\.be/)([^/?&]+)', href)
                            
                            if youtube_id_match:
                                video_id = youtube_id_match.group(1)
                                video_platform = "youtube"
                                video_url = f"https://www.youtube.com/watch?v={video_id}"
                        elif 'vimeo' in href:
                            # Extract Vimeo video ID
                            vimeo_id_match = re.search(r'vimeo\.com/(\d+)', href)
                            if vimeo_id_match:
                                video_id = vimeo_id_match.group(1)
                                video_platform = "vimeo"
                                video_url = f"https://vimeo.com/{video_id}"
                    
                    # If we found a video, process it
                    if video_id and video_platform:
                        print(f"Found {video_platform} video (ID: {video_id}): {video_url}")
                        
                        # Generate a unique filename for the video
                        video_filename = f"{media_id}_{video_platform}_{video_id}.jpg"  # For the thumbnail
                        video_path = os.path.join(videos_folder, video_filename)
                        
                        # Construct thumbnail URL
                        thumbnail_url = None
                        if video_platform == "youtube":
                            thumbnail_url = f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg"
                        elif video_platform == "vimeo":
                            # For Vimeo, getting thumbnails directly requires an API call
                            # For simplicity, we'll just store the video URL for now
                            thumbnail_url = f"https://vimeo.com/api/v2/video/{video_id}/pictures"
                        
                        # Try to download the thumbnail if available
                        if thumbnail_url:
                            try:
                                print(f"Downloading video thumbnail for {video_platform} video {index+1} (ID: {media_id})")
                                response = requests.get(thumbnail_url, stream=True, timeout=10)
                                
                                if response.status_code == 200:
                                    # Save the thumbnail
                                    with open(video_path, 'wb') as thumb_file:
                                        thumb_file.write(response.content)
                                    
                                    print(f"Successfully saved video thumbnail to {video_path}")
                                else:
                                    print(f"Failed to download video thumbnail: HTTP status {response.status_code}")
                                    # If we can't download the thumbnail, we still want to record the video
                                    video_path = None
                            except Exception as e:
                                print(f"Error downloading video thumbnail: {e}")
                                video_path = None
                        
                        # Store video information
                        video_info = {
                            'id': media_id,
                            'type': 'video',
                            'platform': video_platform,
                            'video_id': video_id,
                            'video_url': video_url,
                            'thumbnail_url': thumbnail_url,
                            'thumbnail_path': video_path,
                            'filename': video_filename if video_path else None
                        }
                        downloaded_media.append(video_info)
            
            # Report results
            image_count = sum(1 for item in downloaded_media if item['type'] == 'image')
            video_count = sum(1 for item in downloaded_media if item['type'] == 'video')
            
            if downloaded_media:
                print(f"Successfully processed {len(downloaded_media)} media items: {image_count} images and {video_count} videos")
                
                # Save a metadata file with all media information
                metadata_file = os.path.join(company_folder, "media_metadata.json")
                with open(metadata_file, 'w', encoding='utf-8') as f:
                    json.dump(downloaded_media, f, indent=2)
                print(f"Media metadata saved to {metadata_file}")
            else:
                print("No media items were successfully processed")
                
        except (TimeoutException, NoSuchElementException) as e:
            print(f"Could not find gallery link: {e}")
    
    except Exception as e:
        print(f"Error during gallery scraping: {e}")
    
    return downloaded_media

def scrape_company_reviews(driver, company_id, company_name, profile_url):
    """
    Function to scrape the company's reviews
    
    Args:
        driver: Selenium WebDriver instance
        company_id: ID of the company
        company_name: Name of the company
        profile_url: Original profile URL of the company
    
    Returns:
        Dictionary with aggregate_rating and a list of individual reviews
    """
    print("\nAttempting to access company reviews...")
    
    result = {
        "aggregate_rating": 0,
        "reviews": []
    }
    
    try:
        # First, return to the main installer page to get the aggregate rating and total count
        print(f"Navigating back to main installer page: {profile_url}")
        driver.get(profile_url)
        
        # Wait for the page to load
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        time.sleep(2)  # Give the page a moment to fully render
        
        # Parse with BeautifulSoup
        page_source = driver.page_source
        soup = BeautifulSoup(page_source, 'html.parser')
        
        # Get aggregate rating if visible on main page
        try:
            # Look for clear rating indicators on the main page
            rating_elements = soup.select('.rating, .supplier-rating, .energysage-rating, [class*="rating"]')
            for rating_elem in rating_elements:
                rating_text = rating_elem.get_text(strip=True)
                # Check for patterns like "5.0", "5.0 out of 5", etc.
                rating_match = re.search(r'(\d+\.\d+|\d+)\s*(?:/|out of)?', rating_text)
                if rating_match:
                    try:
                        result["aggregate_rating"] = float(rating_match.group(1))
                        print(f"Found aggregate rating on main page: {result['aggregate_rating']} stars")
                        break
                    except:
                        pass
                        
        except Exception as e:
            print(f"Error extracting aggregate rating from main page: {e}")
        
        # Try to get the total number of reviews
        total_reviews = 0
        try:
            # Find all text elements that might contain review counts
            for element in soup.find_all(['span', 'div', 'button']):
                text = element.get_text(strip=True)
                if 'review' in text.lower():
                    # Look for patterns like "327 reviews", "327 review(s)", etc.
                    count_match = re.search(r'(\d+)\s*review', text, re.IGNORECASE)
                    if count_match:
                        total_reviews = int(count_match.group(1))
                        print(f"Found total of {total_reviews} reviews")
                        break
        except Exception as e:
            print(f"Error extracting total review count: {e}")
        
        # Initialize variables
        valid_reviews = []
        seen_reviews = set()  # Track unique reviews to avoid duplicates
        
        # IMPROVED APPROACH: Look specifically for modal trigger buttons for reviews
        # This targets buttons like <button data-toggle="modal" data-target="#allReviews">See All Reviews (327)</button>
        try:
            print("Looking for review modal buttons...")
            review_modal_button = None
            
            # First try to find buttons that explicitly open review modals
            modal_buttons = driver.find_elements(By.CSS_SELECTOR, 
                'button[data-toggle="modal"][data-target*="review"], '
                'button[data-toggle="modal"][data-target*="Review"], '
                'button[data-bs-toggle="modal"][data-bs-target*="review"]'
            )
            
            # If found buttons, use the first one that mentions reviews
            if modal_buttons:
                for button in modal_buttons:
                    button_text = button.text.lower()
                    if 'review' in button_text:
                        review_modal_button = button
                        print(f"Found review modal button: {button.text}")
                        break
            
            # If no specific modal button found, try more general review-related buttons
            if not review_modal_button:
                print("Looking for any review-related buttons...")
                review_buttons = driver.find_elements(By.XPATH, 
                    '//button[contains(text(), "review") or contains(text(), "Review") or contains(text(), "See All")]'
                )
                if review_buttons:
                    review_modal_button = review_buttons[0]
                    print(f"Found general review button: {review_modal_button.text}")
            
            # If found a button, click it to open the reviews modal
            if review_modal_button:
                print(f"Clicking review button to open modal: {review_modal_button.text}")
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", review_modal_button)
                time.sleep(1)
                driver.execute_script("arguments[0].click();", review_modal_button)  # Use JS click for reliability
                time.sleep(2.5)  # Give modal time to open
                
                # Wait for the modal to appear
                try:
                    WebDriverWait(driver, 10).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, ".modal.show, .modal.fade.in, [role='dialog'][aria-modal='true']"))
                    )
                    print("Modal dialog opened successfully")
                    time.sleep(1)  # Give a moment for contents to fully render
                except TimeoutException:
                    print("Modal didn't appear to open, but continuing...")
            else:
                # Fallback to anchor links
                print("No modal buttons found, looking for review links...")
                review_links = driver.find_elements(By.CSS_SELECTOR, 
                    'a[href*="review"], a[href*="rating"], a:contains("See All"), a:contains("All Reviews")'
                )
                if review_links:
                    print(f"Found review link: {review_links[0].text}")
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", review_links[0])
                    time.sleep(0.5)
                    driver.execute_script("arguments[0].click();", review_links[0])
                    time.sleep(2.5)
                else:
                    print("No review buttons or links found. Will try to extract reviews from current page.")
        except Exception as e:
            print(f"Error while trying to access reviews modal/page: {e}")
        
        # Process reviews across all pages (pagination handling)
        page_num = 1
        max_pages = 100  # Safety limit
        reviews_processed = 0
        consecutive_empty_pages = 0  # Counter for pages with no new reviews
        
        while page_num <= max_pages:
            print(f"\n--- Processing reviews page {page_num} ---")
            
            # Get the current page source (after modal opened or page navigation)
            page_source = driver.page_source
            soup = BeautifulSoup(page_source, 'html.parser')
            
            # Find the modal container if present
            modal_containers = soup.select('.modal.show, .modal.fade.in, .modal-dialog, [role="dialog"], [aria-modal="true"]')
            if modal_containers:
                print(f"Found {len(modal_containers)} modal containers")
                # Use the first visible modal container
                review_container = modal_containers[0]
            else:
                print("No modal container found, using full page")
                review_container = soup
            
            # Find all review items within the container
            review_items = []
            
            # Try specific review selectors first
            review_selectors = [
                '.review-item', '.review-card', '.review', '.testimonial', 
                '[class*="review"]', '[id*="review"]'
            ]
            
            for selector in review_selectors:
                items = review_container.select(selector)
                if items and len(items) > 0:
                    print(f"Found {len(items)} review items with selector: {selector}")
                    review_items = items
                    break
            
            # If no review items found with specific selectors, look for more generic containers
            if not review_items:
                # Look for paragraphs inside the modal that might contain reviews
                paragraph_containers = review_container.select('.modal-body p, .review-container p')
                if paragraph_containers and len(paragraph_containers) > 1:
                    print(f"Found {len(paragraph_containers)} paragraphs that might contain reviews")
                    review_items = paragraph_containers
            
            # Process each review item
            new_reviews_on_page = 0
            
            if review_items:
                print(f"Processing {len(review_items)} potential review items...")
                for idx, item in enumerate(review_items):
                    try:
                        # Skip empty or very short items
                        item_text = item.get_text(strip=True)
                        if len(item_text) < 20:
                            continue
                        
                        review_data = {}
                        
                        # Generate unique review ID
                        review_id = f"{company_id}_review_{int(time.time())}_{reviews_processed+idx+1}"
                        review_data['id'] = review_id
                        
                        # Extract review text - focusing on paragraph elements which usually contain the actual review
                        review_text = ""
                        paragraphs = item.select('p')
                        for p in paragraphs:
                            p_text = clean_text(p.get_text())
                            # Skip attribution paragraphs (usually shorter)
                            if len(p_text) > 25 and 'Posted by' not in p_text and not p_text.startswith('on '):
                                review_text = p_text
                                break
                        
                        # If no paragraph with good content, try the item's full text
                        if not review_text:
                            # Try to get content from a div with the review text
                            content_divs = item.select('.review-text, .review-content, .review-body')
                            if content_divs:
                                review_text = clean_text(content_divs[0].get_text())
                            else:
                                # Last resort: use the full item text but try to filter out metadata
                                item_text = clean_text(item.get_text())
                                # Keep only first 80% of text to avoid attribution info at the end
                                review_text = item_text[:int(len(item_text) * 0.8)]
                        
                        if review_text:
                            review_data['text'] = review_text
                            
                            # Extract review title/heading if present
                            heading_elements = item.select('h3, h4, h5, .review-title, .review-heading, strong')
                            review_heading = None
                            for heading_elem in heading_elements:
                                heading_text = clean_text(heading_elem.get_text())
                                if heading_text and len(heading_text) > 5 and len(heading_text) < 100:
                                    review_heading = heading_text
                                    break
                            
                            # Combine title and text if appropriate
                            if review_heading and review_heading not in review_text:
                                review_data['text'] = f"{review_heading}: {review_text}"
                            
                            # Extract review date
                            review_date = "Unknown"
                            
                            # Look specifically for the EnergySage date format in text-gray-600 div
                            date_container = item.select('div.text-gray-600 span.d-inline-block')
                            if date_container:
                                date_text = clean_text(date_container[0].get_text())
                                if date_text:
                                    review_date = date_text
                                    print(f"Found date in EnergySage format: {review_date}")
                            
                            # If not found, try generic date elements
                            if review_date == "Unknown":
                                date_elements = item.select('.date, .review-date, .timestamp, [class*="date"]')
                                if date_elements:
                                    date_text = clean_text(date_elements[0].get_text())
                                    if date_text and len(date_text) < 30:  # Reasonable date length
                                        review_date = date_text
                            
                            # If still not found, try to extract from "on DATE" pattern
                            if review_date == "Unknown":
                                date_match = re.search(r'on\s+([A-Za-z]{3}\s+\d{1,2},?\s+\d{4}|[A-Za-z]{3}\s+\d{1,2})', item_text)
                                if date_match:
                                    review_date = date_match.group(1).strip()
                            
                            # If still not found, look for any date-like pattern in the text
                            if review_date == "Unknown":
                                date_pattern = re.search(r'([A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4})', item_text)
                                if date_pattern:
                                    review_date = date_pattern.group(1).strip()
                            
                            review_data['date'] = review_date
                            
                            # Extract reviewer name
                            reviewer_name = "Anonymous"
                            
                            # Look specifically for EnergySage reviewer format
                            reviewer_match = re.search(r'Posted by\s+(\w+)\s+on', item_text)
                            if reviewer_match:
                                reviewer_name = reviewer_match.group(1).strip()
                                print(f"Found reviewer in EnergySage format: {reviewer_name}")
                            # If not found, try elements with reviewer name
                            elif review_date == "Unknown":
                                name_elements = item.select('.reviewer-name, .author, [class*="reviewer"], [class*="author"]')
                                if name_elements:
                                    name_text = clean_text(name_elements[0].get_text())
                                    if name_text and len(name_text) < 50:  # Reasonable name length
                                        reviewer_name = name_text
                                        # Remove "Posted by" if present
                                        if 'Posted by' in reviewer_name:
                                            reviewer_name = reviewer_name.split('Posted by')[1].split('on')[0].strip()
                            
                            # If no specific element found, try to extract from "Posted by" text
                            if reviewer_name == "Anonymous":
                                posted_match = re.search(r'Posted by\s+([^on]{2,40}?)(?:\s+on\s|\n|$)', item_text)
                                if posted_match:
                                    reviewer_name = posted_match.group(1).strip()
                            
                            review_data['reviewer_name'] = reviewer_name
                            
                            # Extract rating (stars)
                            stars = 0
                            
                            # Look for numeric rating in text
                            rating_elements = item.select('.rating, .stars, [class*="rating"], [class*="star"]')
                            for elem in rating_elements:
                                rating_text = elem.get_text(strip=True)
                                rating_match = re.search(r'(\d+\.?\d*)\s*/?\s*\d*', rating_text)
                                if rating_match:
                                    try:
                                        stars = float(rating_match.group(1))
                                        break
                                    except:
                                        pass
                            
                            # If no rating found in text, count star icons
                            if stars == 0:
                                filled_stars = len(item.select('.fa-star, .fas.fa-star, [class*="star-fill"], [class*="star-full"]'))
                                if filled_stars > 0:
                                    stars = filled_stars
                            
                            # Use aggregate rating as fallback
                            if stars == 0:
                                stars = result["aggregate_rating"] if result["aggregate_rating"] > 0 else 5.0
                                
                            review_data['rating'] = stars
                            
                            # Create a fingerprint to detect duplicate reviews
                            review_fingerprint = f"{reviewer_name}|{review_date}|{review_text[:50]}"
                            
                            # Add to results if not a duplicate
                            if review_fingerprint not in seen_reviews:
                                seen_reviews.add(review_fingerprint)
                                valid_reviews.append(review_data)
                                new_reviews_on_page += 1
                                reviews_processed += 1
                                
                                # Print review info (truncated to avoid excessive output)
                                review_preview = review_text[:70] + "..." if len(review_text) > 70 else review_text
                                print(f"Extracted review {len(valid_reviews)}: {reviewer_name}, {stars}★ - {review_preview}")
                    
                    except Exception as e:
                        print(f"Error processing review item {idx+1}: {e}")
                
                print(f"Extracted {new_reviews_on_page} new reviews from page {page_num}. Total reviews so far: {len(valid_reviews)}")
                
                # If we didn't find any new reviews on this page, increment counter
                if new_reviews_on_page == 0:
                    consecutive_empty_pages += 1
                    print(f"Warning: No new reviews found on page {page_num}. Consecutive empty pages: {consecutive_empty_pages}")
                    
                    # Stop if we've seen too many consecutive pages with no new reviews
                    if consecutive_empty_pages >= 3:
                        print("Too many consecutive pages with no new reviews. Stopping pagination.")
                        break
                else:
                    # Reset counter if we found reviews
                    consecutive_empty_pages = 0
                
                # Stop if we've reached our expected total
                if total_reviews > 0 and len(valid_reviews) >= total_reviews:
                    print(f"Reached expected total of {total_reviews} reviews. Stopping pagination.")
                    break
                
                # IMPROVED PAGINATION HANDLING BASED ON EXACT HTML STRUCTURE
                try:
                    print("Looking for pagination controls in modal...")
                    
                    # Find the pagination container with the exact class
                    pagination = driver.find_elements(By.CSS_SELECTOR, "ul.pagination")
                    if pagination:
                        print("Found pagination control container")
                        
                        # Look for the active page item first
                        active_page = driver.find_element(By.CSS_SELECTOR, "li.page-item.active")
                        if active_page:
                            print(f"Found active page: {active_page.text}")
                            
                            # Find the next page link - it should be a direct sibling of the active page
                            next_page_link = None
                            
                            # Method 1: Try to find the next page directly with CSS
                            next_page_items = driver.find_elements(By.CSS_SELECTOR, 
                                "li.page-item:not(.active):not(.disabled) a.page-link[data-api-url]"
                            )
                            
                            # Filter to find the next page number
                            try:
                                # Strip any extra text like "(current)" from the active page element
                                clean_page_text = active_page.text.strip().split('\n')[0].strip()
                                current_page_num = int(clean_page_text)
                                print(f"Current page number: {current_page_num}")
                                
                                for item in next_page_items:
                                    # Check if this is a numbered page
                                    page_text = item.text.strip()
                                    try:
                                        page_num = int(page_text)
                                        if page_num == current_page_num + 1:
                                            next_page_link = item
                                            print(f"Found next page link to page {page_num}")
                                            break
                                    except ValueError:
                                        # This might be the "Next" button with arrow
                                        if "next" in item.get_attribute("class").lower() or ">" in page_text:
                                            next_page_link = item
                                            print("Found 'Next' button")
                                            break
                            except ValueError as e:
                                print(f"Warning: Could not parse page number: {active_page.text} - {e}")
                                # Fallback to using the Next button directly
                                for item in next_page_items:
                                    if "next" in item.get_attribute("class").lower() or ">" in item.text:
                                        next_page_link = item
                                        print("Falling back to 'Next' button")
                                        break

                            # If we found a next page link, click it
                            if next_page_link:
                                # Get the API URL from the data attribute for debugging
                                api_url = next_page_link.get_attribute("data-api-url")
                                print(f"Next page API URL: {api_url}")
                                
                                # Click the link
                                print("Clicking next page link...")
                                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", next_page_link)
                                time.sleep(0.5)
                                driver.execute_script("arguments[0].click();", next_page_link)
                                
                                # Wait for content to update
                                time.sleep(2.5)
                                page_num += 1
                            else:
                                print("No next page link found - must be on the last page")
                                break
                        else:
                            print("Could not find active page indicator")
                            break
                    else:
                        print("No pagination controls found")
                        break
                        
                except Exception as e:
                    print(f"Error with pagination navigation: {e}")
                    break
            else:
                print("No review items found on page. Stopping pagination.")
                break
        
        # Update the result with valid reviews
        result["reviews"] = valid_reviews
        print(f"\nSuccessfully extracted {len(valid_reviews)} unique reviews")
        
        # If we found reviews but have no aggregate rating, calculate it
        if result["aggregate_rating"] == 0 and valid_reviews:
            ratings = [r['rating'] for r in valid_reviews if r['rating'] > 0]
            if ratings:
                result["aggregate_rating"] = sum(ratings) / len(ratings)
                print(f"Calculated aggregate rating from reviews: {result['aggregate_rating']:.1f}")
        
        # Report success/failure compared to expected total
        if total_reviews > 0:
            if len(valid_reviews) >= total_reviews:
                print(f"SUCCESS! Captured all {total_reviews} expected reviews.")
            else:
                print(f"WARNING: Only captured {len(valid_reviews)} out of {total_reviews} expected reviews.")
                print(f"Coverage: {(len(valid_reviews)/total_reviews)*100:.1f}% of expected reviews")
            
    except Exception as e:
        print(f"Error in review extraction process: {e}")
    
    return result

def scrape_installer_details(profile_url):
    """
    Test function to scrape details (states served, headquarters, and other locations) from a single installer's page
    
    Args:
        profile_url: URL of the installer's profile page
        
    Returns:
        Dictionary with states_served, headquarters, and other_locations
    """
    print(f"Setting up WebDriver for individual scraping test...")
    
    # Selenium setup
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
        return {"states_served": [], "headquarters": "Error retrieving", "other_locations": [], "gallery_images": [], "reviews_data": {"aggregate_rating": 0, "reviews": []}}
    
    result = {
        "states_served": [],
        "headquarters": "N/A",
        "other_locations": [],
        "gallery_images": [],
        "reviews_data": {"aggregate_rating": 0, "reviews": []}
    }
    
    # Track unique locations to avoid duplicates
    unique_locations = set()
    
    try:
        print(f"Navigating to: {profile_url}")
        driver.get(profile_url)
        
        # Extract company ID from URL
        company_id = profile_url.split('/')[-2] if profile_url.endswith('/') else profile_url.split('/')[-1]
        
        # Wait for page to load
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        
        print("Page loaded successfully. Looking for installer details...")
        time.sleep(2)  # Give the page a moment to fully render
        
        # Parse with BeautifulSoup
        page_source = driver.page_source
        soup = BeautifulSoup(page_source, 'html.parser')
        
        # Get company name from the page title
        company_name = soup.title.string.split('|')[0].strip() if soup.title else "Unknown Company"
        
        # PART 0: Extract company logo
        # Look for logo image in various locations on the page
        print("Looking for company logo...")
        logo_selectors = [
            # EnergySage specific selectors based on observed HTML
            'img[alt$="logo"]',  # Images with alt text ending with "logo"
            'img[alt*="' + company_name + '"]',  # Images with company name in alt
            'img[src*="cloudinary.com/energysage/image/fetch"]',  # Cloudinary hosted images like the example
            'img[src*="es-media-prod"]',  # EnergySage media URLs
            # Generic selectors
            'img[alt*="logo" i]',  # Images with "logo" in alt text (case insensitive)
            'img[src*="logo" i]',  # Images with "logo" in src URL
            'img[alt*="' + company_name + '" i]',  # Images with company name in alt text
            '.supplier-logo img', '.company-logo img',  # Common class names for logo containers
            '.logo img', '#logo img',  # More common logo container selectors
            '.header img', '.navbar-brand img'  # Header areas that might contain logos
        ]
        
        for selector in logo_selectors:
            logo_img = soup.select_one(selector)
            if logo_img and logo_img.get('src'):
                # Found a logo
                result["logo_url"] = logo_img.get('src', '')
                result["logo_alt"] = logo_img.get('alt', company_name + ' logo')
                print(f"Found company logo: {result['logo_url']}")
                break
        
        # If still not found, try more direct approach for EnergySage structure
        if not result["logo_url"]:
            # Try direct attribute search for width/height 200 images which are likely logos
            logo_img = soup.find('img', attrs={'width': '200', 'height': '200'})
            if logo_img and logo_img.get('src'):
                result["logo_url"] = logo_img.get('src', '')
                result["logo_alt"] = logo_img.get('alt', company_name + ' logo')
                print(f"Found company logo with exact dimensions: {result['logo_url']}")
        
        if not result["logo_url"]:
            print("No logo found with standard selectors, trying more generic approach...")
            # If no logo found, try to find a prominent image at the top of the page
            header_sections = soup.select('header, .header, .navbar, .company-header, .supplier-header')
            for section in header_sections:
                logo_img = section.find('img')
                if logo_img and logo_img.get('src'):
                    result["logo_url"] = logo_img.get('src', '')
                    result["logo_alt"] = logo_img.get('alt', company_name + ' logo')
                    print(f"Found potential logo in header: {result['logo_url']}")
                    break
        
        # PART 1: Extract states served
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
                    result["states_served"] = sorted(list(set(states)))  # Remove duplicates and sort
                    break
                
                # If no links found, try to get text directly
                if not result["states_served"] and states_div.text.strip():
                    states_text = states_div.text.strip()
                    print(f"Found states text: {states_text}")
                    # Try to parse states from text (comma-separated list)
                    if ',' in states_text:
                        states = [state.strip() for state in states_text.split(',')]
                        result["states_served"] = sorted(list(set(states)))
                        break
        
        if result["states_served"]:
            print(f"Found {len(result['states_served'])} states served: {', '.join(result['states_served'])}")
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
                result["states_served"] = found_states
        
        # PART 2: Extract headquarters information
        # Try multiple potential selectors for headquarters
        hq_selectors = [
            {'type': 'class', 'value': 'headquarters'},
            {'type': 'class', 'value': 'company-address'},
            {'type': 'class', 'value': 'address'},
            {'type': 'class', 'value': 'location'}
        ]
            
        for selector in hq_selectors:
            hq_div = soup.find('div', class_=selector['value'])
            if hq_div:
                print(f"Found headquarters using class='{selector['value']}'")
                
                # Try different patterns within the HQ div
                address_li = hq_div.find('li', class_='supplier-address')
                if address_li:
                    address_p = address_li.find('p', class_='d-none d-md-block') or address_li.find('p')
                    if address_p:
                        # Apply clean_text function to normalize formatting
                        result["headquarters"] = clean_text(' '.join(address_p.stripped_strings))
                        break
                else:
                    # If no li.supplier-address, just get all text from div and clean it
                    result["headquarters"] = clean_text(' '.join(hq_div.stripped_strings))
                    break
        
        if result["headquarters"] != "N/A":
            print(f"Found headquarters: {result['headquarters']}")
        else:
            print("No headquarters information found.")
        
        # PART 3: Extract other locations information
        # Look for "Other Locations" section - typically this follows the headquarters section
        other_locations_selectors = [
            {'type': 'h3', 'text': 'Other Locations'},
            {'type': 'class', 'value': 'other-locations'},
            {'type': 'class', 'value': 'locations'},
            {'type': 'class', 'value': 'branches'}  # Added based on HTML snippet provided
        ]
        
        # First try to find the "Other Locations" heading
        other_locations_heading = None
        for selector in other_locations_selectors:
            if selector['type'] == 'h3':
                other_locations_heading = soup.find('h3', string=lambda text: text and selector['text'] in text)
            elif selector['type'] == 'class':
                other_locations_heading = soup.find(lambda tag: tag.has_attr('class') and selector['value'] in tag['class'])
            
            if other_locations_heading:
                print(f"Found other locations section using {selector['type']}='{selector.get('text', selector.get('value'))}'")
                break
        
        if other_locations_heading:
            # Look for location list items following the heading
            # First try to find the ul.list-unstyled directly following the heading
            locations_list = other_locations_heading.find_next('ul', class_='list-unstyled')
            
            if not locations_list:
                # If not found with class, try any ul element
                locations_list = other_locations_heading.find_next('ul')
            
            if not locations_list:
                # Try parent's next sibling 
                parent = other_locations_heading.parent
                if parent:
                    locations_list = parent.find('ul', class_='list-unstyled') or parent.find_next('ul')
            
            if locations_list:
                location_items = locations_list.find_all('li')
                for item in location_items:
                    # For each li, look for the desktop version first (more clean text)
                    desktop_p = item.find('p', class_='d-none d-md-block')
                    if desktop_p:
                        # Convert newlines to commas and extract text, then clean it
                        location_text = clean_text(desktop_p.get_text(separator=' ', strip=True).replace('\n', ', '))
                        if location_text and location_text not in unique_locations:
                            unique_locations.add(location_text)
                            result["other_locations"].append(location_text)
                            continue
                    
                    # If desktop version not found or empty, try mobile version
                    mobile_p = item.find('p', class_='my-0')
                    if mobile_p:
                        # Process similar to desktop version
                        location_text = clean_text(mobile_p.get_text(separator=' ', strip=True).replace('\n', ', '))
                        # Remove the SVG icon text if present
                        if 'M8.604' in location_text:
                            location_text = location_text.split('M8.604')[0].strip()
                        if location_text and location_text not in unique_locations:
                            unique_locations.add(location_text)
                            result["other_locations"].append(location_text)
                            continue
                    
                    # If no p tags found, just get all text
                    if not desktop_p and not mobile_p:
                        location_text = clean_text(' '.join(item.stripped_strings))
                        if location_text and location_text not in unique_locations:
                            unique_locations.add(location_text)
                            result["other_locations"].append(location_text)
            
            # If no list items found, try looking for paragraphs or div containers
            if not result["other_locations"]:
                location_containers = other_locations_heading.find_next_siblings(['p', 'div'])
                for container in location_containers[:5]:  # Limit to first 5 to avoid going too far
                    location_text = ' '.join(container.stripped_strings)
                    if location_text.strip() and location_text.strip() not in unique_locations:
                        unique_locations.add(location_text.strip())
                        result["other_locations"].append(location_text.strip())
        
        # Alternative approach: look for location divs directly
        if not result["other_locations"]:
            print("Looking for other locations using alternative approach...")
            
            # Look for multiple address elements or location divs
            address_elements = soup.find_all('li', class_='supplier-address')
            if len(address_elements) > 1:  # If more than one address, the others are likely additional locations
                for address in address_elements[1:]:  # Skip the first one (headquarters)
                    address_p = address.find('p', class_='d-none d-md-block') or address.find('p')
                    if address_p:
                        location_text = ' '.join(address_p.stripped_strings)
                        if location_text.strip() and location_text.strip() not in unique_locations:
                            unique_locations.add(location_text.strip())
                            result["other_locations"].append(location_text.strip())
        
        if result["other_locations"]:
            print(f"Found {len(result['other_locations'])} other locations:")
            for idx, loc in enumerate(result["other_locations"]):
                print(f"  {idx+1}. {loc}")
        else:
            print("No other locations found.")
        
        # PART 4: Scrape the gallery images
        gallery_images = scrape_installer_gallery(driver, company_id, company_name)
        result["gallery_images"] = gallery_images
        
        # PART 5: Scrape company reviews
        reviews_data = scrape_company_reviews(driver, company_id, company_name, profile_url)
        result["reviews_data"] = reviews_data
            
    except Exception as e:
        print(f"Error during scraping: {e}")
    finally:
        print("Closing browser...")
        driver.quit()
        
    return result

def main():
    # Load the first installer from the CSV file
    csv_file = 'massachusetts_solar_installers.csv'
    test_output_file = 'test_installer_details.csv'
    
    try:
        with open(csv_file, 'r', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            # Get just the first row
            first_installer = next(reader)
            
            print(f"Test scraping for a single installer:")
            print(f"ID: {first_installer['id']}")
            print(f"Name: {first_installer['company_name']}")
            print(f"Profile URL: {first_installer['profile_url']}")
            
            # Scrape details for this installer
            details = scrape_installer_details(first_installer['profile_url'])
            
            print("\nTest Results:")
            print(f"Company: {first_installer['company_name']}")
            print(f"States Served: {', '.join(details['states_served']) if details['states_served'] else 'None found'}")
            print(f"Headquarters: {details['headquarters']}")
            print(f"Other Locations: {len(details['other_locations'])} found")
            for idx, loc in enumerate(details['other_locations']):
                print(f"  {idx+1}. {loc}")
            
            # Count images and videos
            image_count = sum(1 for item in details['gallery_images'] if item.get('type') == 'image')
            video_count = sum(1 for item in details['gallery_images'] if item.get('type') == 'video')
            print(f"Gallery Media: {len(details['gallery_images'])} items total ({image_count} images, {video_count} videos)")
            
            # Create a test CSV file with the results
            print(f"\nCreating test CSV file: {test_output_file}")
            
            # Define fieldnames for the test CSV with a single other_locations column
            fieldnames = [
                'id', 'company_name', 'description', 'profile_url', 
                'states_served', 'headquarters', 'other_locations', 'gallery_media',
                'image_count', 'video_count', 'aggregate_rating', 'review_count'
            ]
            
            # Format the other locations using a special separator that's compatible with Excel
            # Using pipe symbols which are less likely to appear in addresses
            other_locations_str = ' | '.join(details['other_locations']) if details['other_locations'] else ''
            
            # For gallery media, include the media IDs rather than URLs
            media_ids = [media_info['id'] for media_info in details['gallery_images']] if details['gallery_images'] else []
            gallery_media_str = ' | '.join(media_ids)
            
            # Debug output to verify data
            print(f"\nData being written to CSV:")
            print(f"Headquarters: {details['headquarters']}")
            print(f"Other Locations: {other_locations_str}")
            print(f"Gallery Media: {len(details['gallery_images'])} items with unique IDs ({image_count} images, {video_count} videos)")
            print(f"Aggregate Rating: {details['reviews_data']['aggregate_rating']}")
            print(f"Reviews: {len(details['reviews_data']['reviews'])} found")
            
            # Prepare the row data
            test_row = {
                'id': first_installer['id'],
                'company_name': first_installer['company_name'],
                'description': clean_text(first_installer['description'][:200] + "..."),  # Truncate and clean description 
                'profile_url': first_installer['profile_url'],
                'states_served': ','.join(details['states_served']) if details['states_served'] else '',
                'headquarters': details['headquarters'],  # Already cleaned during extraction
                'other_locations': other_locations_str,  # Already cleaned during extraction of each location
                'gallery_media': gallery_media_str,
                'image_count': image_count,
                'video_count': video_count,
                'aggregate_rating': details['reviews_data']['aggregate_rating'],
                'review_count': len(details['reviews_data']['reviews'])
            }
            
            # First try to create a TSV (tab-separated) format which often works better in Excel
            tsv_output_file = 'test_installer_details.tsv'
            print(f"\nCreating TSV file for better compatibility: {tsv_output_file}")
            
            with open(tsv_output_file, 'w', newline='', encoding='utf-8-sig') as outfile:
                writer = csv.DictWriter(
                    outfile, 
                    fieldnames=fieldnames,
                    quoting=csv.QUOTE_MINIMAL,
                    delimiter='\t'  # Tab delimiter
                )
                writer.writeheader()
                writer.writerow(test_row)
            
            # Also create a standard CSV with extra compatibility measures
            with open(test_output_file, 'w', newline='', encoding='utf-8-sig') as outfile:
                # First write a UTF-8 BOM marker to help Excel with encoding
                # Write directly to ensure clean output
                # Write the CSV manually to have complete control
                outfile.write(','.join(fieldnames) + '\n')
                
                # Create the line with careful quoting
                values = []
                for field in fieldnames:
                    if field in ['other_locations', 'gallery_media']:
                        # Special handling for other_locations to ensure visibility
                        field_value = test_row[field]
                        values.append('"' + field_value.replace('"', '""') + '"')
                    else:
                        # Quote if needed
                        value = str(test_row[field]).replace('"', '""')
                        if ',' in value or '\n' in value:
                            values.append('"' + value + '"')
                        else:
                            values.append(value)
                
                outfile.write(','.join(values) + '\n')
            
            # Create a separate CSV file for the media catalog
            if details['gallery_images']:
                media_csv_file = 'media_catalog.csv'
                print(f"\nCreating media catalog CSV: {media_csv_file}")
                
                # Define fields for the media catalog
                media_fieldnames = [
                    'company_id', 'company_name', 'media_id', 'media_type', 
                    'url', 'local_path', 'filename',
                    'video_platform', 'video_id', 'video_url'
                ]
                
                with open(media_csv_file, 'w', newline='', encoding='utf-8-sig') as mediafile:
                    mediawriter = csv.DictWriter(
                        mediafile,
                        fieldnames=media_fieldnames,
                        quoting=csv.QUOTE_ALL
                    )
                    mediawriter.writeheader()
                    
                    for media_info in details['gallery_images']:
                        media_row = {
                            'company_id': first_installer['id'],
                            'company_name': first_installer['company_name'],
                            'media_id': media_info['id'],
                            'media_type': media_info.get('type', 'image')  # Default to image for backward compatibility
                        }
                        
                        # Handle different media types
                        if media_info.get('type') == 'video':
                            # For videos
                            media_row['url'] = media_info.get('thumbnail_url', '')
                            media_row['local_path'] = media_info.get('thumbnail_path', '')
                            media_row['filename'] = media_info.get('filename', '')
                            media_row['video_platform'] = media_info.get('platform', '')
                            media_row['video_id'] = media_info.get('video_id', '')
                            media_row['video_url'] = media_info.get('video_url', '')
                        else:
                            # For images
                            media_row['url'] = media_info.get('url', '')
                            media_row['local_path'] = media_info.get('path', '')
                            media_row['filename'] = media_info.get('filename', '')
                            media_row['video_platform'] = ''
                            media_row['video_id'] = ''
                            media_row['video_url'] = ''
                            
                        mediawriter.writerow(media_row)
                
                print(f"Media catalog saved to: {os.path.abspath(media_csv_file)}")
            
            # Create a separate CSV file just for the reviews
            if details['reviews_data']['reviews']:
                reviews_csv_file = 'reviews_catalog.csv'
                print(f"\nCreating reviews catalog CSV: {reviews_csv_file}")
                
                reviews_fieldnames = ['company_id', 'company_name', 'review_id', 'reviewer_name', 'review_date', 'rating', 'review_text']
                
                with open(reviews_csv_file, 'w', newline='', encoding='utf-8-sig') as reviewfile:
                    reviewwriter = csv.DictWriter(
                        reviewfile,
                        fieldnames=reviews_fieldnames,
                        quoting=csv.QUOTE_ALL
                    )
                    reviewwriter.writeheader()
                    
                    for review in details['reviews_data']['reviews']:
                        reviewwriter.writerow({
                            'company_id': first_installer['id'],
                            'company_name': first_installer['company_name'],
                            'review_id': review['id'],
                            'reviewer_name': review['reviewer_name'],
                            'review_date': review['date'],
                            'rating': review['rating'],
                            'review_text': review['text']
                        })
                
                print(f"Reviews catalog saved to: {os.path.abspath(reviews_csv_file)}")
            
            print(f"\nTest completed. Data saved to:")
            print(f"1. CSV: {os.path.abspath(test_output_file)}")
            print(f"2. TSV: {os.path.abspath(tsv_output_file)}")
            if details['gallery_images']:
                company_folder = f"images/{first_installer['id']}_{first_installer['company_name'].replace(' ', '_')}"
                print(f"3. Media: {os.path.abspath(company_folder)}")
                print(f"   - Images: {image_count}")
                print(f"   - Videos: {video_count}")
                print(f"4. Media Catalog: {os.path.abspath(media_csv_file)}")
            if details['reviews_data']['reviews']:
                print(f"5. Reviews: {os.path.abspath(reviews_csv_file)}")
            print(f"\nIf the CSV doesn't display correctly, please try opening the TSV file.")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main() 