import requests
from bs4 import BeautifulSoup
from ics import Calendar, Event
from datetime import datetime, timedelta, timezone, date
import io
import os
import sys
import json
import re
import google.generativeai as genai
from urllib.parse import urljoin, urlparse

try:
    from zoneinfo import ZoneInfo
    TZ_NY = ZoneInfo("America/New_York")
except Exception:
    TZ_NY = timezone(timedelta(hours=-5))

# Constants for scraping
PAGE_URL = "https://winshipcancer.emory.edu/education-and-training/continuing-education/elkin-lecture-series.php"
# Using regex for link text matching as before
PDF_LINK_TEXT_REGEX = re.compile(r'Elkin Lecture Series Flyer \(PDF\)', re.IGNORECASE)

def get_pdf_url(page_url):
    try:
        response = requests.get(page_url)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')

        # Find the link with text "Elkin Lecture Series Flyer (PDF)"
        link = soup.find('a', string=PDF_LINK_TEXT_REGEX)

        if link and link.get('href'):
            href = link['href']
            full_url = urljoin(page_url, href)

            # Security validation: Ensure scheme is http/https and domain matches page_url
            parsed_url = urlparse(full_url)
            parsed_page_url = urlparse(page_url)

            if parsed_url.scheme not in ('http', 'https'):
                print(f"Security Warning: Invalid URL scheme '{parsed_url.scheme}' in PDF link.")
                return None

            if parsed_url.netloc != parsed_page_url.netloc:
                print(f"Security Warning: URL domain mismatch '{parsed_url.netloc}' in PDF link.")
                return None

            return full_url
        else:
            print("PDF link not found on the page.")
            return None
    except Exception as e:
        print(f"Error fetching page: {e}")
        raise e

def download_pdf(pdf_url, output_path="flyer.pdf"):
    try:
        response = requests.get(pdf_url)
        response.raise_for_status()
        with open(output_path, 'wb') as f:
            f.write(response.content)
        return output_path
    except Exception as e:
        print(f"Error downloading PDF: {e}")
        raise e

def analyze_pdf_with_gemini(pdf_path):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY environment variable not set.")

    genai.configure(api_key=api_key)

    try:
        print(f"Uploading {pdf_path} to Gemini...")
        sample_file = genai.upload_file(path=pdf_path, display_name="Elkin Flyer")

        print(f"File uploaded: {sample_file.uri}")

        # Using gemini-3.0-flash as requested
        model = genai.GenerativeModel(model_name="gemini-3-flash-preview")

        # Inject Context: Determine current_year and current_month
        now = datetime.now(TZ_NY)
        current_year = now.year
        current_month = now.strftime("%B")

        prompt = f"""
        Context: The current year is {current_year}. The month is {current_month}.

        Task: Extract the schedule for the Elkin Lecture Series. Ignore 'Hosts', 'Committee Members', or 'Introduced by'. Only extract the main Speaker or Topic.

        Constraint: There is usually only ONE event per date. If you see two names, determine who is the Speaker and who is the Host. Return only the Speaker.

        Constraint: If the text says 'No Seminar', 'Holiday', or 'Special Event', mark the status as 'cancelled' and the title as the specific reason (e.g., 'No Seminar: Special Event').

        Return a pure JSON list of objects with keys:
        - date (YYYY-MM-DD)
        - speaker (string, extract the full name and credentials if available. If cancelled, this field should contain the reason.)
        - status ('confirmed', 'cancelled', or 'special_event').
        """

        print("Generating content...")
        response = model.generate_content(
            [sample_file, prompt],
            generation_config={"response_mime_type": "application/json"}
        )

        print("Response received.")
        cleaned_text = response.text.strip()
        # Remove markdown code blocks if present
        if cleaned_text.startswith("```json"):
            cleaned_text = cleaned_text[7:]
        elif cleaned_text.startswith("```"):
            cleaned_text = cleaned_text[3:]

        if cleaned_text.endswith("```"):
            cleaned_text = cleaned_text[:-3]

        return json.loads(cleaned_text.strip())
    except Exception as e:
        print(f"Error calling Gemini API: {e}")
        raise e

