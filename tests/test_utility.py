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
from tlsrpt_reporter import utility

class MyTestCase(unittest.TestCase):
    def test_extract_domain_from_email_address(self):
        testcases = {
            'test@example.com': 'example.com',
            'test@test@example.com': 'example.com',
        }
        for k,v in testcases.items():
            self.assertEqual( utility.extract_domain_from_email_address(k), v)

    def test_extract_errors(self):
        with self.assertRaises(utility.MalformedEmailAddressException) as cm:
            domain = utility.extract_domain_from_email_address('example.com')
        self.assertEqual(cm.exception.__str__(), "Could not extract domain part from example.com")

    def test_duration(self):
        # New Duration object without events yet must return zero rate
        duration = utility.Duration()
        rate = duration.rate()
        self.assertEqual(rate, 0)
        # Now add an event and the rate must be positive
        duration.add()
        rate = duration.rate()
        self.assertGreater(rate, 0)

if __name__ == '__main__':
    unittest.main()
