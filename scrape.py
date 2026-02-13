import requests
from bs4 import BeautifulSoup
import pdfplumber
import re
from ics import Calendar, Event
from datetime import datetime, timedelta
import io
from urllib.parse import urljoin
import sys

# Constants for scraping
PAGE_URL = "https://winshipcancer.emory.edu/education-and-training/continuing-education/elkin-lecture-series.php"
PDF_LINK_TEXT_REGEX = re.compile(r'Elkin Lecture Series Flyer \(PDF\)', re.IGNORECASE)

def get_pdf_url(page_url):
    try:
        response = requests.get(page_url)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')

        # Find the link with text "Elkin Lecture Series Flyer (PDF)"
        link = soup.find('a', string=PDF_LINK_TEXT_REGEX)

        if link and link.get('href'):
            return urljoin(page_url, link['href'])
        else:
            print("PDF link not found on the page.")
            return None
    except Exception as e:
        print(f"Error fetching page: {e}")
        return None

def download_pdf(pdf_url):
    try:
        response = requests.get(pdf_url)
        response.raise_for_status()
        return io.BytesIO(response.content)
    except Exception as e:
        print(f"Error downloading PDF: {e}")
        return None

def extract_text_from_pdf(pdf_file):
    try:
        with pdfplumber.open(pdf_file) as pdf:
            if len(pdf.pages) > 0:
                # Use simple text extraction which preserves line order
                return pdf.pages[0].extract_text()
            else:
                return ""
    except Exception as e:
        print(f"Error parsing PDF: {e}")
        return ""

def parse_date(date_str, ref_date=None):
    """
    Parses a date string (e.g. 'Feb 12') and returns a datetime date object.
    It determines the year by finding which year (near the current year) makes the date a Friday.
    """
    if ref_date is None:
        ref_date = datetime.now()

    # Normalize date string
    try:
        dt = datetime.strptime(date_str, "%B %d")
    except ValueError:
        try:
            dt = datetime.strptime(date_str, "%b %d")
        except ValueError:
            return None

    month = dt.month
    day = dt.day

    current_year = ref_date.year
    candidate_years = [current_year - 1, current_year, current_year + 1]

    for year in candidate_years:
        try:
            candidate_date = datetime(year, month, day)
            # Check if Friday (Monday=0, Sunday=6, Friday=4)
            if candidate_date.weekday() == 4:
                return candidate_date.date()
        except ValueError:
            continue

    return None

def clean_title(title_lines):
    """Cleans and joins title lines."""
    # Filter out empty lines
    lines = [line.strip() for line in title_lines if line.strip()]
    full_title = " ".join(lines)
    # Remove excessive spaces
    full_title = re.sub(r'\s+', ' ', full_title)
    return full_title

