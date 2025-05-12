#!/usr/bin/env python3

import os
import json
import re
import requests
import requests_cache
from datetime import datetime, timedelta, time
from bs4 import BeautifulSoup
import click
from rich.console import Console
from rich.panel import Panel
import locale


# Configure requests_cache to expire at midnight
def get_seconds_until_midnight():
    now = datetime.now()
    tomorrow = now.date() + timedelta(days=1)
    midnight = datetime.combine(tomorrow, time())
    return (midnight - now).total_seconds()

# Initialize the cache with expiration at midnight
requests_cache.install_cache(
    cache_name=os.path.join(os.path.dirname(os.path.abspath(__file__)), '.verse_cache'),
    backend='sqlite',
    expire_after=get_seconds_until_midnight()
)

def is_response_from_cache(response):
    """Check if a response came from the cache."""
    return hasattr(response, 'from_cache') and response.from_cache


DEBUG = False
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def debug_log(msg: str):
    if DEBUG:
        click.echo(f"DEBUG: {msg}")

def get_default_language():
    loc = locale.getlocale()[0]
    if loc:
        lang = loc.split("_")[0].lower()
        debug_log(f"System locale detected, using language: {lang}")
        return lang
    debug_log("No locale found, defaulting to 'en'")
    return "en"

def load_defaults():
    try:
        defaults_path = os.path.join(BASE_DIR, "db", "defaults.json")
        with open(defaults_path, "r", encoding="utf-8") as df:
            defaults = json.load(df)
        debug_log("Defaults database loaded.")
        return defaults
    except Exception as e:
        debug_log(f"Error loading defaults database: {e}")
        return {}

def load_translations():
    try:
        translations_path = os.path.join(BASE_DIR, "db", "translations.json")
        with open(translations_path, "r", encoding="utf-8") as tf:
            translations = json.load(tf)
        debug_log("Translations database loaded.")
        return translations
    except Exception as e:
        debug_log(f"Error loading translations database: {e}")
        return {}

def get_votd(lang: str):
    url = f"https://www.bible.com/{lang.strip()}/verse-of-the-day"
    debug_log(f"Fetching VOTD from: {url}")
    try:
        response = requests.get(url)
        if is_response_from_cache(response):
            debug_log("VOTD retrieved from cache")
        else:
            debug_log("VOTD fetched from network (will be cached)")
        response.raise_for_status()
    except requests.RequestException as e:
        click.echo(f"Error for language '{lang}': {e}", err=True)
        return None

    soup = BeautifulSoup(response.text, "html.parser")
    next_data_tag = soup.find("script", id="__NEXT_DATA__")
    if next_data_tag and next_data_tag.string:
        try:
            json_data = json.loads(next_data_tag.string)
            verses = json_data.get("props", {}).get("pageProps", {}).get("verses", [])
            if verses:
                verse_text = verses[0].get("content", "").replace("\n", " ")
                reference = verses[0].get("reference", {}).get("human", "")
                version = json_data.get("props", {}).get("pageProps", {}).get("versionData", {}).get("abbreviation", "")
                images = []
                for a in soup.select("a.block"):
                    img = a.find("img")
                    if img and img.get("src"):
                        images.append("https://www.bible.com" + img.get("src"))
                debug_log(f"VOTD parsed: {reference} ({version})")
                return {
                    "citation": reference,
                    "passage": verse_text,
                    "images": images,
                    "version": version
                }
        except Exception as e:
            click.echo(f"Error parsing Nextjs data for language '{lang}': {e}", err=True)
    citations = soup.select("p.text-gray-25")
    verses_tags = soup.select("a.text-text-light.w-full.no-underline")
    images = []
    for a in soup.select("a.block"):
        img = a.find("img")
        if img and img.get("src"):
            images.append("https://www.bible.com" + img.get("src"))
    if citations and verses_tags:
        citation_text = citations[0].get_text().strip()
        version = citation_text[-4:].replace("(", "").replace(")", "")
        citation_text = citation_text[:-6].strip()
        verse_text = verses_tags[0].get_text().replace("\n", " ").strip()
        debug_log(f"VOTD fallback parsed: {citation_text} ({version})")
        return {
            "citation": citation_text,
            "passage": verse_text,
            "images": images,
            "version": version
        }
    return None

