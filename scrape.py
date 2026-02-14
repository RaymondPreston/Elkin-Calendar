import requests
from bs4 import BeautifulSoup
from ics import Calendar, Event
from datetime import datetime, timedelta, timezone, date
import io
import os
import sys
import json
import re
from google import genai
from google.genai import types
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo

TZ_NY = ZoneInfo("America/New_York")

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

    client = genai.Client(api_key=api_key)

    try:
        print(f"Uploading {pdf_path} to Gemini...")
        sample_file = client.files.upload(file=pdf_path)

        print(f"File uploaded: {sample_file.uri}")

        # Inject Context: Determine current_year and current_month
        now = datetime.now(TZ_NY)
        current_year = now.year
        current_month = now.strftime("%B")

        prompt = f"""
        Context: The current year is {current_year}. The month is {current_month}.

        Task: Extract the schedule for the Elkin Lecture Series.

        Details to extract:
        - Date (YYYY-MM-DD)
        - Speaker Name (if applicable)
        - Topic (title of the talk)
        - Host (person hosting)
        - Status ('confirmed', 'cancelled', 'special_event')
        - Reason (if cancelled or special event, e.g., 'Holiday', 'No Seminar')

        Constraint: There is usually only ONE event per date. If you see two names, determine who is the Speaker and who is the Host.

        Constraint: If the text says 'No Seminar', 'Holiday', or 'Special Event', mark the status as 'cancelled' (or 'special_event') and provide the 'reason'.

        Return a pure JSON list of objects with keys:
        - date
        - speaker
        - topic
        - host
        - status
        - reason
        """

        print("Generating content...")
        response = client.models.generate_content(
            model="gemini-3-flash-preview",
            contents=[sample_file, prompt],
            config=types.GenerateContentConfig(response_mime_type="application/json")
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

def create_calendar_from_json(events_data):
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
                return

    if not isinstance(events_data, list):
        print("Error: content is not a list")
        return

    print(f"Found {len(events_data)} events.")

    # Determine current year for validation
    now = datetime.now(TZ_NY)
    current_year = now.year
    current_month_num = now.month

    seen_dates = set()

    for item in events_data:
        date_str = item.get("date")
        speaker = (item.get("speaker") or "").strip()
        topic = (item.get("topic") or "").strip()
        host = (item.get("host") or "").strip()
        status = (item.get("status") or "confirmed").lower()
        reason = (item.get("reason") or "").strip()

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

        title = ""
        description_lines = []

        # Determine Title and Description based on status
        if status == "cancelled":
            # Priority: Reason -> Speaker -> "Cancelled"
            cancellation_reason = reason if reason else speaker
            if not cancellation_reason:
                cancellation_reason = "Cancelled"

            title = f"NO SEMINAR: {cancellation_reason}"
            description_lines.append(f"Cancelled: {cancellation_reason}")

        elif status == "special_event":
            event_reason = reason if reason else speaker
            title = f"SPECIAL EVENT: {event_reason}"
            description_lines.append(f"Special Event: {event_reason}")
            if topic:
                description_lines.append(f"Topic: {topic}")
            if host:
                description_lines.append(f"Host: {host}")

        else: # Confirmed or unknown
            # Fallback for speaker name if empty
            speaker_name = speaker if speaker else "Unknown Speaker"
            title = f"Elkin: {speaker_name}"

            if topic:
                description_lines.append(f"Topic: {topic}")
            if host:
                description_lines.append(f"Host: {host}")

            description_lines.append(f"Presented by: {speaker_name}")

        description = "\n".join(description_lines)

        # Set time to 12:15 PM EST
        dt_start = datetime.combine(event_date, datetime.strptime("12:15 PM", "%I:%M %p").time())
        dt_start = dt_start.replace(tzinfo=TZ_NY)

        # Generate Deterministic UID
        # "elkin-{date_str}@winship.emory.edu"
        # We use the CALCULATED date (YYYY-MM-DD)
        uid_date_str = event_date.strftime("%Y-%m-%d")
        uid = f"elkin-{uid_date_str}@winship.emory.edu"

        e = Event()
        e.name = title
        e.description = description
        e.begin = dt_start
        e.duration = timedelta(hours=1)
        e.location = "John H. Kauffman Auditorium (C5012) / Zoom"
        e.uid = uid

        calendar.events.add(e)
        print(f"  -> Added Event: {title} on {event_date} (UID: {uid})")

    with open('elkin.ics', 'w') as f:
        f.write(calendar.serialize())

    print("elkin.ics created successfully.")
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
    create_calendar_from_json(events_data)

if __name__ == "__main__":
    main()
