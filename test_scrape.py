import unittest
from unittest.mock import MagicMock, patch, mock_open
import json
import os
import sys
from datetime import datetime, timezone, timedelta

# Mock google.genai and google.genai.types before importing scrape
sys.modules["google.genai"] = MagicMock()
sys.modules["google.genai.types"] = MagicMock()

import scrape
from ics import Calendar, Event

class TestScrape(unittest.TestCase):

    @patch('scrape.datetime')
    @patch("builtins.open", new_callable=mock_open)
    @patch("os.path.exists")
    def test_create_calendar_from_json_year_correction(self, mock_exists, mock_file, mock_datetime):
        # Simulate no existing file
        mock_exists.return_value = False

        # Configure mock_datetime
        mock_datetime.strptime.side_effect = datetime.strptime
        mock_datetime.combine.side_effect = datetime.combine

        # Set "current time" to October 2025
        # TZ_NY is used in scrape.py, so we should return a timezone-aware datetime
        fixed_now = datetime(2025, 10, 15, tzinfo=timezone(timedelta(hours=-5)))
        mock_datetime.now.return_value = fixed_now

        # Test case: Input date has 2024, but should result in 2025 (current year)
        # Because we ignore the input year.
        events_data = [
            {"date": "2024-10-20", "speaker": "Dr. Future", "status": "confirmed"}
        ]

        calendar = scrape.create_calendar_from_json(events_data)
        self.assertEqual(len(calendar.events), 1)
        event = list(calendar.events)[0]
        self.assertEqual(event.begin.year, 2025)
        self.assertEqual(event.begin.month, 10)
        self.assertEqual(event.begin.day, 20)

    @patch('scrape.datetime')
    @patch("builtins.open", new_callable=mock_open)
    @patch("os.path.exists")
    def test_create_calendar_from_json_next_year_logic(self, mock_exists, mock_file, mock_datetime):
        mock_exists.return_value = False

        mock_datetime.strptime.side_effect = datetime.strptime
        mock_datetime.combine.side_effect = datetime.combine

        # Set "current time" to Nov 2025
        fixed_now = datetime(2025, 11, 15, tzinfo=timezone(timedelta(hours=-5)))
        mock_datetime.now.return_value = fixed_now

        # Test case: Input date is Jan 5, 2024 (stale year in PDF)
        # Should result in Jan 5, 2026 (Next year) because current month is Nov (>=10) and event is Jan.
        events_data = [
            {"date": "2024-01-05", "speaker": "Dr. Next", "status": "confirmed"}
        ]

        calendar = scrape.create_calendar_from_json(events_data)
        event = list(calendar.events)[0]
        self.assertEqual(event.begin.year, 2026)
        self.assertEqual(event.begin.month, 1)
        self.assertEqual(event.begin.day, 5)

    @patch('scrape.datetime')
    @patch("builtins.open", new_callable=mock_open)
    @patch("os.path.exists")
    def test_create_calendar_from_json_deduplication(self, mock_exists, mock_file, mock_datetime):
        mock_exists.return_value = False

        mock_datetime.strptime.side_effect = datetime.strptime
        mock_datetime.combine.side_effect = datetime.combine
        fixed_now = datetime(2025, 3, 1, tzinfo=timezone(timedelta(hours=-5)))
        mock_datetime.now.return_value = fixed_now

        # Duplicate dates
        events_data = [
            {"date": "2025-03-10", "speaker": "Speaker 1", "status": "confirmed"},
            {"date": "2025-03-10", "speaker": "Speaker 1 Duplicate", "status": "confirmed"},
            {"date": "2025-03-17", "speaker": "Speaker 2", "status": "confirmed"}
        ]

        calendar = scrape.create_calendar_from_json(events_data)
        self.assertEqual(len(calendar.events), 2)
        dates = sorted([e.begin.day for e in calendar.events])
        self.assertEqual(dates, [10, 17])

    @patch('scrape.datetime')
    @patch("builtins.open", new_callable=mock_open)
    @patch("os.path.exists")
    def test_create_calendar_from_json_cancelled(self, mock_exists, mock_file, mock_datetime):
        mock_exists.return_value = False

        mock_datetime.strptime.side_effect = datetime.strptime
        mock_datetime.combine.side_effect = datetime.combine
        fixed_now = datetime(2025, 3, 1, tzinfo=timezone(timedelta(hours=-5)))
        mock_datetime.now.return_value = fixed_now

        # Cancelled event with reason in speaker field
        events_data = [
            {"date": "2025-03-24", "speaker": "Holiday", "status": "cancelled", "reason": "Holiday"}
        ]

        calendar = scrape.create_calendar_from_json(events_data)
        event = list(calendar.events)[0]
        # Title should be the reason (speaker field)
        self.assertEqual(event.name, "NO SEMINAR: Holiday")
        self.assertIn("Cancelled: Holiday", event.description)

    @patch('scrape.datetime')
    @patch("builtins.open", new_callable=mock_open)
    @patch("os.path.exists")
    def test_create_calendar_from_json_special_event(self, mock_exists, mock_file, mock_datetime):
        mock_exists.return_value = False

        mock_datetime.strptime.side_effect = datetime.strptime
        mock_datetime.combine.side_effect = datetime.combine
        fixed_now = datetime(2025, 3, 1, tzinfo=timezone(timedelta(hours=-5)))
        mock_datetime.now.return_value = fixed_now

        # Special Event
        events_data = [
            {"date": "2025-03-31", "speaker": "Symposium", "status": "special_event"}
        ]

        calendar = scrape.create_calendar_from_json(events_data)
        event = list(calendar.events)[0]
        self.assertEqual(event.name, "SPECIAL EVENT: Symposium")

    @patch("scrape.datetime")
    @patch("scrape.genai")
    def test_analyze_pdf_with_gemini_mock(self, mock_genai, mock_datetime):
        # Set "current time" for analyze_pdf context
        fixed_now = datetime(2025, 5, 1, tzinfo=timezone(timedelta(hours=-5)))
        mock_datetime.now.return_value = fixed_now

        mock_client = MagicMock()
        mock_genai.Client.return_value = mock_client

        # Mock file upload
        mock_file_upload_response = MagicMock()
        mock_file_upload_response.uri = "http://mock.uri"
        mock_client.files.upload.return_value = mock_file_upload_response

        # Mock generate_content
        mock_response = MagicMock()
        mock_response.text = '```json\n[{"date": "2025-04-01", "speaker": "Test", "status": "confirmed"}]\n```'
        mock_client.models.generate_content.return_value = mock_response

        os.environ["GEMINI_API_KEY"] = "fake_key"

        events = scrape.analyze_pdf_with_gemini("dummy.pdf")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["speaker"], "Test")

        # Verify calls
        mock_genai.Client.assert_called_with(api_key="fake_key")
        mock_client.files.upload.assert_called_with(file="dummy.pdf")

        # Verify prompt args
        args, kwargs = mock_client.models.generate_content.call_args
        self.assertEqual(kwargs['model'], "gemini-3-flash-preview")

        prompt_text = kwargs['contents'][1]
        self.assertIn("The current year is 2025", prompt_text)
        self.assertIn("The month is May", prompt_text)

    def test_analyze_pdf_with_gemini_missing_key(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError):
                scrape.analyze_pdf_with_gemini("dummy.pdf")

    @patch('scrape.datetime')
    @patch("builtins.open", new_callable=mock_open)
    @patch("os.path.exists")
    def test_create_calendar_from_json_none_values(self, mock_exists, mock_file, mock_datetime):
        mock_exists.return_value = False

        mock_datetime.strptime.side_effect = datetime.strptime
        mock_datetime.combine.side_effect = datetime.combine
        fixed_now = datetime(2025, 3, 1, tzinfo=timezone(timedelta(hours=-5)))
        mock_datetime.now.return_value = fixed_now

        # Events with None values for string fields
        events_data = [
            {
                "date": "2025-03-24",
                "speaker": None,
                "topic": None,
                "host": None,
                "status": "confirmed",
                "reason": None
            }
        ]

        # This should not raise AttributeError
        calendar = scrape.create_calendar_from_json(events_data)
        event = list(calendar.events)[0]
        self.assertEqual(event.name, "Elkin: Unknown Speaker")

    @patch('scrape.datetime')
    @patch("builtins.open", new_callable=mock_open, read_data="BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//My Calendar//MXM//EN\nBEGIN:VEVENT\nUID:old-uid\nSUMMARY:Old Event\nDTSTART:20250101T120000Z\nEND:VEVENT\nEND:VCALENDAR")
    @patch("os.path.exists")
    def test_merge_existing_events(self, mock_exists, mock_file, mock_datetime):
        # Simulate existing file
        mock_exists.return_value = True

        mock_datetime.strptime.side_effect = datetime.strptime
        mock_datetime.combine.side_effect = datetime.combine
        fixed_now = datetime(2025, 1, 10, tzinfo=timezone(timedelta(hours=-5)))
        mock_datetime.now.return_value = fixed_now

        # New event data
        events_data = [
            {"date": "2025-02-01", "speaker": "New Speaker", "status": "confirmed"}
        ]

        calendar = scrape.create_calendar_from_json(events_data)

        # Check that we have 2 events: one old, one new
        self.assertEqual(len(calendar.events), 2)
        uids = {e.uid for e in calendar.events}
        self.assertIn("old-uid", uids)
        # Calculate new UID
        new_uid = "elkin-2025-02-01@winship.emory.edu"
        self.assertIn(new_uid, uids)

    @patch('scrape.datetime')
    @patch("builtins.open", new_callable=mock_open, read_data="BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//My Calendar//MXM//EN\nBEGIN:VEVENT\nUID:elkin-2025-02-01@winship.emory.edu\nSUMMARY:Old Version\nDTSTART:20250201T171500Z\nEND:VEVENT\nEND:VCALENDAR")
    @patch("os.path.exists")
    def test_merge_update_existing_event(self, mock_exists, mock_file, mock_datetime):
        # Simulate existing file with an event that will be updated
        mock_exists.return_value = True

        mock_datetime.strptime.side_effect = datetime.strptime
        mock_datetime.combine.side_effect = datetime.combine
        fixed_now = datetime(2025, 1, 10, tzinfo=timezone(timedelta(hours=-5)))
        mock_datetime.now.return_value = fixed_now

        # New event data (same date, different speaker)
        events_data = [
            {"date": "2025-02-01", "speaker": "Updated Speaker", "status": "confirmed"}
        ]

        calendar = scrape.create_calendar_from_json(events_data)

        # Check that we still have 1 event, but updated
        self.assertEqual(len(calendar.events), 1)
        event = list(calendar.events)[0]
        self.assertEqual(event.uid, "elkin-2025-02-01@winship.emory.edu")
        self.assertEqual(event.name, "Elkin: Updated Speaker")

if __name__ == '__main__':
    unittest.main()
