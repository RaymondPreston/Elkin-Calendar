import unittest
from unittest.mock import MagicMock, patch
import json
import os
import sys
from datetime import datetime, timezone, timedelta

# Mock google.generativeai
sys.modules["google.generativeai"] = MagicMock()

import scrape
from ics import Calendar, Event

class TestScrape(unittest.TestCase):

    @patch('scrape.datetime')
    def test_create_calendar_from_json_year_correction(self, mock_datetime):
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
    def test_create_calendar_from_json_next_year_logic(self, mock_datetime):
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
    def test_create_calendar_from_json_deduplication(self, mock_datetime):
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
    def test_create_calendar_from_json_cancelled(self, mock_datetime):
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
    def test_create_calendar_from_json_special_event(self, mock_datetime):
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

        mock_model = MagicMock()
        mock_genai.GenerativeModel.return_value = mock_model

        mock_response = MagicMock()
        mock_response.text = '```json\n[{"date": "2025-04-01", "speaker": "Test", "status": "confirmed"}]\n```'
        mock_model.generate_content.return_value = mock_response

        os.environ["GEMINI_API_KEY"] = "fake_key"

        events = scrape.analyze_pdf_with_gemini("dummy.pdf")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["speaker"], "Test")

        # Verify prompt contains current year
        args, kwargs = mock_model.generate_content.call_args
        # The first argument is a list [sample_file, prompt]
        prompt_text = args[0][1]
        self.assertIn("The current year is 2025", prompt_text)
        self.assertIn("The month is May", prompt_text)

    def test_analyze_pdf_with_gemini_missing_key(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError):
                scrape.analyze_pdf_with_gemini("dummy.pdf")

if __name__ == '__main__':
    unittest.main()