def process_events(text):
    calendar = Calendar()
    lines = text.split('\n')

    # Identify lines with dates
    date_pattern = re.compile(r'(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+(\d{1,2})', re.IGNORECASE)

    date_indices = []
    for i, line in enumerate(lines):
        match = date_pattern.search(line)
        if match:
            # Check if it's likely a date line (not just "Dec 12" in middle of sentence, though rare in this context)
            d_str = match.group(0)
            if parse_date(d_str):
                date_indices.append((i, match))

    if not date_indices:
        print("No dates found.")
        return calendar

    print(f"Found {len(date_indices)} events.")
    date_indices.sort(key=lambda x: x[0])

    # Helper to check if a line is a separator/header
    def is_separator(line):
        line_lower = line.lower()
        if "hosted by:" in line_lower: return True
        if "passcode:" in line_lower: return True
        if "zoom" in line_lower: return True
        if "meeting id" in line_lower: return True
        if "elkin lectures are open" in line_lower: return True
        if "friday afternoons" in line_lower: return True
        if "presented by:" in line_lower: return True
        # Time regex: e.g. 10:30 AM, 12:15 p.m.
        if re.search(r'\d{1,2}:\d{2}\s*(?:AM|PM|a\.m\.|p\.m\.)', line, re.IGNORECASE): return True
        return False

    def is_title_line(line):
        # Heuristic: Title lines are usually All Caps.
        # Or explicitly "Special Event" / "No Seminar"
        if not line.strip(): return False
        if is_separator(line): return False

        # Check for special keywords
        if "NO SEMINAR" in line.upper(): return True
        if "SPECIAL EVENT" in line.upper(): return True
        if "RETREAT" in line.upper(): return True # "CANCER PREVENTION AND CONTROL RETREAT"

        # Default All Caps check
        # Remove numbers and punctuation to check if letters are uppercase
        letters = re.sub(r'[^a-zA-Z]', '', line)
        if len(letters) > 0 and letters.isupper():
            return True
        elif len(letters) == 0:
            # Lines like "FEB 6" with no letters (if cleaned) or just digits
            # But line usually has letters.
            # If line is just "123", assume True if context matches?
            # Safe to say False if we rely on All Caps titles.
            return True # e.g. "2026" or just symbols

        return False

    previous_end_idx = 0

    for k, (date_idx, match) in enumerate(date_indices):
        date_str = match.group(0)
        event_date = parse_date(date_str)

        print(f"Processing event for date: {date_str} (Line {date_idx})")

        # 1. Determine START of this event title
        # Scan backwards from date_idx. Include if is_title_line.
        start_idx = date_idx
        for i in range(date_idx - 1, previous_end_idx - 1, -1):
            line = lines[i].strip()
            if not line: continue
            if is_title_line(line):
                start_idx = i
            else:
                break

        print(f"  -> Title starts around line {start_idx}")

        # 2. Determine END of this event block (Start of next event)
        next_date_start = date_indices[k+1][0] if k + 1 < len(date_indices) else len(lines)
        limit_idx = next_date_start

        # Refine limit_idx: Look backwards from next_date_start to find where next title likely starts
        if k + 1 < len(date_indices):
            # Scan back from next date to find START of next title
            for j in range(next_date_start - 1, date_idx, -1):
                line = lines[j].strip()
                if not line: continue
                if is_title_line(line):
                    limit_idx = j
                else:
                    break

        # Search forwards for "PRESENTED BY" within the event block
        pres_idx = -1
        # Range must allow searching past date_idx up to limit_idx
        for i in range(start_idx, limit_idx):
            if "PRESENTED BY:" in lines[i].upper():
                pres_idx = i
                break

        # 3. Extract content
        title_parts = []

        # Title is from start_idx to pres_idx (or limit_idx if no pres_idx)
        # However, we must ensure we don't accidentally include presenter lines if pres_idx missed.
        # But is_title_line check prevents start_idx from going too far back.
        # Scanning forward for title: stop if not is_title_line?
        # Yes, title is contiguous block of All Caps.

        title_end_limit = pres_idx if pres_idx != -1 else limit_idx

        # Refine Title End: Scan forward from start_idx. If line is NOT title line (and not date line), stop?
        # But date line might be mixed case (if regex matched mixed).
        # And sometimes title includes mixed case "Special Event"?
        # Let's stick to the range [start_idx, title_end_limit) but exclude non-title lines?
        # No, "PRESENTED BY" is the definitive end of title.
        # If "PRESENTED BY" is missing, title ends when All Caps ends?

        current_title_scan_idx = start_idx
        while current_title_scan_idx < title_end_limit:
            line = lines[current_title_scan_idx].strip()
            # Special check: Date line is part of range but handled.
            is_date_line = (current_title_scan_idx == date_idx)

            if not is_date_line and not is_title_line(line) and line:
                # If we hit a non-title line before PRESENTED BY, what is it?
                # e.g. "Time" line?
                # If it is separator, skip it.
                if is_separator(line):
                    pass
                else:
                    # Non-separator, non-title line. Presenter info appearing before "PRESENTED BY"?
                    # Unlikely. Or maybe Title has mixed case?
                    # For safety, include it if we are sure it's not next event.
                    pass
            current_title_scan_idx += 1

        for i in range(start_idx, title_end_limit):
            line = lines[i].strip()
            if is_separator(line) and "PRESENTED BY" not in line.upper(): continue
            if "PRESENTED BY" in line.upper(): break # Should be handled by loop range, but safety.

            # Remove the date string from the line
            if i == date_idx:
                line = line.replace(date_str, "").strip()

            if line:
                title_parts.append(line)

        title = clean_title(title_parts)
        if not title:
            title = "Elkin Lecture Series"

        # Presenter extraction
        presenter_parts = []
        description_parts = []

        if pres_idx != -1:
            # Extract presenter from pres_idx onwards
            line = lines[pres_idx]
            cleaned_line = re.sub(r'PRESENTED BY:\s*', '', line, flags=re.IGNORECASE).strip()
            if cleaned_line:
                presenter_parts.append(cleaned_line)

            for i in range(pres_idx + 1, limit_idx):
                line = lines[i].strip()
                if "HOSTED BY:" in lines[i].upper():
                    description_parts.append(line)
                elif is_separator(line) and "HOSTED BY" not in line.upper():
                    pass # Skip separators like Time
                else:
                    presenter_parts.append(line)
        else:
            # No presenter found
            pass

        # Construct Description
        desc_lines = []
        if presenter_parts:
            # Filter out empty parts
            p_clean = [p for p in presenter_parts if p]
            if p_clean:
                desc_lines.append(f"Presented by: {' '.join(p_clean)}")
        if description_parts:
            desc_lines.append("\n".join(description_parts))

        full_description = "\n".join(desc_lines)

        # Update previous_end_idx
        previous_end_idx = limit_idx

        # Check for Edge Cases
        if "NO SEMINAR" in title.upper() or "NO ELKIN SEMINAR" in title.upper():
            title = "NO ELKIN SEMINAR"
        elif "SPECIAL EVENT" in title.upper():
            title = "SPECIAL EVENT"

        # Create Event
        e = Event()
        e.name = title
        e.description = full_description

        from zoneinfo import ZoneInfo
        try:
            tz = ZoneInfo("America/New_York")
        except:
            from datetime import timezone
            tz = timezone(timedelta(hours=-5))

        dt_start = datetime.combine(event_date, datetime.strptime("12:15 PM", "%I:%M %p").time())
        dt_start = dt_start.replace(tzinfo=tz)

        e.begin = dt_start
        e.duration = timedelta(hours=1)

        calendar.events.add(e)
        print(f"  -> Added Event: {title} on {event_date}")

    return calendar

def main():
    print(f"Fetching page: {PAGE_URL}")
    pdf_url = get_pdf_url(PAGE_URL)

    if not pdf_url:
        sys.exit(1)

    print(f"Found PDF URL: {pdf_url}")
    pdf_file = download_pdf(pdf_url)

    if not pdf_file:
        sys.exit(1)

    print("Extracting text from PDF...")
    text = extract_text_from_pdf(pdf_file)

    if not text:
        print("No text extracted from PDF.")
        sys.exit(1)

    print("Parsing text and generating calendar...")
    calendar = process_events(text)

    with open('elkin.ics', 'w') as f:
        f.write(calendar.serialize())

    print("elkin.ics created successfully.")

if __name__ == "__main__":
    main()