def get_verse(book: str, chapter: str, verses: str, version: str):
    try:
        versions_path = os.path.join(BASE_DIR, "db", "versions.json")
        with open(versions_path, "r", encoding="utf-8") as vf:
            versions_dict = json.load(vf)
        debug_log("Versions database loaded.")
    except Exception as e:
        click.echo(f"Error loading versions database: {e}", err=True)
        versions_dict = {}

    if version.isdigit():
        version_id = int(version)
    else:
        found = None
        for key, val in versions_dict.items():
            if key.upper() == version.upper():
                found = val
                break
        version_id = found if found is not None else versions_dict.get("NIV", 111)
    debug_log(f"Using Bible version '{version}' resolved to id: {version_id}")

    try:
        books_path = os.path.join(BASE_DIR, "db", "books.json")
        with open(books_path, "r", encoding="utf-8") as bf:
            book_data = json.load(bf)
        debug_log("Books database loaded.")
    except Exception as e:
        click.echo(f"Error loading books database: {e}", err=True)
        return None

    try:
        mappings_path = os.path.join(BASE_DIR, "db", "book_mappings.json")
        with open(mappings_path, "r", encoding="utf-8") as mf:
            mappings = json.load(mf)
        debug_log("Book mappings loaded.")
    except Exception as e:
        click.echo(f"Error loading book mappings: {e}", err=True)
        return None

    orig_book = book
    if book.lower() in mappings.get("de_to_en", {}):
        debug_log(f"Mapping German book '{book}' to English '{mappings['de_to_en'][book.lower()]}'")
        book = mappings["de_to_en"][book.lower()]

    book_entry = None
    for entry in book_data.get("books", []):
        if entry.get("book", "").lower() == book.lower():
            book_entry = entry
            break
    if not book_entry:
        for entry in book_data.get("books", []):
            aliases = entry.get("aliases", [])
            if any(book.upper() == alias.upper() for alias in aliases):
                book_entry = entry
                break
    if not book_entry:
        debug_log(f"Book not found for '{orig_book}' (mapped to '{book}').")
        return {
            "code": 400,
            "message": f"Could not find book '{orig_book}' by name or alias."
        }

    baseURL = "https://www.bible.com/bible"
    if verses == "-1":
        url = f"{baseURL}/{version_id}/{book_entry['aliases'][0]}.{chapter}"
    else:
        url = f"{baseURL}/{version_id}/{book_entry['aliases'][0]}.{chapter}.{verses}"
    debug_log(f"Fetching verse from: {url}")

    try:
        response = requests.get(url)
        if is_response_from_cache(response):
            debug_log("Verse retrieved from cache")
        else:
            debug_log("Verse fetched from network (will be cached)")
        response.raise_for_status()
        html = response.text
    except requests.RequestException as e:
        click.echo(f"Error fetching verse: {e}", err=True)
        return None

    soup = BeautifulSoup(html, "html.parser")
    if soup.find("p", string=lambda t: t and "No Available Verses" in t):
        return {"code": 400, "message": "Verse not found"}

    next_data_tag = soup.find("script", id="__NEXT_DATA__")
    if next_data_tag and next_data_tag.string:
        try:
            json_data = json.loads(next_data_tag.string)
        except Exception as e:
            click.echo(f"Error parsing JSON data: {e}", err=True)
            return None

        if verses == "-1":
            chapter_info = json_data.get("props", {}).get("pageProps", {}).get("chapterInfo", {}).get("content", "")
            if chapter_info:
                chapter_soup = BeautifulSoup(chapter_info, "html.parser")
                full_chapter_html = str(chapter_soup)
                parts = re.split(r'<span class="label">[0-9]*<\/span>', full_chapter_html)
                if parts:
                    title_soup = BeautifulSoup(parts[0], "html.parser")
                    title_el = title_soup.find(class_="heading")
                    title_text = title_el.get_text(strip=True) if title_el else ""
                    verse_list = []
                    for i, part in enumerate(parts[1:], start=1):
                        part_soup = BeautifulSoup(part, "html.parser")
                        content_div = part_soup.find(class_="content")
                        verse_text = content_div.get_text(" ", strip=True) if content_div else part_soup.get_text(" ", strip=True)
                        verse_list.append((i, verse_text))
                    verses_dict = {num: text for num, text in verse_list}
                    citation = f"{book_entry['book']} {chapter}"
                    return {
                        "title": title_text,
                        "verses": verses_dict,
                        "citation": citation
                    }
        else:
            verses_arr = json_data.get("props", {}).get("pageProps", {}).get("verses", [])
            if verses_arr:
                verse_text = verses_arr[0].get("content", "")
                reference = verses_arr[0].get("reference", {}).get("human", "")
                return {
                    "citation": reference,
                    "passage": verse_text,
                }
    verses_elements = soup.select(".text-17")
    if verses_elements:
        verse_text = verses_elements[0].get_text(" ", strip=True)
        citation = f"{book_entry['book']} {chapter}:{verses}"
        return {
            "citation": citation,
            "passage": verse_text
        }
    return None

