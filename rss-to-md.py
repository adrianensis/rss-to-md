import urllib.parse
from lxml import etree
import urllib.request
import requests
import json
import sys
import os
import time
import random
import re
import shutil
import xml.etree.ElementTree as ET
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Any
from datetime import datetime, timezone, timedelta
from pathlib import Path 
from dateutil import parser
from datetime import date
from fake_useragent import UserAgent
import yt_dlp
from html.parser import HTMLParser

# ==============================================================================
# LOGGING UTILITY
# ==============================================================================

def log(msg: str, error: bool = False):
    if error:
        print(f"> #ERROR: {msg}")
    else:
        print(f"> log: {msg}")

# ==============================================================================
# GLOBAL CONFIGURATION
# ==============================================================================

CONFIG = {}
CACHE = {}
CACHE_FILE = None
cache_lock = threading.Lock()
MAX_THREADS = 6  # Adjust based on your network and CPU
CACHE_DIR = Path("./rss_file_cache")
CACHE_EXPIRATION_MINUTES = 16 # youtube max-age expiration (900 seconds, 15 min)

def setup_environment(cache_path=None):
    global CACHE_FILE
    CACHE_FILE = cache_path
    if not CACHE_FILE:
        return
        
    parent_dir = Path(CACHE_FILE).parent
    try:
        # Ensure cache directory structure exists before operating on it
        os.makedirs(parent_dir, exist_ok=True)
        log(f"Cache path set to: {CACHE_FILE}")
        load_cache()
    except Exception as e:
        log(f"Error setting up cache: {e}", error=True)
        exit(1)

def load_cache():
    global CACHE
    if CACHE_FILE and os.path.exists(CACHE_FILE):
        try:
            # Load existing cache data from JSON file
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                CACHE = json.load(f)
            log(f"Cache loaded with {len(CACHE)} entries.")
        except (json.JSONDecodeError, IOError):
            # Fallback to an empty cache if loading fails or file is corrupt
            CACHE = {}
    else:
        CACHE = {}

def save_cache():
    if CACHE_FILE:
        # Acquire thread lock to safely write the cache dictionary to disk
        with cache_lock:
            try:
                with open(CACHE_FILE, 'w', encoding='utf-8') as f:
                    json.dump(CACHE, f, indent=4, ensure_ascii=False)
            except IOError as e:
                log(f"Error saving cache: {e}", error=True)

def get_cached_file_path(url: str) -> Path:
    import hashlib
    # Generate an MD5 hash of the URL to use as a unique filename
    url_hash = hashlib.md5(url.encode('utf-8')).hexdigest()
    return CACHE_DIR / f"{url_hash}.xml"

def is_cache_valid(file_path: Path) -> bool:
    if not file_path.exists():
        return False
    # Calculate file age based on its modification time
    file_age = time.time() - file_path.stat().st_mtime
    return file_age < (CACHE_EXPIRATION_MINUTES * 60)

# ==============================================================================
# SLEEP
# ==============================================================================

def sleep_random_range(a,b):
    # Generate a random delay within the specified millisecond range to mimic human behavior
    random_delay_ms = random.randint(a,b)
    log(f"[SLEEP]: {random_delay_ms} ms")
    time.sleep(random_delay_ms / 1000)
    
def sleep_random():
    # Call sleep with default range for request throttling
    sleep_random_range(200, 700)

# ==============================================================================
# RETRIEVE RSS LINKS AND DATA
# ==============================================================================

