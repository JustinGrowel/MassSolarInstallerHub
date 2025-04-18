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
        # First, return to the main installer page
        print(f"Navigating back to main installer page: {profile_url}")
        driver.get(profile_url)
        
        # Wait for the page to load
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        time.sleep(2)  # Give the page a moment to fully render
        
        # Look for aggregate rating on main page first
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
        
        # Directly use the URL method with parameters to access the reviews
        direct_url = f"{profile_url}?limit=4&offset=0"
        print(f"Using direct URL approach to access reviews: {direct_url}")
        driver.get(direct_url)
        
        # Wait for the page to load
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        time.sleep(2)  # Give the page time to load
        
        # Now extract the reviews
        page_source = driver.page_source
        soup = BeautifulSoup(page_source, 'html.parser')
        
        # Look for the review cards first - EnergySage specific selectors based on the HTML
        review_containers = []
        review_card_selector = '.review-card'
        review_cards = soup.select(review_card_selector)
        
        if review_cards:
            review_containers = review_cards
            print(f"Found {len(review_cards)} review cards with selector: {review_card_selector}")
        else:
            # Fallback to more generic selectors if specific cards aren't found
            review_selectors = [
                '.review', 
                '[id*="review"]', 
                '.testimonial', 
                '.reviews-container .review-item',
                '.rating-list .review-entry'
            ]
            
            for selector in review_selectors:
                containers = soup.select(selector)
                if containers:
                    review_containers.extend(containers)
                    print(f"Found {len(containers)} review containers with selector: {selector}")
        
        # Double check for reviews that might be displayed directly on the page in a list
        if not review_containers:
            # Looking at the HTML you shared, this is more specific to the EnergySage structure
            possible_reviews = soup.find_all(['div', 'article'], class_=lambda c: c and ('review' in (c.lower() if isinstance(c, str) else ' '.join(c).lower())))
            if possible_reviews:
                review_containers.extend(possible_reviews)
                print(f"Found {len(possible_reviews)} potential review containers")
        
        # Process review containers
        valid_reviews = []
        for idx, container in enumerate(review_containers):
            try:
                review_data = {}
                
                # Generate unique review ID
                review_id = f"{company_id}_review_{int(time.time())}_{idx+1}"
                review_data['id'] = review_id
                
                # Extract review text - first try to find the review body paragraph
                review_text_elem = container.find('p', class_='review-body')
                if not review_text_elem:
                    # Fallbacks if specific class not found
                    review_text_elem = container.find(['p', 'div'], class_=lambda c: c and 'text' in (c.lower() if isinstance(c, str) else ''))
                    if not review_text_elem:
                        review_text_elem = container.find('p')  # Just find any paragraph
                
                if review_text_elem:
                    review_text = clean_text(review_text_elem.get_text())
                    
                    # Only proceed if we have meaningful text (not just a few characters)
                    if len(review_text) > 10:
                        review_data['text'] = review_text
                        
                        # Extract reviewer name - first check for the text-gray-700 div that contains reviewer info
                        reviewer_div = container.find('div', class_='text-gray-700')
                        reviewer_name = "Anonymous"
                        
                        if reviewer_div:
                            # In EnergySage, the reviewer name is the first part before "on"
                            reviewer_text = clean_text(reviewer_div.get_text())
                            
                            # Handle various formats for the reviewer information
                            if 'on' in reviewer_text:
                                # Extract the reviewer name - it's before "on" 
                                name_part = reviewer_text.split('on')[0].strip()
                                # Remove "Posted by" or similar text if present
                                if 'Posted by' in name_part:
                                    name_part = name_part.replace('Posted by', '').strip()
                                if name_part and len(name_part) < 50:  # Reasonable name length
                                    reviewer_name = name_part
                            else:
                                # If no "on" delimiter, try to extract from the beginning
                                if reviewer_text and len(reviewer_text) < 50:
                                    reviewer_name = reviewer_text
                        else:
                            # Fallback to traditional selectors if the specific class isn't found
                            name_elem = container.find(['span', 'div'], class_=lambda c: c and any(x in (c.lower() if isinstance(c, str) else ' '.join(c).lower()) for x in ['author', 'name', 'poster', 'reviewer']))
                            if name_elem:
                                name_text = clean_text(name_elem.get_text())
                                if name_text and len(name_text) < 50:  # Reasonable name length
                                    reviewer_name = name_text
                                    
                                    # Clean common prefixes
                                    if reviewer_name.lower().startswith(('by ', 'from ', '- ')):
                                        reviewer_name = reviewer_name[reviewer_name.find(' ')+1:]
                                        
                        review_data['reviewer_name'] = reviewer_name
                        
                        # Extract date - if we have the reviewer_div, the date is after "on"
                        review_date = "Unknown"
                        
                        if reviewer_div:
                            reviewer_text = clean_text(reviewer_div.get_text())
                            if 'on' in reviewer_text:
                                date_part = reviewer_text.split('on')[1].strip()
                                if date_part and len(date_part) < 30:  # Reasonable date length
                                    review_date = date_part
                        else:
                            # Fallback to traditional date extraction
                            date_elem = container.find(['span', 'div', 'time'], class_=lambda c: c and 'date' in (c.lower() if isinstance(c, str) else ' '.join(c).lower()))
                            if date_elem:
                                date_text = clean_text(date_elem.get_text())
                                if date_text and len(date_text) < 30:  # Reasonable date length
                                    review_date = date_text
                                    
                                    # Clean common prefixes
                                    prefixes = ["posted on", "posted", "date:", "on", "published"]
                                    for prefix in prefixes:
                                        if review_date.lower().startswith(prefix):
                                            review_date = review_date[len(prefix):].strip()
                                            
                        review_data['date'] = review_date
                        
                        # Try to determine star rating - first look for star ratings in the specific review card
                        stars = 0
                        
                        # First check if there's a specific rating container
                        star_container = container.find('div', class_='review-card__rating-overall-stars')
                        if star_container:
                            # Count the SVG stars (full ones)
                            full_stars = len(star_container.select('svg.full'))
                            if full_stars:
                                stars = full_stars
                        
                        if stars == 0:
                            # Fallback to more generic star indicators
                            star_container = container.find(['div', 'span'], class_=lambda c: c and any(x in (c.lower() if isinstance(c, str) else ' '.join(c).lower()) for x in ['star', 'rating']))
                            if star_container:
                                # Count star SVGs, images, or rating text
                                full_stars = len(star_container.select('[class*="full"], [class*="filled"], .fa-star, svg'))
                                if full_stars:
                                    stars = full_stars
                                else:
                                    # Try to extract numerical rating
                                    rating_text = star_container.get_text(strip=True)
                                    rating_match = re.search(r'(\d+(?:\.\d+)?)', rating_text)
                                    if rating_match:
                                        try:
                                            stars = float(rating_match.group(1))
                                        except:
                                            pass
                        
                        review_data['rating'] = stars
                        
                        # Add valid review to list
                        valid_reviews.append(review_data)
                        print(f"Extracted review {len(valid_reviews)}: {reviewer_name}, {stars} stars, {review_date}")
            
            except Exception as e:
                print(f"Error processing review container {idx+1}: {e}")
        
        # Update result with valid reviews
        result["reviews"] = valid_reviews
        print(f"Successfully extracted {len(valid_reviews)} valid reviews")
        
        # If we found valid reviews but no aggregate rating, calculate it from reviews
        if result["aggregate_rating"] == 0 and valid_reviews:
            rated_reviews = [r['rating'] for r in valid_reviews if r['rating'] > 0]
            if rated_reviews:
                result["aggregate_rating"] = sum(rated_reviews) / len(rated_reviews)
                print(f"Calculated aggregate rating from reviews: {result['aggregate_rating']:.1f}")
                
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