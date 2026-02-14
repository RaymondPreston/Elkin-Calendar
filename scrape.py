import requests
from bs4 import BeautifulSoup
from ics import Calendar, Event
from datetime import datetime, timedelta, timezone
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

        # Using gemini-2.0-flash as requested (assuming 3.0 was a typo for the latest flash model)
        model = genai.GenerativeModel(model_name="gemini-2.0-flash")

        prompt = """
        Extract all seminar dates, speaker names, and special statuses from this text.
        Return a pure JSON list of objects with keys:
        - date (YYYY-MM-DD)
        - speaker (string, extract the full name and credentials if available)
        - status ('confirmed', 'cancelled', or 'special_event').

        If the year is missing, assume the current year or the upcoming year based on the month.
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

    for item in events_data:
        date_str = item.get("date")
        speaker = item.get("speaker", "Unknown Speaker")
        status = item.get("status", "confirmed")

        if not date_str:
            print(f"Skipping event with missing date: {item}")
            continue

        try:
            event_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            print(f"Error parsing date: {date_str}")
            continue

        title = speaker
        description = ""

        if status == "cancelled":
            title = "NO SEMINAR"
            description = f"Cancelled: {speaker}"
        elif status == "special_event":
            title = "SPECIAL EVENT"
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