def replace_urls_with_rss_feeds(inputJSON, outputJSON):
    # Recursively crawls the input JSON and resolves website URLs to RSS feeds in parallel.
    tasks = []
    
    def collect_tasks(inner_in, inner_out):
        # Traverse dictionary elements to find url entries or nested categories
        for k, v in inner_in.items():
            if isinstance(v, list):
                if "feeds" not in inner_out:
                    inner_out["feeds"] = []
                    
                for u in v:
                    if k == "rss":
                        # Direct RSS feeds are added immediately
                        inner_out["feeds"].append(u)
                    elif k == "urls":
                        # General URLs need resolution tasks queued up
                        tasks.append((u, inner_out))
                    else:
                        log(f"Error, undefined URL/RSS list: {k}, only 'urls' or 'rss' are allowed", error=True)

            else:
                inner_out[k] = {}
                collect_tasks(v, inner_out[k])

    collect_tasks(inputJSON, outputJSON)

    if tasks:
        log(f"Resolving {len(tasks)} URLs to feeds using {MAX_THREADS} threads...")
        # Execute feed resolution concurrently using a ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
            future_to_url = {executor.submit(retrieve_rss_feed, t[0]): t for t in tasks}
            for future in as_completed(future_to_url):
                _, output_container = future_to_url[future]
                _, feed_url = future.result()
                if feed_url:
                    output_container["feeds"].append(feed_url)


def retrieve_rss_feed(url):
    # Worker function to find a feed for a single URL. Returns (original_url, feed_url).
    with cache_lock:
        if url in CACHE:
            log(f"[ok] URL found in cache: {url}")
            return url, CACHE[url]

    log(f"[--] URL NOT found in cache, retrieving: {url}")

    # Handle YouTube Playlist special case
    if "youtube.com/playlist?list=" in url:
        id_part = url.split("list=")[-1]
        feed_url = "https://www.youtube.com/feeds/videos.xml?playlist_id=" + id_part.split("&")[0]
        with cache_lock:
            # Cache the mapped RSS feed URL
            CACHE[url] = feed_url
        
        log(f"[+] RSS Link found for {url}: {feed_url}")
        return url, feed_url
        
    if ("youtube.com/channel" in url):
        id_part = url.split("channel/")[-1]
        feed_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={id_part}"
        with cache_lock:
            # Cache the channel feed URL
            CACHE[url] = feed_url
        
        log(f"[+] RSS Link found for {url}: {feed_url}")
        return url, feed_url

    if ("youtube.com/@" in url) or ("youtube.com/c/" in url):
        ydl_opts = {
            'extract_flat': True,
            'quiet': True,
            'no_warnings': True,
        }
        try:
            # Use yt_dlp to extract channel metadata for user-friendly YouTube URLs
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                print(f"Using YoutubeDL to retrieve channel metadata.")
                info = ydl.extract_info(
                    url,
                    download=False,
                )
            
            channel_id=info["channel_id"]
            print(f"YT channel ID {url}: {channel_id}")
            feed_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
            with cache_lock:
                # Cache the resolved YouTube handle/custom URL feed
                CACHE[url] = feed_url
            
            log(f"[+] RSS Link found for {url}: {feed_url}")
            return url, feed_url
        except Exception as e:
            log(f"Error retrieving {url}: {e}", error=True)
            return url, None

    # Initialize fake user agent
    ua = UserAgent()
    headers = {'User-Agent': ua.random}
    
    # Throttle requests using random delay
    sleep_random()

    try:
        # Request the target webpage to scrape feed links from HTML header
        response = requests.get(url, headers=headers, timeout=5)
        html_str = response.text

        tree = etree.HTML(html_str)
        base = tree.findall('.//base')
        base_url = base[0].attrib['href'] if base and 'href' in base[0].attrib else url

        # Search for link tags
        links = tree.findall("""head/link[@rel='alternate'][@type='application/atom+xml']""")
        links += tree.findall("""head/link[@rel='alternate'][@type='application/rss+xml']""")

        if "ivoox.com" in base_url:
            # Extract iVoox podcast RSS links using custom selectors
            ivoox_links = tree.findall(".//a[@rel='nofollow']")
            for link in ivoox_links:
                href = link.attrib.get('href', '').strip()
                if href and (".xml" in href):
                    links.append(link)

        for link in links:
            href = link.attrib.get('href', '').strip()
            if href:
                feed_url = urllib.parse.urljoin(base_url, href)
                with cache_lock:
                    # Cache the scraped feed link
                    CACHE[url] = feed_url
                log(f"[+] RSS Link found for {url}: {feed_url}")
                return url, feed_url
        
        # Heuristic fallback
        for suffix in ['feed', 'rss', 'feed.xml', 'rss.xml', '/feed', '/rss', '.rss']:
            try:
                potential_feed = urllib.parse.urljoin(base_url, suffix)
                response = requests.get(potential_feed, headers={'User-Agent': ua.random}, timeout=5)
                # Verify standard RSS/Atom signatures in response text
                if response.status_code == 200 and any(tag in response.text.lower() for tag in ['<rss', '<feed', '<rdf']):
                    with cache_lock:
                        # Cache the working heuristic feed endpoint
                        CACHE[url] = potential_feed
                    log(f"[+] RSS Link found for {url}: {potential_feed}")
                    return url, potential_feed
            except:
                continue

        log(f"[--] URL NOT found for: {url}")

    except Exception as e:
        log(f"Error retrieving {url}: {e}", error=True)
        pass
    
    return url, None