@click.command()
@click.argument("positional", nargs=-1)
@click.option("--book", help="Book name")
@click.option("--chapter", help="Chapter number")
@click.option("--verse", help="Verse number (single verse)")
@click.option("--from", "from_verse", type=int, help="Start verse for range")
@click.option("--to", "to_verse", type=int, help="End verse for range")
@click.option("--version", help="Bible version (e.g., NIV, KJV, bibel.heute)")
@click.option("--language", default=get_default_language(), help="Language code (default: system locale)")
@click.option("--json", "json_output", is_flag=True, default=False, help="Output JSON")
@click.option("--pretty", is_flag=True, default=True, help="Pretty output (default)")
@click.option("-v", "--verbose", is_flag=True, default=False, help="Verbose debug output")
@click.option("--clear-cache", is_flag=True, default=False, help="Clear the request cache before running")
def main(positional, book, chapter, verse, from_verse, to_verse, version, language, json_output, pretty, verbose, clear_cache):
    global DEBUG
    DEBUG = verbose
    debug_log("Starting script...")

    if clear_cache:
        debug_log("Clearing request cache...")
        requests_cache.clear()
        debug_log("Cache cleared.")

    defaults = load_defaults()
    translations = load_translations()
    if not version:
        version = defaults.get(language.lower(), "NIV")
        debug_log(f"No version specified, using default for '{language}': {version}")

    if not positional and not book:
        debug_log("Running in VOTD mode")
        result = get_votd(language)
        if not result:
            click.echo("No data received.")
            return
        if version:
            citation = result.get("citation", "")
            debug_log(f"Original citation: {citation}")
            m = re.match(r"^([\d\.\s]*[\w\s]+)\s+(\d+):(\d+)", citation)
            if m:
                book_name = m.group(1).strip()
                chap = m.group(2)
                ver_num = m.group(3)
                debug_log(f"Re-fetching verse for {book_name} {chap}:{ver_num} in version {version}")
                new_result = get_verse(book_name, chap, ver_num, version)
                if new_result and new_result.get("passage"):
                    result = new_result
                    result["citation"] = f"{result.get('citation','')} ({version.upper()})"
                    debug_log("Re-fetch succeeded.")
                else:
                    click.echo("Failed to re-fetch verse with specified version.", err=True)
                    return
            else:
                click.echo("Could not parse citation for version switch.", err=True)
                return
    else:
        debug_log("Running in verse mode")
        if positional:
            if len(positional) >= 2:
                book_name = positional[0]
                if "," in positional[1]:
                    parts = positional[1].split(",")
                    if len(parts) == 2:
                        chapter = parts[0].strip()
                        verse = parts[1].strip()
                    else:
                        click.echo("Invalid format for chapter,verse.", err=True)
                        return
                elif len(positional) >= 3:
                    chapter = positional[1]
                    verse = positional[2]
                else:
                    click.echo("Not enough positional arguments for verse mode.", err=True)
                    return
            else:
                click.echo("Not enough positional arguments for verse mode.", err=True)
                return
        else:
            if not book or not chapter or (not verse and (from_verse is None or to_verse is None)):
                click.echo("Please provide --book, --chapter, and --verse or both --from and --to.", err=True)
                return
            book_name = book
            if not verse and from_verse is not None and to_verse is not None:
                verse = "-1"
        debug_log(f"Fetching verse for {book_name} {chapter}:{verse} in version {version}")
        result = get_verse(book_name, chapter, verse, version)
        if verse == "-1" and from_verse is not None and to_verse is not None:
            if "verses" in result:
                verses_dict = result["verses"]
                filtered = {num: txt for num, txt in verses_dict.items() if from_verse <= num <= to_verse}
                result["verses"] = filtered
                combined = "\n".join(f"{num}: {txt}" for num, txt in sorted(filtered.items()))
                result["passage"] = combined
            else:
                click.echo("Full chapter verses not available.", err=True)
                return
        result["citation"] = f"{result.get('citation','')} ({version.upper()})"

    panel_title = translations.get(language.lower(), "Verse")
    if json_output:
        click.echo(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        console = Console()
        if "verses" in result:
            text = f"Citation: {result.get('citation','')}\n\n" + "\n".join(f"{num}: {txt}" for num, txt in sorted(result["verses"].items()))
        else:
            text = f"{result.get('passage','')}\n- {result.get('citation','')}"
        panel = Panel(text, title=panel_title, expand=False)
        console.print(panel)

if __name__ == "__main__":
    main()