def process_events(events_data):
    calendar = Calendar()

    # In case the JSON is a dict with a key like "events"
    if isinstance(events_data, dict):
        if "events" in events_data:
            events_data = events_data["events"]
        else:
            # try to find a list in values
            found_list = False
            for v in events_data.values():
                if isinstance(v, list):
                    events_data = v
                    found_list = True
                    break
            if not found_list:
                print("Error: content is not a list and no list found in dict")
                return calendar

    if not isinstance(events_data, list):
        print("Error: content is not a list")
        return calendar

    print(f"Found {len(events_data)} events.")

    # Determine current year for validation
    now = datetime.now(TZ_NY)
    current_year = now.year
    current_month_num = now.month

    seen_dates = set()

    for item in events_data:
        date_str = item.get("date")
        speaker = item.get("speaker", "Unknown Speaker")
        status = item.get("status", "confirmed")

        if not date_str:
            print(f"Skipping event with missing date: {item}")
            continue

        try:
            # Parse the date string from Gemini to get month and day, ignoring the year
            temp_date = datetime.strptime(date_str, "%Y-%m-%d")
            event_month = temp_date.month
            event_day = temp_date.day
        except ValueError:
            print(f"Error parsing date: {date_str}")
            continue

        # Year Validation Logic
        # Construct the date object using the current year (or current_year + 1 if the month is January and we are scraping for next year).
        # We assume scraping for next year happens if current month is late in the year (>= 10) and event is in Jan.
        year = current_year
        if event_month == 1 and current_month_num >= 10:
             year = current_year + 1

        try:
             event_date = date(year, event_month, event_day)
        except ValueError as e:
             print(f"Error creating date with year {year}: {e}")
             continue

        # Deduplication Logic
        if event_date in seen_dates:
             print(f"Skipping duplicate event on {event_date}")
             continue
        seen_dates.add(event_date)

        title = speaker
        description = ""

        if status == "cancelled":
            # Constraint says title should be the specific reason. Assuming Gemini puts reason in 'speaker'.
            title = speaker
            description = f"Cancelled: {speaker}"
        elif status == "special_event":
            # If status is special_event, it might be an actual event or a cancellation.
            # Assuming it is an event unless it says "No Seminar".
            # The prompt says: "If the text says ... 'Special Event', mark the status as 'cancelled'..."
            # So if we see 'special_event' status here, it might be from older logic or Gemini deviated.
            # We'll treat it as Special Event.
            title = f"SPECIAL EVENT: {speaker}"
            description = f"Special Event: {speaker}"
        else:
            # Confirmed
            title = speaker
            description = f"Presented by: {speaker}"

        # Set time to 12:15 PM EST
        # Combine date and time
        dt_start = datetime.combine(event_date, datetime.strptime("12:15 PM", "%I:%M %p").time())
        dt_start = dt_start.replace(tzinfo=TZ_NY)

        e = Event()
        e.name = title
        e.description = description
        e.begin = dt_start
        e.duration = timedelta(hours=1)

        calendar.events.add(e)
        print(f"  -> Added Event: {title} on {event_date}")

    return calendar

def main():
    print(f"Fetching page: {PAGE_URL}")
    pdf_url = get_pdf_url(PAGE_URL)

    if not pdf_url:
        print("Could not find PDF URL.")
        sys.exit(1)

    print(f"Found PDF URL: {pdf_url}")
    pdf_path = download_pdf(pdf_url)

    if not pdf_path:
        print("Failed to download PDF.")
        sys.exit(1)

    print("Analyzing PDF with Gemini...")
    try:
        events_data = analyze_pdf_with_gemini(pdf_path)
    except Exception as e:
        print(f"Failed to analyze PDF: {e}")
        sys.exit(1)

    if not events_data:
        print("No events data returned from Gemini.")
        sys.exit(1)

    print("Generating calendar...")
    calendar = process_events(events_data)

    with open('elkin.ics', 'w') as f:
        f.write(calendar.serialize())

    print("elkin.ics created successfully.")

if __name__ == "__main__":
    main()
