#!/usr/bin/env python3

import copy
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
import webbrowser
import tempfile


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

CONFIG_PATH = os.path.expanduser(os.path.join("~", ".config", "versli", "config.json"))

def load_user_config():
    """User-level defaults, e.g. {"version": "SLT"}."""
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as cf:
            config = json.load(cf)
        debug_log(f"User config loaded from {CONFIG_PATH}.")
        return config
    except FileNotFoundError:
        debug_log(f"No user config at {CONFIG_PATH}.")
        return {}
    except Exception as e:
        click.echo(f"Warning: could not read {CONFIG_PATH}: {e}", err=True)
        return {}

def resolve_version_id(version: str):
    try:
        versions_path = os.path.join(BASE_DIR, "db", "versions.json")
        with open(versions_path, "r", encoding="utf-8") as vf:
            versions_dict = json.load(vf)
        debug_log("Versions database loaded.")
    except Exception as e:
        click.echo(f"Error loading versions database: {e}", err=True)
        versions_dict = {}

    if version.isdigit():
        return int(version)
    for key, val in versions_dict.items():
        if key.upper() == version.upper():
            return val
    return versions_dict.get("NIV", 111)

def load_versification():
    try:
        with open(os.path.join(BASE_DIR, "db", "versification.json"), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        debug_log(f"No versification database: {e}")
        return {}

def shift_verse(book: str, chapter: str, verse: str, version: str):
    """bible.com references the verse of the day in english numbering. translations that follow the hebrew
    numbering of the psalms (german, french) count the superscription as verse 1 (or 1-2), so e.g. english
    Psalm 55:22 is Psalm 55,23 in Schlachter. Returns the shifted verse (ranges like "3-5" are shifted too)."""
    vs = load_versification()
    if not vs or not verse:
        return verse
    if resolve_version_id(version) not in {resolve_version_id(v) for v in vs.get("hebrew_psalm_numbering", [])}:
        return verse
    entry, _ = resolve_book(book)
    if not entry or entry["aliases"][0].upper() != "PSA":
        return verse
    offset = vs.get("psalm_offsets", {}).get(str(chapter), 0)
    if not offset:
        return verse
    shifted = "-".join(str(int(v) + offset) for v in str(verse).split("-"))
    debug_log(f"Psalm {chapter}: hebrew numbering, verse {verse} -> {shifted} for version {version}")
    return shifted

def normalize_book_key(name: str):
    return re.sub(r"[.\s]", "", name.lower())

def load_book_index():
    """Returns (book_entries, de_to_en_mapping, error_message)."""
    try:
        books_path = os.path.join(BASE_DIR, "db", "books.json")
        with open(books_path, "r", encoding="utf-8") as bf:
            book_data = json.load(bf)
        debug_log("Books database loaded.")
    except Exception as e:
        return None, None, f"Error loading books database: {e}"

    try:
        mappings_path = os.path.join(BASE_DIR, "db", "book_mappings.json")
        with open(mappings_path, "r", encoding="utf-8") as mf:
            mappings = json.load(mf)
        debug_log("Book mappings loaded.")
    except Exception as e:
        return None, None, f"Error loading book mappings: {e}"

    return book_data.get("books", []), mappings.get("de_to_en", {}), None

def resolve_book(book: str):
    """Resolve a possibly abbreviated book name to its books.json entry.

    Tries exact matches on English names, aliases and German names first,
    then unique prefixes ("jes" -> "jesaja" -> Isaiah).
    Returns (book_entry, None) or (None, error_message)."""
    entries, de_to_en, load_error = load_book_index()
    if load_error:
        return None, load_error

    indexed = []
    for entry in entries:
        names = {entry.get("book", "")} | set(entry.get("aliases", []))
        names |= {de for de, en in de_to_en.items() if en.lower() == entry.get("book", "").lower()}
        indexed.append((entry, {normalize_book_key(n) for n in names if n}))

    key = normalize_book_key(book)
    if not key:
        return None, f"Could not find book '{book}'."
    for entry, names in indexed:
        if key in names:
            debug_log(f"Book '{book}' matched exactly: {entry['book']}")
            return entry, None
    matches = [entry for entry, names in indexed if any(n.startswith(key) for n in names)]
    if len(matches) == 1:
        debug_log(f"Book '{book}' matched by prefix: {matches[0]['book']}")
        return matches[0], None
    if not matches:
        return None, f"Could not find book '{book}' by name, alias or prefix."
    candidates = ", ".join(entry["book"] for entry in matches)
    return None, f"Book '{book}' is ambiguous: {candidates}."

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

def parse_chapter_markup(soup, book_entry, chapter):
    """Parse bible.com's current chapter pages (no __NEXT_DATA__ anymore).

    Verse fragments are <span data-usfm="ISA.55.1"> elements whose CSS-module
    class names are hashed, so children are matched by class suffix
    (…__label = verse number, …__note = footnotes, …__heading = section title)."""
    def has_class_suffix(el, suffix):
        return any(c.endswith(suffix) for c in (el.get("class") or []))

    # page chrome (chapter picker etc.) reuses the same class suffixes,
    # so only look inside the bible text container
    root = soup.find("div", class_="version") or soup
    # cross-reference links inside footnotes carry data-usfm too (e.g. JHN.4.10),
    # so only accept real verse spans of the requested chapter
    usfm_prefix = f"{book_entry['aliases'][0]}.{chapter}.".upper()
    fragments = {}
    for span in root.find_all("span", attrs={"data-usfm": True}):
        if not has_class_suffix(span, "__verse"):
            continue
        if not span["data-usfm"].upper().startswith(usfm_prefix):
            continue
        m = re.match(r"^[^.]+\.[^.]+\.(\d+)", span["data-usfm"])
        if not m:
            continue
        num = int(m.group(1))
        piece = copy.copy(span)
        for junk in piece.find_all(lambda el: has_class_suffix(el, "__label") or has_class_suffix(el, "__note")):
            junk.decompose()
        text = piece.get_text(" ", strip=True)
        if text:
            fragments.setdefault(num, []).append(text)
    if not fragments:
        return None

    verses_dict = {num: " ".join(parts) for num, parts in sorted(fragments.items())}
    # ignore the chapter label ("Kapitel 55"), whose heading sits in a __cl container
    heading = root.find(lambda el: el.name == "span" and has_class_suffix(el, "__heading")
                        and not (el.parent and has_class_suffix(el.parent, "__cl")))
    return {
        "title": heading.get_text(strip=True) if heading else "",
        "verses": verses_dict,
        "citation": f"{book_entry['book']} {chapter}"
    }

def get_verse(book: str, chapter: str, verses: str, version: str):
    version_id = resolve_version_id(version)
    debug_log(f"Using Bible version '{version}' resolved to id: {version_id}")

    book_entry, book_error = resolve_book(book)
    if not book_entry:
        debug_log(f"Book not found for '{book}'.")
        return {
            "code": 400,
            "message": book_error
        }

    baseURL = "https://www.bible.com/bible"
    if verses == "-1":
        url = f"{baseURL}/{version_id}/{book_entry['aliases'][0]}.{chapter}"
    else:
        url = f"{baseURL}/{version_id}/{book_entry['aliases'][0]}.{chapter}.{verses}"
    debug_log(f"Fetching verse from: {url}")
    
    if url=="https://www.bible.com/bible/73/PSA.19.1":
        url = "https://www.bible.com/bible/73/PSA.19.2" #dirty hack because of a bug in the bible.com site

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
    if verses == "-1":
        chapter_result = parse_chapter_markup(soup, book_entry, chapter)
        if chapter_result:
            return chapter_result
    verses_elements = soup.select(".text-17")
    if verses_elements:
        verse_text = verses_elements[0].get_text(" ", strip=True)
        citation = f"{book_entry['book']} {chapter}:{verses}"
        return {
            "citation": citation,
            "passage": verse_text
        }
    return None

def get_verse_url(book: str, chapter: str, verses: str, version: str):
    version_id = resolve_version_id(version)
    book_entry, book_error = resolve_book(book)
    if not book_entry:
        click.echo(book_error, err=True)
        return None
    baseURL = "https://www.bible.com/bible"
    if verses == "-1":
        return f"{baseURL}/{version_id}/{book_entry['aliases'][0]}.{chapter}"
    return f"{baseURL}/{version_id}/{book_entry['aliases'][0]}.{chapter}.{verses}"

def format_markdown(result):
    """Chapters become a heading plus bold verse numbers, single passages a blockquote."""
    if result.get("verses"):
        lines = [f"# {result.get('citation', '').strip()}", ""]
        if result.get("title"):
            lines += [f"*{result['title'].strip()}*", ""]
        lines.append("  \n".join(f"**{num}** {txt}" for num, txt in sorted(result["verses"].items())))
        return "\n".join(lines)
    passage = result.get("passage", "").strip()
    quoted = "\n".join(f"> {line}".rstrip() for line in passage.splitlines())
    return f"{quoted}\n>\n> — {result.get('citation', '').strip()}"

CHAPTER_TOKEN_RE = re.compile(r"^(\d+)(?:,(\d+(?:-\d+)?))?$")
GLUED_TOKEN_RE = re.compile(r"^(.*?[^\d,.\s])\.?\s*(\d+)(?:,(\d+(?:-\d+)?))?$")

def parse_positional(positional):
    """Turn positional args into (book, chapter, verse); verse "-1" = whole chapter.

    Accepted forms:
      jes55        -> Jesaja, chapter 55
      jes55,3      -> Jesaja 55:3        (also jes55,3-7)
      jes 55       -> Jesaja, chapter 55
      jes 55,3     jes 55 3     jesaja 55 3
      1. mose 3    1kor13,4     2 sam 7 12
    Returns (book, chapter, verse, error_message)."""
    tokens = [t.strip() for t in positional if t.strip()]
    if not tokens:
        return None, None, None, "No reference given."
    # the first token can never be the chapter (a book is required, and books
    # like "1. Mose" start with a digit), so scan for a chapter token from the second on
    for i in range(1, len(tokens)):
        m = CHAPTER_TOKEN_RE.match(tokens[i])
        if not m:
            continue
        book = " ".join(tokens[:i])
        chapter, verse = m.group(1), m.group(2)
        rest = tokens[i + 1:]
        if rest:
            if verse is None and len(rest) == 1 and re.fullmatch(r"\d+(?:-\d+)?", rest[0]):
                verse = rest[0]
            else:
                return None, None, None, f"Could not make sense of trailing arguments: {' '.join(rest)}"
        return book, chapter, verse or "-1", None
    # no standalone chapter token: split a glued "<book><chapter>[,<verse>]" off the last token
    m = GLUED_TOKEN_RE.match(tokens[-1])
    if m and re.search(r"[^\W\d_]", m.group(1)):
        book = " ".join(tokens[:-1] + [m.group(1)])
        return book, m.group(2), m.group(3) or "-1", None
    return None, None, None, (
        f"Could not parse reference '{' '.join(tokens)}'. "
        "Try e.g. 'jes55', 'jes 55', 'jes55,3' or 'jesaja 55 3'."
    )

def _default_version():
    user_config = load_user_config()
    return (user_config.get("version") or user_config.get("translation")
            or load_defaults().get(get_default_language().lower(), "NIV"))

def _verse_numbers(book_entry, chapter):
    """Verse numbers of a chapter, fetched via the (cached) chapter page."""
    import socket
    socket.setdefaulttimeout(4)
    try:
        result = get_verse(book_entry["book"], chapter, "-1", _default_version())
    except Exception:
        return []
    if not result or not result.get("verses"):
        return []
    return sorted(result["verses"])

def complete_reference(ctx, param, incomplete):
    """Tab completion for the positional reference: book, then chapter, then verse."""
    import contextlib, io
    from click.shell_completion import CompletionItem
    with contextlib.redirect_stderr(io.StringIO()):
        return _complete_reference(ctx, incomplete, CompletionItem)

def _complete_reference(ctx, incomplete, CompletionItem):
    prior = [t.strip() for t in (ctx.params.get("positional") or ()) if t.strip()]
    entries, de_to_en, load_error = load_book_index()
    if load_error:
        return []

    # already past the book? locate a chapter among the prior words
    book_entry = chapter = None
    verse_done = False
    for i in range(1, len(prior)):
        m = CHAPTER_TOKEN_RE.match(prior[i])
        if m:
            book_entry, _ = resolve_book(" ".join(prior[:i]))
            chapter, verse_done = m.group(1), m.group(2) is not None
            verse_done = verse_done or len(prior) > i + 1
            break
    else:
        if prior:
            glued = GLUED_TOKEN_RE.match(prior[-1])
            if glued and re.search(r"[^\W\d_]", glued.group(1)):
                book_entry, _ = resolve_book(" ".join(prior[:-1] + [glued.group(1)]))
                chapter, verse_done = glued.group(2), glued.group(3) is not None

    if book_entry and chapter:
        if verse_done:
            return []
        return [CompletionItem(str(n)) for n in _verse_numbers(book_entry, chapter)
                if str(n).startswith(incomplete)]

    if prior:
        book_entry, _ = resolve_book(" ".join(prior))
        if book_entry:  # book complete -> chapter numbers
            return [CompletionItem(str(n)) for n in range(1, int(book_entry.get("chapters", 0)) + 1)
                    if str(n).startswith(incomplete)]

    # book stage: German names first, then English; multi-word books complete token-wise
    items, seen = [], set()
    for entry in entries:
        en = entry.get("book", "")
        names = [de for de, e in de_to_en.items() if e.lower() == en.lower()] + [en]
        for name in names:
            name_tokens = name.split()
            if len(name_tokens) <= len(prior):
                continue
            if [t.lower() for t in name_tokens[:len(prior)]] != [t.lower() for t in prior]:
                continue
            candidate = " ".join(name_tokens[len(prior):])
            if not candidate.lower().startswith(incomplete.lower()) or candidate.lower() in seen:
                continue
            seen.add(candidate.lower())
            items.append(CompletionItem(candidate, help=en if candidate.lower() != en.lower() else None))

    # glued "<book><chapter>" being typed (e.g. "jes5") -> complete glued chapters
    if not prior:
        glued = GLUED_TOKEN_RE.match(incomplete)
        if glued and re.search(r"[^\W\d_]", glued.group(1)) and glued.group(3) is None:
            entry, _ = resolve_book(glued.group(1))
            if entry:
                items += [CompletionItem(f"{glued.group(1)}{n}")
                          for n in range(1, int(entry.get("chapters", 0)) + 1)
                          if str(n).startswith(glued.group(2))]
    return items

@click.command()
@click.argument("positional", nargs=-1, shell_complete=complete_reference)
@click.option("--book", help="Book name")
@click.option("--chapter", help="Chapter number")
@click.option("--verse", help="Verse number (single verse)")
@click.option("--from", "from_verse", type=int, help="Start verse for range")
@click.option("--to", "to_verse", type=int, help="End verse for range")
@click.option("--version", help="Bible version (e.g., NIV, KJV, bibel.heute)")
@click.option("--language", default=get_default_language(), help="Language code (default: system locale)")
@click.option("--json", "json_output", is_flag=True, default=False, help="Output JSON")
@click.option("--markdown", "markdown_output", is_flag=True, default=False, help="Output Markdown")
@click.option("--pretty", is_flag=True, default=True, help="Pretty output (default)")
@click.option("-v", "--verbose", is_flag=True, default=False, help="Verbose debug output")
@click.option("--clear-cache", is_flag=True, default=False, help="Clear the request cache before running")
@click.option("--web", is_flag=True, default=False, help="Show verse in the browser")
def main(positional, book, chapter, verse, from_verse, to_verse, version, language, json_output, markdown_output, pretty, verbose, clear_cache, web):
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
        user_config = load_user_config()
        version = user_config.get("version") or user_config.get("translation")
        if version:
            debug_log(f"No version specified, using user config default: {version}")
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
                ver_num = shift_verse(book_name, chap, m.group(3), version)
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
            book_name, chapter, verse, parse_error = parse_positional(positional)
            if parse_error:
                click.echo(parse_error, err=True)
                raise SystemExit(1)
        else:
            if not book or not chapter or (not verse and (from_verse is None or to_verse is None)):
                click.echo("Please provide --book, --chapter, and --verse or both --from and --to.", err=True)
                return
            book_name = book
            if not verse and from_verse is not None and to_verse is not None:
                verse = "-1"
        debug_log(f"Fetching verse for {book_name} {chapter}:{verse} in version {version}")
        result = get_verse(book_name, chapter, verse, version)
        if not result:
            click.echo("No data received.", err=True)
            raise SystemExit(1)
        if result.get("code"):
            click.echo(result.get("message", "Unknown error."), err=True)
            raise SystemExit(1)
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
    elif markdown_output:
        click.echo(format_markdown(result))
    elif web:
        # Open verse on bible.com in browser
        if not positional and not book:
            # VOTD mode: open verse-of-the-day page for language
            url = f"https://www.bible.com/{language}/verse-of-the-day"
        else:
            # Verse mode: construct URL and open
            if not book_name:
                click.echo("Book name is required for --web option.", err=True)
                return
            if not chapter:
                click.echo("Chapter number is required for --web option.", err=True)
                return
            verse_param = verse if verse else "-1"
            url = get_verse_url(book_name, chapter, verse_param, version)
            if not url:
                click.echo("Could not construct URL for the verse.", err=True)
                return
        webbrowser.open(url)
    else:
        console = Console()
        if "verses" in result:
            text = f"Citation: {result.get('citation','')}\n\n" + "\n".join(f"{num}: {txt}" for num, txt in sorted(result["verses"].items()))
        else:
            text = f"{result.get('passage','')}\n- {result.get('citation','')}"
        panel = Panel(text, title=panel_title, expand=False)
        console.print(panel)

if __name__ == "__main__":
    main(prog_name="verse")