def download_rss_worker(url: str):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = get_cached_file_path(url)

    try:
        print(f'Retrieving RSS from {url}')
        content = None

        if is_cache_valid(cache_path):
            log(f"[CACHE HIT] Loading RSS from file: {url}")
            # Read cached XML file content from disk
            with open(cache_path, 'rb') as f:
                content = f.read()
        else:
            log(f"[CACHE MISS/EXPIRED] Fetching feed online: {url}")
            # Throttle network request
            sleep_random()
            response = requests.get(url, timeout=5)
            response.raise_for_status()
            content = response.content

            # Save newly fetched RSS content to cache file
            with open(cache_path, 'wb') as f:
                f.write(content)

        return generate_articles(url, content)
    except Exception as e:
        log(f"Error parsing RSS: {url} , Error: {e}", error=True)
        return url, "Unknown Source", []

# ==============================================================================
# EXTRACT CONTENT FROM HTML
#  ==============================================================================

class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.result = []
    
    def handle_data(self, data):
        # Accumulate text chunks parsed from HTML elements
        self.result.append(data)
    
    def get_text(self):
        return " ".join(self.result)

def extract_text_HTML(html_content: str) -> str:
    parser = TextExtractor()
    parser.feed(html_content)
    # Strip excessive whitespace and join text fragments
    return " ".join(parser.get_text().split())

def extract_image_from_html(html_content: str) -> str:
    if not html_content:
        return None
    # Use regular expression to find the first image source URL in HTML snippet
    match = re.search(r'<img [^>]*src="([^"]+)"', html_content)
    return match.group(1) if match else None

# ==============================================================================
# DATE TIME
# ==============================================================================

def parse_iso_date(date_str: str) -> datetime:
    if not date_str:
        return datetime.min.replace(tzinfo=timezone.utc)

    try:
        # Attempt standard ISO format parsing
        return datetime.fromisoformat(date_str)
    except Exception as e:
        try:
            # Fallback to dateutil parser for flexible date format parsing
            dt = parser.parse(date_str)
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt
        except:
            return datetime.min.replace(tzinfo=timezone.utc)

# ==============================================================================
# GENERATE RSS FOLDERS
# ==============================================================================

