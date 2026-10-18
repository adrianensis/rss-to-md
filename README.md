# RSS to Markdown Converter (`rss-to-md.py`)

A Python script that automatically turns RSS feeds, podcast channels, and even regular website URLs or YouTube channels/playlists into clean, organized Markdown files.

It is designed to run automatically to keep a personal news dashboard, reading list, or Telegram news feed up to date.

---

## ✨ What it does

* **Smart URL Resolution:** You don't need direct RSS links. You can give it regular website URLs, YouTube channel/playlist links, or iVoox pages, and the script will automatically find the correct RSS feeds for you.
* **Fast Multi-threading:** Uses concurrent workers (`ThreadPoolExecutor`) to download and parse multiple feeds at the same time.
* **Smart Caching:** Caches discovered feed URLs and downloaded RSS content locally to avoid spamming websites and speed up future runs.
* **Automatic Categorization:** Reads a hierarchical JSON structure of your favorite topics and builds matching folders and Markdown files (`index.md`, category files, etc.).
* **Time-based Filtering:** Automatically organizes articles into **Last 24h**, **Last Days**, and older items hidden inside collapsible (`<details>`) sections.
* **Telegram Ready:** Can also generate formatted text snippets ready to be sent straight to a Telegram bot.

---

## 🚀 How to Use It

### 1. Prerequisites

Make sure you have Python installed along with the required libraries:

```bash
pip install requests lxml beautifulsoup4 yt-dlp python-dateutil fake-useragent

```

### 2. Prepare your Configuration Files

You need two JSON files to run the script:

* **`urls.json`**: A nested structure of your categories and websites or RSS feeds.
* **`config.json`**: Settings file (e.g., words or links to ignore).

### 3. Run the Script

Run the script from your terminal by passing the input JSON, output directory, and config file:

```bash
python rss-to-md.py urls.json ./output config.json

```

---

## 📁 Input File Examples

### `urls.json` Example

```json
{
  "Tech": {
    "urls": [
      "https://news.ycombinator.com",
      "https://www.youtube.com/@TheLinuxGamer"
    ]
  },
  "News": {
    "rss": [
      "https://feeds.bbci.co.uk/news/rss.xml"
    ]
  }
}

```

### `config.json` Example

```json
{
  "ignore_titles_contain": [
    "Sponsored",
    "Advertisement"
  ],
  "ignore_links_contain": [
    "ad-tracker"
  ]
}

```

---

## 🛠️ How it Works Under the Hood

1. **Setup & Cache:** Loads cache (`rss_cache.json`) to remember previously discovered feed links.
2. **Feed Discovery:** Crawls standard HTML headers (`<link rel="alternate" type="application/rss+xml">`) or uses `yt-dlp` for YouTube channels to find feeds.
3. **Download & Parse:** Fetches feed XML contents, handles standard namespaces (Atom, MediaRSS, iTunes), and extracts titles, dates, images, and descriptions.
4. **Markdown Generation:** Sorts articles by date and builds structured Markdown pages separated by timeframe (Last 24h vs. older items).
