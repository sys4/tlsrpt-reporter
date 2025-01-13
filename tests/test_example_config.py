#
#    Copyright (C) 2024 sys4 AG
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
import os
import sys

from pytlsrpt.config import options_from_cmd_cfg_env
from pytlsrpt.tlsrpt import ConfigCollectd, ConfigReporter, options_collectd, \
    options_reporter, TLSRPTCollectd, TLSRPTFetcher, TLSRPTReporter, pospars_fetcher

class MyTestCase(unittest.TestCase):
    """
    Test usability of example config file
    """

    def setUp(self):
        sys.argv.clear()
        sys.argv.append("programname")
        self.example_filename = os.path.join(os.path.dirname(__file__), "..", "pytlsrpt" , "example.cfg")
        sys.argv.append("--config_file")
        sys.argv.append(self.example_filename)

    def test_collectd_config(self):
        (configvars, params, _) = options_from_cmd_cfg_env(options_collectd, TLSRPTCollectd.DEFAULT_CONFIG_FILE,
                                                        TLSRPTCollectd.CONFIG_SECTION,
                                                        TLSRPTCollectd.ENVIRONMENT_PREFIX,
                                                        {})
        config = ConfigCollectd(**configvars)
        self.assertEqual(config.log_level, "debug")
        self.assertEqual(config.logfilename, "/tmp/tlsrpt-collectd.log")

    def test_fetcher_config(self):
        sys.argv.append("2000-01-01")  # add required parameter 'day'
        (configvars, params, _) = options_from_cmd_cfg_env(options_collectd, TLSRPTFetcher.DEFAULT_CONFIG_FILE,
                                                        TLSRPTFetcher.CONFIG_SECTION,
                                                        TLSRPTFetcher.ENVIRONMENT_PREFIX,
                                                        pospars_fetcher)
        config = ConfigCollectd(**configvars)
        self.assertEqual(config.log_level, "debug")
        self.assertEqual(config.logfilename, "/tmp/tlsrpt-fetcher.log")

    def test_reporter_config(self):
        (configvars, params, _) = options_from_cmd_cfg_env(options_reporter, TLSRPTReporter.DEFAULT_CONFIG_FILE,
                                                        TLSRPTReporter.CONFIG_SECTION,
                                                        TLSRPTReporter.ENVIRONMENT_PREFIX,
                                                        {})
        config = ConfigReporter(**configvars)
        self.assertEqual(config.log_level, "debug")
        self.assertEqual(config.logfilename, "/tmp/tlsrpt-reporter.log")


if __name__ == '__main__':
    unittest.main()