def generate_rss_folders(urlsJSON, folder, pathList, out_categories_data, url_to_feed):
    pathList.append(folder)
    current_dir = os.path.join(*pathList)
    # Ensure directory path exists for the category structure
    os.makedirs(current_dir, exist_ok=True)

    local_folder_latest_articles = []
    local_folder_articles_by_feed = {}

    for k, v in urlsJSON.items():
        if isinstance(v, dict) and "feeds" in v:
            feed_urls = v["feeds"]
            articles_by_feed = {}
            latest_articles = []

            log(f"Processing category '{k}': Downloading {len(feed_urls)} feeds...")
            # Concurrently download and process all feeds in the category
            with ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
                futures = [executor.submit(download_rss_worker, u) for u in feed_urls]
                for future in as_completed(futures):
                    url, feed_title, current_feed_articles = future.result()
                    url_to_feed[url] = feed_title
                    # Sort articles per feed by publication date in descending order
                    sorted_feed = sorted(current_feed_articles, key=lambda x: parse_iso_date(x['published']), reverse=True)
                    if sorted_feed:
                        # Collect top recent articles from this feed
                        latest_articles.extend(sorted_feed[:5])
                        local_folder_latest_articles.extend(sorted_feed[:5])
                    articles_by_feed[url] = sorted_feed
                    local_folder_articles_by_feed[url] = sorted_feed
            
            # Sort combined category latest articles by date descending
            sorted_latest = sorted(latest_articles, key=lambda x: parse_iso_date(x['published']), reverse=True)
            rss_articles_to_markdown(sorted_latest, articles_by_feed, url_to_feed, k, os.path.join(current_dir, k + ".md"))
            
            # Save category latest for external usages
            out_categories_data[k] = sorted_latest
            
        elif isinstance(v, dict):
            # Recursively process nested category folders
            generate_rss_folders(v, k, pathList, out_categories_data, url_to_feed)

    # Generate index markdown file for the folder level
    rss_articles_to_markdown(
        sorted(local_folder_latest_articles, key=lambda x: parse_iso_date(x['published']), reverse=True), 
        local_folder_articles_by_feed, url_to_feed, folder.replace(current_dir,'') + " Index", os.path.join(current_dir, "index.md")
    )

    pathList.pop()

# ==============================================================================
# ARTICLES
# ==============================================================================

def get_rss_title(root):
    channel = root.find('{*}channel')
    if channel is None:
        channel = root.find('./{*}channel')
    if channel is not None:
        title_el = channel.find('{*}title')
        if title_el is not None: return title_el.text
    atom_title = root.find('{http://www.w3.org/2005/Atom}title')
    return atom_title.text if atom_title is not None else "???"

def generate_articles(url, content):
    # Parse XML content string into an ElementTree root element
    root = ET.fromstring(content)
        
    items = root.findall('.//item') or root.findall('{*}item')
    items.extend(root.findall('{*}entry'))

    channel_title = get_rss_title(root)

    namespaces = {
        'atom': 'http://www.w3.org/2005/Atom',
        'media': 'http://search.yahoo.com/mrss/',
        'yt': 'http://www.youtube.com/xml/schemas/2015',
        'itunes': 'http://www.itunes.com/dtds/podcast-1.0.dtd'
    }

    articles = []
    for item in items:
        article = {}
        article['author'] = channel_title

        title_el = item.find('{*}title')
        article['title'] = title_el.text if title_el is not None else ''

        description_el = item.find('{*}description')
        article['description'] = description_el.text if description_el is not None else ''
        # Clean HTML tags from description text
        article['description'] = extract_text_HTML(article['description']) if article['description'] is not None else ''
        article['description'] = article['description'].replace('\n', ' ') if article['description'] is not None else ''
        
        if not article['title']:
            article['title'] = article['description']

        if ('rss-bridge.org' in url) and ('instagram' in url.lower()):
            article['title'] = article['description']

        link_el = item.find('{*}link')
        if link_el is not None:
            article['link'] = link_el.attrib.get('href') if 'href' in link_el.attrib else (link_el.text or '')
        else:
            article['link'] = ''

        lower_case_title = article['title'].lower()
        lower_case_link = article['link'].lower()
        ignore_titles_contain = CONFIG.get("ignore_titles_contain", [])
        ignore_links_contain = CONFIG.get("ignore_links_contain", [])
        # Check configuration rules to determine if the article should be filtered out
        should_ignore = (
            any(ignore_str.lower() in lower_case_title for ignore_str in ignore_titles_contain) or
            any(ignore_str.lower() in lower_case_link for ignore_str in ignore_links_contain)
        )
        if should_ignore:
            log(f"Ignoring article {article['title']}: {article['link']}")
            continue

        article['published'] = None

        if "youtube.com" in article['link']:
            pub_date_el = item.find('{*}published')
            article['published'] = pub_date_el.text if pub_date_el is not None else None

        if article['published'] is None:
            pub_date_el = next((item.find(f'{{*}}{tag}') for tag in ['pubDate', 'published', 'updated', 'date']), None)
            article['published'] = pub_date_el.text if pub_date_el is not None else None

        if article['published'] is None:
            pub_date_text = None
            # Iterate over elements to locate publishing date tag flexibly
            for element in item.iter():
                tag_name = element.tag.split('}')[-1] if '}' in element.tag else element.tag
                if tag_name in ['pubDate', 'published', 'updated', 'date', 'created']:
                    if element.text:
                        pub_date_text = element.text
                        break
            
            if not pub_date_text:
                dc_date = item.find('{http://purl.org/dc/elements/1.1/}date')
                if dc_date is not None:
                    pub_date_text = dc_date.text

            article['published'] = pub_date_text if pub_date_text else None

        article['image'] = None
        img_url = ''
        
        # Extract media thumbnails from standard namespaces (YouTube, MediaRSS, iTunes)
        media_group = item.find('media:group', namespaces)
        if media_group is not None:
            thumbnail = media_group.find('media:thumbnail', namespaces)
            if thumbnail is not None:
                img_url = thumbnail.attrib.get('url')

        if not img_url:
            media_thumb = item.find('media:thumbnail', namespaces)
            if media_thumb is not None:
                img_url = media_thumb.attrib.get('url')

        if not img_url:
            media_content = item.find('media:content', namespaces)
            if media_content is not None:
                img_url = media_content.attrib.get('url')

        if not img_url:
            desc_el = item.find('{*}description')
            if desc_el is None:
                desc_el = item.find('{*}content')
            if desc_el is not None and desc_el.text:
                img_url = extract_image_from_html(desc_el.text)

        if not img_url:
            itunes_img = item.find('itunes:image', namespaces)
            if itunes_img is not None:
                img_url = itunes_img.attrib.get('href')
        
        article['image'] = img_url
        articles.append(article)
        
    return url, channel_title, articles

