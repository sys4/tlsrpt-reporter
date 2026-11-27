#
#    Copyright (C) 2024-2026 sys4 AG
#    Author Boris Lohner bl@sys4.de
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.
#    If not, see <http://www.gnu.org/licenses/>.
#

import unittest
import logging


class MyTestCase(unittest.TestCase):
    def setUp(self):
        self.defined_log_levels = {"debug": 10, "info": 20, "warning": 30, "error": 40, "critical": 50}
        self.additional_log_levels = {"warn":30, "fatal":50}

    def test_available_logging_options(self):
        """
        Test for available log level names
        """
        log_levels = {**self.defined_log_levels, **self.additional_log_levels}
        for level, expected_value in log_levels.items():
            numeric_level = getattr(logging, level.upper(), None)
            self.assertEqual(numeric_level, expected_value)

if __name__ == '__main__':
    unittest.main()
