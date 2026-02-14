import unittest
from unittest.mock import MagicMock, patch
import json
import os
import sys

# Mock google.generativeai
sys.modules["google.generativeai"] = MagicMock()

import scrape
from ics import Calendar, Event

class TestScrape(unittest.TestCase):

    def test_process_events_confirmed(self):
        events_data = [
            {"date": "2024-03-01", "speaker": "Dr. Smith", "status": "confirmed"}
        ]

        calendar = scrape.process_events(events_data)
        self.assertEqual(len(calendar.events), 1)
        event = list(calendar.events)[0]
        self.assertEqual(event.name, "Dr. Smith")
        self.assertEqual(event.begin.format("YYYY-MM-DD HH:mm:ss ZZ"), "2024-03-01 12:15:00 -05:00")
        self.assertIn("Presented by: Dr. Smith", event.description)

    def test_process_events_cancelled(self):
        events_data = [
            {"date": "2024-03-08", "speaker": "Dr. Jones", "status": "cancelled"}
        ]

        calendar = scrape.process_events(events_data)
        self.assertEqual(len(calendar.events), 1)
        event = list(calendar.events)[0]
        self.assertEqual(event.name, "NO SEMINAR")
        self.assertIn("Cancelled: Dr. Jones", event.description)

    def test_process_events_special(self):
        events_data = [
            {"date": "2024-03-15", "speaker": "Symposium", "status": "special_event"}
        ]

        calendar = scrape.process_events(events_data)
        self.assertEqual(len(calendar.events), 1)
        event = list(calendar.events)[0]
        self.assertEqual(event.name, "SPECIAL EVENT")
        self.assertIn("Special Event: Symposium", event.description)

    def test_analyze_pdf_with_gemini_mock(self):
        with patch("scrape.genai") as mock_genai:
            mock_model = MagicMock()
            mock_genai.GenerativeModel.return_value = mock_model

            mock_response = MagicMock()
            mock_response.text = '```json\n[{"date": "2024-04-01", "speaker": "Test", "status": "confirmed"}]\n```'
            mock_model.generate_content.return_value = mock_response

            os.environ["GEMINI_API_KEY"] = "fake_key"

            events = scrape.analyze_pdf_with_gemini("dummy.pdf")
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["speaker"], "Test")

    def test_analyze_pdf_with_gemini_missing_key(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError):
                scrape.analyze_pdf_with_gemini("dummy.pdf")

if __name__ == '__main__':
    unittest.main()