def rss_articles_to_markdown(latestArticles, articles_map, url_to_feed, topic, filename: str):
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(f'# {topic}\n')
        f.write(f'---\n## ⏰ Last 24h\n')
        for article in latestArticles:
            is_24h = is_last_24h(article)
            if is_24h:
                writeArticle(article, f)

        f.write(f'---\n## ⏰ Last Days \n')

        for article in latestArticles[:10]:
            is_week = is_last_week(article) and not is_last_24h(article)
            if is_week:
                writeArticle(article, f)
                
        f.write(f'<details>\n')
        f.write(f'<summary>more...</summary>\n')
        for article in latestArticles[10:]:
            is_week = is_last_week(article) and not is_last_24h(article)
            if is_week:
                writeArticle(article, f)
        f.write(f'</details>\n')

        # Sort individual feed items alphabetically by their feed title
        sorted_items = sorted(
            articles_map.items(), 
            key=lambda item: url_to_feed[item[0]].lower()
        )

        for url, feed_arts in sorted_items:
            if feed_arts:
                f.write(f'---\n#### {url_to_feed[url]}\n')
                f.write(f'<details>\n')
                f.write(f'<summary>more...</summary>\n')
                f.write(f'\n<a href="{url}">RSS link</a>\n')
                for article in feed_arts[:10]:
                    writeArticle(article, f)
                f.write(f'</details>\n')
            else:
                f.write(f'---\n#### (!) RSS Error\n')
                f.write(f'\nError: Couldn\'t retrieve RSS data from [{url}]({url})\n\n')

def is_last_week(article):
    date = parse_iso_date(article.get('published', '-date unknown-'))
    now = datetime.now(timezone.utc)
    # Check if article publication date falls within the past week
    result = now - timedelta(weeks=1) <= date <= now
    return result

def is_last_24h(article):
    date = parse_iso_date(article.get('published', '-date unknown-'))
    now = datetime.now(timezone.utc)
    # Check if article publication date falls within the last 24 hours
    result = now - timedelta(hours=24) <= date <= now
    return result

