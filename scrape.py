import requests
from bs4 import BeautifulSoup
import pdfplumber
import re
from ics import Calendar, Event
from datetime import datetime, timedelta
import io
from urllib.parse import urljoin
import sys

def get_pdf_url(page_url):
    try:
        response = requests.get(page_url)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')

        # Find the link with text "Elkin Lecture Series Flyer (PDF)"
        link = soup.find('a', string=re.compile(r'Elkin Lecture Series Flyer \(PDF\)', re.IGNORECASE))

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
        # Try full month name
        dt = datetime.strptime(date_str, "%B %d")
    except ValueError:
        try:
            # Try abbreviated month name
            dt = datetime.strptime(date_str, "%b %d")
        except ValueError:
            return None

    month = dt.month
    day = dt.day

    # Candidates for year: current year, previous year, next year
    current_year = ref_date.year
    candidate_years = [current_year - 1, current_year, current_year + 1]

    for year in candidate_years:
        try:
            candidate_date = datetime(year, month, day)
            # Check if Friday (Monday=0, Sunday=6, Friday=4)
            if candidate_date.weekday() == 4:
                return candidate_date.date()
        except ValueError:
            # Invalid date (e.g. Feb 29 on non-leap year)
            continue

    return None

def main():
    page_url = "https://winshipcancer.emory.edu/education-and-training/continuing-education/elkin-lecture-series.php"

    print(f"Fetching page: {page_url}")
    pdf_url = get_pdf_url(page_url)

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

    print("Parsing text...")
    # Regex to find dates: Month Day (e.g., Feb 12, February 12)
    # Note: We need to match lines that contain these dates to check for context (No Seminar, etc.)

    calendar = Calendar()

    lines = text.split('\n')
    date_pattern = re.compile(r'(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+(\d{1,2})', re.IGNORECASE)

    for line in lines:
        match = date_pattern.search(line)
        if match:
            date_str = match.group(0)
            print(f"Found potential date: {date_str} in line: '{line.strip()}'")

            event_date = parse_date(date_str)

            if event_date:
                print(f"  -> Resolved to: {event_date}")

                # Create event
                e = Event()

                # Set time to 12:15 PM EST
                # Note: EST is UTC-5. EDT is UTC-4.
                # Since we want to be correct with DST, we should probably use a timezone library or rely on ics handling.
                # However, for simplicity and robustness without heavy timezone libs (like pytz if not installed),
                # we can define the event in local time and set the timezone.
                # Or easier: construct the datetime and let ics handle it?
                # The 'ics' library handles arrow objects well.

                # Let's set the begin time.
                # 12:15 PM = 12:15

                # Using simple timezone offset might be risky with DST.
                # But since the prompt says "12:15 PM EST", usually that implies Eastern Time (ET), changing with DST.
                # Let's try to set it to America/New_York if possible, or approximate.
                # Since we don't have 'pytz' in requirements (only 'requests', 'beautifulsoup4', 'pdfplumber', 'ics'),
                # we rely on standard libs or what 'ics' provides.
                # 'ics' uses 'arrow' internally? Wait, I saw 'arrow' being installed.
                # 'ics' creates events.

                # Let's import arrow if needed, but we can pass datetime.
                # To handle ET correctly, we can use zoneinfo if python 3.9+ (we have 3.12).

                from zoneinfo import ZoneInfo
                try:
                    tz = ZoneInfo("America/New_York")
                except:
                    # Fallback if tzdata not available (though it was installed)
                    print("  Warning: America/New_York timezone not found, using UTC-5 fixed.")
                    from datetime import timezone
                    tz = timezone(timedelta(hours=-5))

                dt_start = datetime.combine(event_date, datetime.strptime("12:15 PM", "%I:%M %p").time())
                dt_start = dt_start.replace(tzinfo=tz)

                e.begin = dt_start
                e.duration = timedelta(hours=1) # Assume 1 hour duration

                # Determine title
                title = "Elkin Lecture Series"
                if "No Seminar" in line or "NO SEMINAR" in line.upper():
                    title = "NO ELKIN SEMINAR"
                elif "Special Event" in line or "SPECIAL EVENT" in line.upper():
                    title = "SPECIAL EVENT"

                e.name = title
                e.description = line.strip() # Put the full line in description for context

                calendar.events.add(e)
            else:
                print(f"  -> Could not resolve year for {date_str} to be a Friday.")

    with open('elkin.ics', 'w') as f:
        f.write(calendar.serialize())

    print("elkin.ics created successfully.")

if __name__ == "__main__":
    main()
