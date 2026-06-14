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

import collections
import logging
import sqlite3
import sys

from tlsrpt_reporter import config
from tlsrpt_reporter import mapping
from tlsrpt_reporter import tlsrpt
from tlsrpt_reporter import utility


ConfigTlsrptctlMaptest = collections.namedtuple("ConfigTlsrptctlMaptest",
                                                ['tlsrpt_record_map',
                                                 'mail_destination_map',
                                                 'http_upload_map'])


ConfigTlsrptctlStatus = collections.namedtuple("ConfigTlsrptctlMaptest",['dbname'])

def show_report_destinations(msg, dests):
    """
    Pretty-print a list of report destinations (mailto: or https: URLs)
    :param msg: A descriptive message printed before the list of destinations
    :param dests: the list of report destinations
    """
    print(msg, ":", len(dests), "recipients: ", dests)


def tlsrptctl_status_main():
    """
    The main sub program handling the 'status' command
    """
    pospars = {}
    options = config.ignore_other_options(tlsrpt.options_reportd,
                                          ['dbname'])
    (configvars, params, sources, warnings) = tlsrpt.options_from_cmd_env_cfg(options,
                                                                              tlsrpt.TLSRPTReportd.DEFAULT_CONFIG_FILE,
                                                                              tlsrpt.TLSRPTReportd.CONFIG_SECTION,
                                                                              tlsrpt.TLSRPTReportd.ENVIRONMENT_PREFIX,
                                                                              pospars)
    cfg = ConfigTlsrptctlStatus(**configvars)
    con = sqlite3.connect("file:///" + cfg.dbname, uri=True)
    cursor = con.cursor()
    reportd_status(cursor, "Fetchjobs", "SELECT day, status, count(*) AS cnt FROM fetchjobs")
    reportd_status(cursor, "Reports", "SELECT day, status, count(*) AS cnt FROM reportdata")
    reportd_status(cursor, "Destinations", "SELECT reports.day, destinations.status, count(*) AS cnt "
                                           "FROM destinations LEFT JOIN reports ON destinations.d_r_id=reports.r_id")
    exit(0)

def reportd_status(cursor:sqlite3.Cursor, headertext: str, query: str):
    """
    Print a reportd status section
    :param cursor: the SQLite cursor to be used for teh query
    :param headertext: header text describing the status information to be shown
    :param query: the query providing the status information
    """
    cursor.execute(query)
    alldata = cursor.fetchall()
    print("### ", headertext, " ###")
    for row in alldata:
        print(row[0], " ", row[1], " ", row[2])
    print()


def tlsrptctl_maptest_main():
    """
    The main sub program handling the 'maptest' command
    """
    pospars = {
        "domain": {"type": str, "nargs": 1, "help": "Domain used to test the tlsrpt_record_map"},
        "tlsrpt_record": {"type": str, "nargs": 1, "help": "TLSRPT DNS record used to test all maps"},
    }

    options = config.ignore_other_options(tlsrpt.options_reportd,
                                          ['tlsrpt_record_map', 'mail_destination_map', 'http_upload_map'])
    (configvars, params, sources, warnings) = tlsrpt.options_from_cmd_env_cfg(options,
                                                                              tlsrpt.TLSRPTReportd.DEFAULT_CONFIG_FILE,
                                                                              tlsrpt.TLSRPTReportd.CONFIG_SECTION,
                                                                              tlsrpt.TLSRPTReportd.ENVIRONMENT_PREFIX,
                                                                              pospars)
    cfg = ConfigTlsrptctlMaptest(**configvars)
    domain = params["domain"][0]
    tlsrpt_record = params["tlsrpt_record"][0]
    print("Domain:", domain)
    print("Record:", tlsrpt_record)
    dests = utility.parse_tlsrpt_record(tlsrpt_record)
    destination_map = mapping.DestinationMap()
    destination_map.read_from_files(cfg.tlsrpt_record_map,
                                    cfg.mail_destination_map,
                                    cfg.http_upload_map)

    handlers = [logging.StreamHandler()]
    logging.basicConfig(level=5, handlers=handlers)
    logger=logging.getLogger()
    show_report_destinations("Initial recipients before mapping", dests)
    dests = destination_map.map_destination(domain, dests, logger)
    show_report_destinations("Resulting recipients after mapping", dests)
    exit(0)

def tlsrptctl_main():
    """
    The main program
    """
    if len(sys.argv)>1:
        if sys.argv[1] == "maptest":
            sys.argv.pop(1)
            tlsrptctl_maptest_main()
        elif sys.argv[1] == "status":
            sys.argv.pop(1)
            tlsrptctl_status_main()
        else:
            print("Unknown command", sys.argv[1])
            exit(1)
    else:
        print("Usage: tlsrptctl [COMMAND] [OPTIONS...]")
        print()
        print("Supported commands:")
        print("  maptest  Test the destination maps for a domain and its TLSRPT record")
        print("  status   Show the status of tlsrpt-reportd")


if __name__ == "__main__":
    tlsrptctl_main()