def writeArticle(article, f):
    img = article.get('image')
    title = article.get('title', 'No Title')
    link = article.get('link', '#')
    author = article.get('author', '')
    date = parse_iso_date(article.get('published', '-date unknown-'))
    date_str = date.strftime('%A %d/%m/%y %H:%M')

    img = img if img else ""

    # Truncate overly long article titles to standard length
    if len(title) > 200:
        title = title[:200] + "..."
    
    # Format and write the article metadata into Markdown syntax
    f.write(f"\n> ![]({img}) [ {title} ]({link}) [{author} | {date_str}]()\n")

# ==============================================================================
# TELEGRAM
# ==============================================================================

def print_telegram_markdown_per_category(categories_data, telegram_output_path, limit=10):

    today = datetime.now().strftime('%A %d/%m/%y %H:%M')
    telegram_message_counter = 0
    header_lines = [f"\n############################\n\nLATEST NEWS: {today}\n\n############################\n",]
    write_telegram_message(header_lines, os.path.join(telegram_output_path, f"telegram_msg_{telegram_message_counter}"))
    telegram_message_counter += 1

    for category_name, articles in categories_data.items():

        lines = []
        lines.append(f"*LATEST NEWS: {category_name.upper()}*\n")

        article_counter = 0
        for article in articles:
            title = article.get('title', 'No Title')
            link = article.get('link', '#')
            author = article.get('author', '')
            published_date = parse_iso_date(article.get('published', '-date unknown-'))
            date_str = published_date.strftime('%d/%m/%y %H:%M')

            if is_last_24h(article):
                log(f"Category [{category_name}] Article: {title} {date_str}")

                if len(title) > 150:
                    title = title[:150] + "..."

                line = f"- [{title}]({link})\n  {author} | {date_str}\n"
                lines.append(line)
                article_counter += 1

            if article_counter == limit:
                break
        
        if article_counter > 0:
            # Safe naming for category message files
            file_path = os.path.join(telegram_output_path, f"telegram_msg_{telegram_message_counter}")
            write_telegram_message(lines, file_path)
            telegram_message_counter += 1

def write_telegram_message(lines, filename: str):
    telegram_msg = "\n".join(lines)
    log(f"Print Telegram message {filename}: {telegram_msg}")
    # Save the formatted message chunk to a text file for Telegram delivery
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(telegram_msg)
    # Add minor pause between telegram file writes
    sleep_random_range(100, 200)

# ==============================================================================
# MAIN
# ==============================================================================

if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Usage: python script.py <input.json> <output_dir> <config>")
        sys.exit(1)

    # Initialize environment with cache path specification
    setup_environment("./rss_cache.json")
    
    urlsJSONPath = sys.argv[1]
    outputPath = sys.argv[2]
    config_path = sys.argv[3]

    # Load configuration settings from JSON file
    with open(config_path, 'r', encoding='utf-8') as f:
        CONFIG = json.load(f)
        log(f"Config loaded: {CONFIG}")

    try:
        with open(urlsJSONPath, 'r', encoding='utf-8') as file:
            urls_data = json.load(file)
        
        rss_resolved_json = {}
        # Resolve URLs to feed links
        replace_urls_with_rss_feeds(urls_data, rss_resolved_json)
        
        # Cleanup old output directory if it exists
        final_output_path = os.path.join(outputPath, 'feeds')
        if os.path.exists(final_output_path):
            shutil.rmtree(final_output_path)
            
        categories_data = {}
        url_to_feed = {}
        
        # Creates files and collects dictionary mapping category name -> latest articles
        generate_rss_folders(rss_resolved_json, final_output_path, [], categories_data, url_to_feed)

        # Write RSS in Telegram format, so it can be sent to Telegram bot later (optional)
        telegram_output_path = Path(os.path.join(outputPath, 'telegram'))
        telegram_output_path.mkdir(parents=True, exist_ok=True)
        log(f"Writing Category-Specific Telegram Markdown files to {telegram_output_path}.")
        print_telegram_markdown_per_category(categories_data, telegram_output_path, limit=10)
        
        # Persist cache state before exit
        save_cache()
        log("Task Completed Successfully.")
    except Exception as e:
        log(f"Critical Error: {e}", error=True)