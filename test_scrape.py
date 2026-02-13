import unittest
from scrape import clean_title

class TestCleanTitle(unittest.TestCase):
    def test_clean_title_normal(self):
        """Test with a standard list of strings."""
        input_lines = ["Hello", "World"]
        expected = "Hello World"
        self.assertEqual(clean_title(input_lines), expected)

    def test_clean_title_extra_whitespace(self):
        """Test with strings containing extra whitespace."""
        input_lines = ["  Hello  ", "   World   "]
        expected = "Hello World"
        self.assertEqual(clean_title(input_lines), expected)

        input_lines = ["Hello   World"]
        expected = "Hello World"
        self.assertEqual(clean_title(input_lines), expected)

        input_lines = ["Hello\tWorld", "Test\nString"]
        expected = "Hello World Test String"
        self.assertEqual(clean_title(input_lines), expected)

    def test_clean_title_empty_lines(self):
        """Test with empty lines in the list."""
        input_lines = ["Hello", "", "World", "   "]
        expected = "Hello World"
        self.assertEqual(clean_title(input_lines), expected)

    def test_clean_title_empty_list(self):
        """Test with an empty list."""
        input_lines = []
        expected = ""
        self.assertEqual(clean_title(input_lines), expected)

    def test_clean_title_all_empty(self):
        """Test with a list of only empty/whitespace strings."""
        input_lines = ["", "   ", "\t"]
        expected = ""
        self.assertEqual(clean_title(input_lines), expected)

if __name__ == '__main__':
    unittest.main()
