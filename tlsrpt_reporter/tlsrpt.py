#
#    Copyright (C) 2024-2025 sys4 AG
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
import email.message
import email.utils
import gzip
import json
import logging
import random
from abc import ABCMeta, abstractmethod
import os
from pathlib import Path
from selectors import DefaultSelector, EVENT_READ
import shutil
import signal
import socket
import subprocess
import sys
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
import shlex
from enum import Enum, unique

logger = logging.getLogger(__name__)

from tlsrpt_reporter.utility import *
from tlsrpt_reporter.config import options_from_cmd_env_cfg
from tlsrpt_reporter import randpool
from tlsrpt_reporter import plugins

# Constants
DB_Purpose_Suffix = "-devel-2024-10-28"
TLSRPT_FETCHER_VERSION_STRING_V1 = "TLSRPT FETCHER v1devel-c domain list"
TLSRPT_TIMEFORMAT = "%Y-%m-%d %H:%M:%S"
TLSRPT_MAX_READ_FETCHER = 16*1024*1024
TLSRPT_MAX_READ_COLLECTD = 16*1024*1024

# Exit codes
EXIT_USAGE = 2  # argparse default
EXIT_DB_SETUP_FAILURE = 3
EXIT_WRONG_DB_VERSION = 4
EXIT_SHUTDOWN_SOCKETCLOSE = 5
EXIT_SHUTDOWN_COLLECTDPLUGIN = 6
EXIT_SOCKET = 7
EXIT_OTHER = 8


@unique
class DeliveryResult(Enum):
    """
    Results for report delivery
    """
    SUCCEEDED = 1
    TRYAGAIN = 2
    UNKNOWNRUA = 3


@unique
class RolloverReason(Enum):
    """
    Reasons for database rollover
    """
    MIDNIGHT = 1
    INITIALIZE = 2
    MANUALLYINDUCED = 3


# Keyboard interrupt and signal handling
interrupt_read, interrupt_write = socket.socketpair()


def signalhandler(signum, frame):
    """
    Signal handler to intercept keyboard interrupt and other termination signals
    :param signum: signal number
    :param frame: unused
    """
    interrupt_write.send(bytes([signum]))


def setup_daemon_signalhandlers():
    """
    Setup signalhandlers to properly shutdown daemons on interrupt
    """
    signal.signal(signal.SIGINT, signalhandler)
    signal.signal(signal.SIGTERM, signalhandler)
    try:  # SIGUSR2 does not exist on all platforms
        signal.signal(signal.SIGUSR2, signalhandler)  # only used for development to trigger day roll-over
    except AttributeError:
        pass


ConfigCollectd = collections.namedtuple("ConfigCollectd",
                                        ['storage',
                                         'socketname',
                                         'socketuser',
                                         'socketgroup',
                                         'socketmode',
                                         'sockettimeout',
                                         'max_uncommited_datagrams',
                                         'retry_commit_datagram_count',
                                         'pidfilename',
                                         'logfilename',
                                         'log_level',
                                         'daily_rollover_script',
                                         'dump_path_for_invalid_datagram'])


# Available command line options for the collectd
options_collectd = {
    "storage": {"type": str, "default": "",
                "help": "Storage backend, multiple backends separated by comma"},
    "socketname": {"type": str, "default": "", "help": "Name of the unix domain socket to receive data"},
    "socketuser": {"type": str, "default": "", "help": "User owning the unix domain socket to receive data"},
    "socketgroup": {"type": str, "default": "", "help": "Group of the unix domain socket to receive data"},
    "socketmode": {"type": str, "default": "", "help": "Permissions of the unix domain in octal, eg 0220"},
    "sockettimeout": {"type": int, "default": 5, "help": "Read timeout for the socket"},
    "max_uncommited_datagrams": {"type": int, "default": 1000,
                                 "help": "Commit after that many datagrams were received"},
    "retry_commit_datagram_count": {"type": int, "default": 1000,
                                    "help": "Retry commit after that many datagrams more were received"},
    "pidfilename": {"type": str, "default": "", "help": "PID file name for collectd"},
    "logfilename": {"type": str, "default": "", "help": "Log file name for collectd"},
    "log_level": {"type": str, "default": "warn", "help": "Choose log level: debug, info, warning, error, critical"},
    "daily_rollover_script": {"type": str, "default": "", "help": "Hook script to run after day has changed"},
    "dump_path_for_invalid_datagram": {"type": str, "default": "", "help": "Filename to save an invalid datagram"},
}


ConfigFetcher = collections.namedtuple("ConfigFetcher",
                                       ['storage',
                                        'logfilename',
                                        'log_level',
                                        ])


# Available command line options for the fetcher
options_fetcher = {
    "storage": {"type": str, "default": "",
                "help": "Storage backend, multiple backends separated by comma. "
                        "Note: only the first storage will be used to fetch data from!"},
    "logfilename": {"type": str, "default": "", "help": "Log file name for fetcher"},
    "log_level": {"type": str, "default": "warn", "help": "Choose log level: debug, info, warning, error, critical"},
}


# Positional parameters for the fetcher
pospars_fetcher = {
    "day": {"type": str, "nargs": 1, "help": "Day to fetch data for"},
    "domain": {"type": str, "nargs": "?", "help": "Domain to fetch data for, if omitted fetch list of domains"},
}


ConfigReportd = collections.namedtuple("ConfigReportd",
                                        ['logfilename',
                                         'pidfilename',
                                         'log_level',
                                         'debug_db',
                                         'debug_send_mail_dest',
                                         'debug_send_http_dest',
                                         'debug_send_file_dest',
                                         'dbname',
                                         'keep_days',
                                         'fetchers',
                                         'organization_name',
                                         'contact_info',
                                         'sender_address',
                                         'compression_level',
                                         'http_script',
                                         'http_timeout',
                                         'sendmail_script',
                                         'sendmail_timeout',
                                         'spread_out_delivery',
                                         'interval_main_loop',
                                         'max_collectd_timeout',
                                         'max_collectd_timediff',
                                         'max_retries_delivery',
                                         'min_wait_delivery',
                                         'max_wait_delivery',
                                         'max_retries_domainlist',
                                         'min_wait_domainlist',
                                         'max_wait_domainlist',
                                         'max_retries_domaindetails',
                                         'min_wait_domaindetails',
                                         'max_wait_domaindetails'])


# Available command line options for the reportd
options_reportd = {
    "pidfilename": {"type": str, "default": "", "help": "PID file name for reportd"},
    "logfilename": {"type": str, "default": "", "help": "Log file name for reportd"},
    "log_level": {"type": str, "default": "warn", "help": "Log level"},
    "debug_db": {"type": int, "default": 0, "help": "Enable database debugging"},
    "keep_days": {"type": int, "default": 10, "help": "Days to keep old data"},
    "debug_send_mail_dest": {"type": str, "default": "", "help": "Send all mail reports to this addres instead"},
    "debug_send_http_dest": {"type": str, "default": "", "help": "Post all mail reports to this server instead"},
    "debug_send_file_dest": {"type": str, "default": "",
                             "help": "Save all mail reports to this directory additionally"},
    "dbname": {"type": str, "default": "", "help": "Name of database file"},
    "fetchers": {"type": str, "default": "",
                 "help": "Comma-separated list of fetchers to collect data"},
    "organization_name": {"type": str, "default": "",
                          "help": "The name of the organization sending out the TLSRPT reports"},
    "contact_info": {"type": str, "default": "", "help": "The contact information of the sending organization"},
    "sender_address": {"type": str, "default": "", "help": "The From: address to send the report email from"},
    "compression_level": {"type": int, "default": -1, "help": "zlib compression level used to create reports"},
    "http_script": {"type": str,
                    "default": "curl --silent --header 'Content-Type: application/tlsrpt+gzip' --data-binary @-",
                    "help": "HTTP upload script"},
    "http_timeout": {"type": int, "default": 10, "help": "Timeout for HTTPS uploads"},
    "sendmail_script": {"type": str, "default": "sendmail -i -t", "help": "sendmail script"},
    "sendmail_timeout": {"type": int, "default": 10, "help": "Timeout for sendmail script"},
    "spread_out_delivery": {"type": int, "default": 36000,
                            "help": "Time range in seconds to spread out report delivery"},
    "interval_main_loop": {"type": int, "default": 300, "help": "Maximum sleep interval in main loop"},
    "max_collectd_timeout": {"type": int, "default": 10, "help": "Maximum expected collectd timeout"},
    "max_collectd_timediff": {"type": int, "default": 10, "help": "Maximum expected collectd time difference"},
    "max_retries_delivery": {"type": int, "default": 5, "help": "Maximum attempts to deliver a report"},
    "min_wait_delivery": {"type": int, "default": 300, "help": "Minimum time in seconds between two delivery attempts"},
    "max_wait_delivery": {"type": int, "default": 1800,
                          "help": "Maximum time in seconds between two delivery attempts"},
    "max_retries_domainlist": {"type": int, "default": 5, "help": "Maximum attempts to fetch the list of domains"},
    "min_wait_domainlist": {"type": int, "default": 30,
                            "help": "Minimum time in seconds between two domain list fetch attempts"},
    "max_wait_domainlist": {"type": int, "default": 300,
                            "help": "Maximum time in seconds between two domain list fetch attempts"},
    "max_retries_domaindetails": {"type": int, "default": 5, "help": "Maximum attempts to fetch domain details"},
    "min_wait_domaindetails": {"type": int, "default": 30,
                               "help": "Minimum time in seconds between two domain detail fetch attempts"},
    "max_wait_domaindetails": {"type": int, "default": 300,
                               "help": "Maximum time in seconds between two domain detail fetch attempts"}
}


def setup_logging(filename, level, component_name):
    handlers = [logging.StreamHandler()]
    if filename != "":
        handlers.append(logging.FileHandler(filename))
    logging.basicConfig(format="%(asctime)s " + component_name + " %(levelname)s %(module)s %(lineno)s : %(message)s",
                        level=logging.NOTSET, handlers=handlers)
    numeric_level = getattr(logging, level.upper(), None)
    if not isinstance(numeric_level, int):
        raise ValueError("Invalid log level: %s" % level)
    logger.setLevel(numeric_level)


class EmailReport(email.message.EmailMessage):
    """
    Extension of EmailMessage with get_header method
    """
    def get_header(self, header):
        """
        Lookup an existing header
        :param header: email header to retrieve
        :return: the content of the email header
        """
        for k, v in self._headers:
            if k == header:
                return v
        raise IndexError("Header not found: " + header)


class PidFile:
    """
    PID file context manager
    """
    def __init__(self, filename):
        """
        Create a new PDI file context manager
        :param filename: the name of the pidfile
        """
        self.filename = filename
    def __enter__(self):
        try:
            if self.filename != "":
                fd = open(self.filename, mode="w")
                print(os.getpid(), file=fd)
                fd.close()
        except Exception as e:
            logger.warning("Error while creating pid-file %s: %s", self.filename, e)
    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            if self.filename != "":
                os.remove(self.filename)
        except Exception as e:
            logger.warning("Error while removing pid-file %s: %s", self.filename, e)


class TLSRPTCollectd(metaclass=ABCMeta):
    """
    Abstract base class for TLSRPT collectd implementations
    """
    DEFAULT_CONFIG_FILE = "/etc/tlsrpt/collectd.cfg"
    CONFIG_SECTION = "tlsrpt_collectd"
    ENVIRONMENT_PREFIX = "TLSRPT_COLLECTD_"

    @abstractmethod
    def add_datagram(self, datagram):
        """
        Process a received datagram
        :param datagram: datagram received e.g. from the tlsrpt library
        """
        pass

    @abstractmethod
    def socket_timeout(self):
        """
        Process a timeout on the receiving socket
        """
        pass

    @abstractmethod
    def switch_to_next_day(self, rolloverreason):
        """
        Switch to next day after UTC-midnight
        :param rolloverreason: reason for the database rollover
        """
        pass

    @staticmethod
    def factory(url: str, config: ConfigCollectd):
        cls = plugins.get_plugin("tlsrpt.collectd", url)
        return cls(url, config)


class DummyCollectd(TLSRPTCollectd):
    """
    DummyCollectd only logs received datagrams.
    This is used during development to test support for multiple collectds.
    """

    def __init__(self, url: str, config: ConfigCollectd):
        parsed = urllib.parse.urlparse(urllib.parse.unquote(url))
        if parsed.scheme != "dummy":
            raise Exception(f"DummyCollectd can not be instantiated from '{url}'")
        dolog = (parsed.query == "log")
        self.dolog = dolog

    def switch_to_next_day(self, rolloverreason):
        pass

    def add_datagram(self, datagram):
        if self.dolog:
            logger.info("Dummy collectd got datagram %s", datagram)

    def socket_timeout(self):
        if self.dolog:
            logger.info("Dummy collectd got socket timeout")


class VersionedSQLite(metaclass=ABCMeta):
    """
    Abstract base class for versioned SQLite databases
    """
    def __init__(self, dbname):
        self.dbname = dbname
        logger.debug("Try to open database '%s'", self.dbname)
        self.con = sqlite3.connect("file:///"+self.dbname, uri=True)
        self.cur = self.con.cursor()

    def _setup_database(self):
        """
        Set up the database: Create tables and manage version information
        :return:
        """
        try:
            ddl = self._ddl()
            for ddlstatement in ddl:
                logger.debug("DDL %s", ddlstatement)
                self.cur.execute(ddlstatement)
            self.con.commit()
            logger.info("Database '%s' setup finished", self.dbname)
        except Exception as err:
            logger.error("Database '%s' setup failed: %s", self.dbname, err)
            sys.exit(EXIT_DB_SETUP_FAILURE)

    def _check_database(self) -> bool:
        """
        Tries to run a database query, returns True if database has the correct
        version and works as expected. If the database has wrong database
        version, the whole program execution is terminated.
        """
        try:
            self.cur.execute("SELECT version, installdate, purpose FROM dbversion")
            (version, installdate, purpose) = self.cur.fetchone()
            if purpose != self._db_purpose():
                logger.error("Database has wrong purpose, expected %s but got %s", self._db_purpose(), purpose)
                sys.exit(EXIT_WRONG_DB_VERSION)
            if version != 1:
                logger.error("Database has wrong version, expected 1 but got %s", version)
                sys.exit(EXIT_WRONG_DB_VERSION)
            # test if database is read-write
            try:
                tmp_writetest = "tmp_writetest"
                self.cur.execute("INSERT INTO dbversion(version, installdate, purpose) "
                                 "VALUES(0,strftime('%Y-%m-%d %H-%M-%f','now'),?)", (tmp_writetest,))
                self.cur.execute("DELETE FROM dbversion WHERE version=0 and purpose=?", (tmp_writetest,))
            except Exception as e:
                logger.error("Database error %s: %s", e.__class__.__name__, e)
                sys.exit(EXIT_DB_SETUP_FAILURE)
            return True
        except Exception as err:
            logger.info("Database check failed: %s", err)
            return False

    @abstractmethod
    def _ddl(self):
        """
        Defines the database structure
        :return: an array of DDL statements to create for example the tables and indices
        """
        pass

    @abstractmethod
    def _db_purpose(self):
        """
        Defines the purpose of the database to distinguish it from other databases
        :return: A string defining he database purpose
        """
        pass


class VersionedSQLiteCollectdBase(VersionedSQLite):
    def __init__(self, dbname):
        super().__init__(dbname)
    def _db_purpose(self):
        return "TLSRPT-Collectd-DB" + DB_Purpose_Suffix

    def _ddl(self):
        return ["CREATE TABLE finalresults(day, domain, tlsrptrecord, policy, cntrtotal, cntrfailure, its datetime default CURRENT_TIMESTAMP,"
                "PRIMARY KEY(day, domain, tlsrptrecord, policy))",
                "CREATE TABLE failures(day, domain, tlsrptrecord, policy, reason, cntr, "
                "PRIMARY KEY(day, domain, tlsrptrecord, policy, reason))",
                "CREATE TABLE daystatus(daycomplete, its datetime default CURRENT_TIMESTAMP, PRIMARY KEY(daycomplete))",
                "CREATE TABLE dbversion(version, installdate, purpose)",
                "INSERT INTO dbversion(version, installdate, purpose) "
                " VALUES(1,strftime('%Y-%m-%d %H-%M-%f','now'),'"+self._db_purpose()+"')"]


class TLSRPTCollectdSQLite(TLSRPTCollectd, VersionedSQLiteCollectdBase):
    def __init__(self, url: str, config: ConfigCollectd):
        """
        :url str: URL defining the parameters for this reciever instance
        :type config: ConfigCollectd
        """
        parsed = urllib.parse.urlparse(urllib.parse.unquote(url))
        if parsed.scheme != "sqlite":
            raise Exception(f"SQLiteCollectd can not be instantiated from '{url}'")

        self.cfg = config
        self.url = url
        self.today = tlsrpt_utc_date_now()
        self.uncommitted_datagrams = 0
        self.total_datagrams_read = 0
        super().__init__(parsed.path)
        if self._check_database():
            logger.info("Database %s looks OK", self.dbname)
        else:
            logger.info("Create new database %s", self.dbname)
            self._setup_database()
            self.switch_to_next_day(RolloverReason.INITIALIZE)  # prepare yesterday´s DB as well

        # Settings for flushing to disk
        self.commitEveryN = self.cfg.max_uncommited_datagrams
        self.next_commit = tlsrpt_utc_time_now()

    def switch_to_next_day(self, rolloverreason):
        """
        Switch to next day after UTC-midnight
        :param rolloverreason: reason for the database rollover
        """
        yesterday = tlsrpt_utc_date_yesterday()
        commit_message = "Midnight UTC database rollover"
        if rolloverreason == RolloverReason.MANUALLYINDUCED:
            commit_message = commit_message + " FOR DEVELOPMENT"
        elif rolloverreason == RolloverReason.INITIALIZE:
            commit_message = commit_message + " FOR INITIALIZATION"
        logger.info("Performing %s", commit_message)

        if rolloverreason == RolloverReason.MANUALLYINDUCED:
            self.con.set_trace_callback(print)  # show updates in this development-only if-branch
            self._db_commit(commit_message)
            self.cur.execute("UPDATE finalresults SET day=? WHERE day=?", (yesterday, self.today))
            logger.debug("Updated %d rows in finalresults", self.cur.rowcount)
            self.cur.execute("UPDATE failures SET day=? WHERE day=?", (yesterday, self.today))
            logger.debug("Updated %d rows in failuredetails", self.cur.rowcount)
            self.con.commit()

        self._db_commit(commit_message)
        # check for dangling day status
        self.cur.execute("SELECT daycomplete FROM daystatus")
        alldata = self.cur.fetchall()
        has_dangling_daystatus = False
        for row in alldata:
            has_dangling_daystatus = True
            logger.error("POTENTIAL ROLLOVER PROBLEM! Stale day status detected: %s", row)
            break
        if has_dangling_daystatus:
            self.cur.execute("DELETE FROM daystatus;")
        # set day status
        self.cur.execute("INSERT INTO daystatus (daycomplete)  VALUES(?)", (yesterday, ))
        self.con.commit()
        self.cur.close()
        self.con.close()
        yesterdaydbname = make_yesterday_dbname(self.dbname)
        if os.path.isfile(yesterdaydbname):
            os.remove(yesterdaydbname)
        os.rename(self.dbname, yesterdaydbname)
        # start new day
        self.today = tlsrpt_utc_date_now()
        logger.info("Old database moved to %s, create new database %s", yesterdaydbname, self.dbname)
        self.con = sqlite3.connect("file:///"+self.dbname, uri=True)
        self.cur = self.con.cursor()
        self.total_datagrams_read = 0
        if self.uncommitted_datagrams != 0:
            logger.error("%d uncommitted datagrams during day roll-over", self.uncommitted_datagrams)
            self.uncommitted_datagrams = 0
        self._setup_database()
        # finally start hook script
        script = self.cfg.daily_rollover_script
        if script is not None and script != "":
            try:
                args = script.split()
                args.append(self.url)
                args.append(yesterdaydbname)
                logger.info("Starting daily rollover script '%s'", args)
                subprocess.Popen(args)
            except Exception as e:
                logger.error("Unexpected problem while starting daily rollover script '%s': %s", script, e)

    def _db_commit(self, reason):
        """
        Perform a commit of the sqlite database to write data to disk so it can be accessed by the fetcher
        :param reason: Descriptive string for the logging message
        :return:
        """
        try:
            # adjust next_commit now BEFORE the actual commit might fail!
            # This way we avoid retrying it after each datagram and wasting too much time blocking in timeouts
            self.next_commit = tlsrpt_utc_time_now() + datetime.timedelta(seconds=self.cfg.sockettimeout)
            if self.uncommitted_datagrams == 0:
                return  # do not perform unneeded commits and do not flood debug logs
            self.con.commit()
            logger.debug("%s with %d datagrams (%d total)", reason, self.uncommitted_datagrams,
                         self.total_datagrams_read)
            self.uncommitted_datagrams = 0
        except sqlite3.OperationalError as e:
            logger.error("Failed %s with %d datagrams: %s", reason, self.uncommitted_datagrams, e)

    def timed_commit(self):
        self._db_commit("Database commit due to timeout")

    def commit_after_n_datagrams(self):
        if tlsrpt_utc_time_now() > self.next_commit:
            self._db_commit("Database commit due to overdue")
        if self.uncommitted_datagrams >= self.commitEveryN:
            # a database problem can cause a commit-attempt to hang
            # do not retry after each additional datagram but wait for more data to accumulate before retrying
            if (self.uncommitted_datagrams-self.commitEveryN) % self.cfg.retry_commit_datagram_count == 0:
                self._db_commit("Database commit")

    def _add_policy(self, day, domain, tlsrptrecord, policy):
        """
        Process one of the policies found in the received datagram
        :param day: The day this datagram was received
        :param domain: The domain this report entry will be about
        :param tlsrptrecord: The tlsrpt DNS record
        :param policy: the policy dict
        """
        # Normalize domain name
        normalized_domain = normalize_domain_name(domain)
        if normalized_domain != domain:
            logger.debug("Normalized domain name '%s' to '%s'", domain, normalized_domain)
            domain = normalized_domain
        # Remove unneeded keys from policy before writing to database, keeping needed values
        policy_failed = policy.pop("f")  # boolean defining success or failure as final result
        failures = policy.pop("failure-details", [])  # the failures encountered
        failure_count = policy.pop("t", None)  # number of failures
        if failure_count != len(failures):
            logger.error("Failure count mismatch in received datagram: %d reported versus %d failured details: %s",
                         failure_count, len(failures), json.dumps(failures))
        p = json.dumps(policy)
        self.cur.execute(
            "INSERT INTO finalresults (day, domain, tlsrptrecord, policy, cntrtotal, cntrfailure) VALUES(?,?,?,?,1,?) "
            "ON CONFLICT(day, domain, tlsrptrecord, policy) "
            "DO UPDATE SET cntrtotal=cntrtotal+1, cntrfailure=cntrfailure+?",
            (day, domain, tlsrptrecord, p, policy_failed, policy_failed))

        for f in failures:
            self.cur.execute(
                "INSERT INTO failures (day, domain, tlsrptrecord, policy, reason, cntr) VALUES(?,?,?,?,?,1) "
                "ON CONFLICT(day, domain, tlsrptrecord, policy, reason) "
                "DO UPDATE SET cntr=cntr+1",
                (day, domain, tlsrptrecord, p, json.dumps(f)))

    def _add_policies_from_datagram(self, day, datagram):
        """
        Process the policies found in the received datagram
        :param day: The day this datagram was received
        :param datagram: The received datagram
        """
        if "policies" not in datagram:
            logger.warning("No policies found in datagram: %s", datagram)
            return
        if "dpv" not in datagram:
            logger.debug("No datagram protocol version found in datagram: %s", datagram)
        elif datagram["dpv"] != "1":
            logger.error("Wrong datagram protocol version: Expected '1' but got '%s' in datagram: %s", datagram["dpv"], datagram)
        for policy in datagram["policies"]:
            self._add_policy(day, datagram["d"], datagram["pr"], policy)

    def add_datagram(self, datagram):
        # process the datagram
        datenow = tlsrpt_utc_date_now()
        if self.today != datenow:
            self.switch_to_next_day(RolloverReason.MIDNIGHT)
        self._add_policies_from_datagram(datenow, datagram)
        # database maintenance
        self.uncommitted_datagrams += 1
        self.total_datagrams_read += 1
        self.commit_after_n_datagrams()

    def socket_timeout(self):
        """
        Commit database to disk periodically
        """
        datenow = tlsrpt_utc_date_now()
        if self.today != datenow:
            self.switch_to_next_day(RolloverReason.MIDNIGHT)
        self.timed_commit()


class TLSRPTFetcher(metaclass=ABCMeta):
    """
    Abstract base class for TLSRPT fetcher implementations
    """
    DEFAULT_CONFIG_FILE = "/etc/tlsrpt/fetcher.cfg"
    CONFIG_SECTION = "tlsrpt_fetcher"
    ENVIRONMENT_PREFIX = "TLSRPT_FETCHER_"

    @abstractmethod
    def fetch_domain_list(self, day):
        """
        List domains contained in this collectd database for a specific day
        :param day: The day for which to create a report
        """
        pass

    @abstractmethod
    def fetch_domain_details(self, day, domain):
        """
        Print out report details for a domain on a specific day
        :param day: The day for which to print the report details
        :param domain: The domain for which to print the report details
        """
        pass

    @staticmethod
    def factory(url: str, config: ConfigFetcher):
        if url.startswith("sqlite:"):  # fast path for default implementation
            return TLSRPTFetcherSQLite(url, config)
        cls = plugins.get_plugin("tlsrpt.fetcher", url)
        return cls(url, config)


class TLSRPTFetcherSQLite(TLSRPTFetcher, VersionedSQLiteCollectdBase):
    """
    Fetcher class for SQLite collectd
    """
    def __init__(self, url: str, config: ConfigFetcher):
        """
        :url str: URL defining the parameters for this fetcher instance
        :type config: ConfigFetcher
        """
        parsed = urllib.parse.urlparse(urllib.parse.unquote(url))
        if parsed.scheme != "sqlite":
            raise Exception(f"{self.__class__.__name__} can not be instantiated from '{url}'")

        self.cfg = config
        self.uncommitted_datagrams = 0
        self.total_datagrams_read = 0
        super().__init__(make_yesterday_dbname(parsed.path))
        if self._check_database():
            logger.info("Database %s looks OK", self.dbname)
        else:
            raise Exception(f"DB check failed for database {self.dbname}")

    def fetch_domain_list(self, day):
        """
        List domains contained in this collectd database for a specific day
        :param day: The day for which to create a report
        """
        logger.info("TLSRPT fetcher domain list starting for day %s", day)
        # protocol header line 1: the protocol version
        print(TLSRPT_FETCHER_VERSION_STRING_V1)
        # line 2: current time so fetching can be rescheduled to account for clock offset, or warn about too big delay
        print(tlsrpt_utc_time_now().strftime(TLSRPT_TIMEFORMAT))
        # line 3: available day
        dlcursor = self.con.cursor()
        dlcursor.execute("SELECT daycomplete FROM daystatus")
        alldata = dlcursor.fetchall()
        for row in alldata:
            print(row[0])
            break
        # protocol header finished
        # send domains
        dlcursor.execute("SELECT DISTINCT domain FROM finalresults WHERE day=?", (day,))
        alldata = dlcursor.fetchall()
        dlcursor.close()
        linenumber = 0
        for row in alldata:
            try:
                linenumber += 1
                print(row[0])
            except BrokenPipeError as err:
                logger.warning("Error when writing line %d: %s", linenumber, err)
                return
        # terminate domain list with a single dot
        print(".")

    def fetch_domain_details(self, day, domain):
        """
        Print out report details for a domain on a specific day
        :param day: The day for which to print the report details
        :param domain: The domain for which to print the report details
        """
        logger.info("TLSRPT fetcher domain details starting for day %s and domain %s", day, domain)
        policies = {}
        dlcursor = self.con.cursor()
        dlcursor.execute("SELECT domain, policy, tlsrptrecord, cntrtotal, cntrfailure "
                         "FROM finalresults WHERE day=? AND domain=?",
                         (day, domain))
        for (domain, policy, tlsrptrecord, cntrtotal, cntrfailure) in dlcursor:
            if tlsrptrecord not in policies:  # need to create new dict entry
                policies[tlsrptrecord] = {}
            if policy not in policies[tlsrptrecord]:  # need to create new dict entry
                policies[tlsrptrecord][policy] = {"cntrtotal": 0, "cntrfailure": 0, "failures": {}}
            policies[tlsrptrecord][policy]["cntrtotal"] += cntrtotal
            policies[tlsrptrecord][policy]["cntrfailure"] += cntrfailure

        dlcursor.execute("SELECT tlsrptrecord, policy, reason, cntr FROM failures WHERE day=? AND domain=?",
                         (day, domain))
        for (tlsrptrecord, policy, reason, cntr) in dlcursor:
            if reason not in policies[tlsrptrecord][policy]["failures"]:  # need to create new dict entry
                policies[tlsrptrecord][policy]["failures"][reason] = 0
            policies[tlsrptrecord][policy]["failures"][reason] += cntr
        details = {"d": domain, "policies": policies}
        print(json.dumps(details, indent=4))


class TLSRPTReportdSetupException(Exception):
    pass


class TLSRPTReportd(VersionedSQLite):
    """
    The TLSRPT reportd class
    """

    DEFAULT_CONFIG_FILE = "/etc/tlsrpt/reportd.cfg"
    CONFIG_SECTION = "tlsrpt_reportd"
    ENVIRONMENT_PREFIX = "TLSRPT_REPORTD_"

    def __init__(self, config: ConfigReportd):
        """
        :type config: ConfigReportd
        """
        self.cfg = config
        # Some config sanity checks
        fetchers = self.get_fetchers()
        if self.cfg.fetchers == "":
            raise TLSRPTReportdSetupException("No fetchers setup")
        for fetcher in fetchers:
            if fetcher.strip() == "":
                raise TLSRPTReportdSetupException("Empty fetcher configured")

        # Proceed with startup
        super().__init__(self.cfg.dbname)
        self.curtoupdate = self.con.cursor()
        self.randPoolDelivery = randpool.RandPool(self.cfg.spread_out_delivery)
        self.wakeuptime = tlsrpt_utc_time_now()
        if self._check_database():
            logger.info("Database %s looks OK", self.dbname)
        else:
            logger.info("Create new database %s", self.dbname)
            self._setup_database()
        if self.cfg.debug_db:
            self.con.set_trace_callback(print)

    def _db_purpose(self):
        return "TLSRPT-Reportd-DB" + DB_Purpose_Suffix

    def _ddl(self):
        return ["CREATE TABLE fetchjobs(day, fetcherindex, fetcher, retries, status, nexttry, "
                "its datetime default CURRENT_TIMESTAMP, "
                "PRIMARY KEY(day, fetcherindex))",
                "CREATE TABLE reportdata(day, domain, data, fetcher, fetcherindex, retries, status, nexttry, "
                "its datetime default CURRENT_TIMESTAMP, "
                "PRIMARY KEY(day, domain, fetcher))",
                "CREATE TABLE reports(r_id INTEGER PRIMARY KEY ASC, day, domain, uniqid, tlsrptrecord, report, "
                "its datetime default CURRENT_TIMESTAMP) ",
                "CREATE TABLE destinations(destination, d_r_id INTEGER, retries, status, nexttry, "
                "its datetime default CURRENT_TIMESTAMP, "
                "PRIMARY KEY(destination, d_r_id), "
                "FOREIGN KEY(d_r_id) REFERENCES reports(r_id))",
                "CREATE TABLE dbversion(version, installdate, purpose)",
                "INSERT INTO dbversion(version, installdate, purpose) "
                " VALUES(1,strftime('%Y-%m-%d %H-%M-%f','now'),'"+self._db_purpose()+"')"]

    def get_fetchers(self):
        """
        Parse and extract fetchers from config
        :return: An array of fetcher commands
        """
        fetchers = self.cfg.fetchers.split(",")
        return fetchers

    def _wait(self, smin, smax):
        """
        Calculates a random wait period between smin and smax seconds

        :return: seconds to wait before next retry
        """
        return random.randint(smin, smax)

    def wait_domainlist(self):
        """
        Calculates a random wait period between smin and smax seconds

        :return: seconds to wait before next retry
        """
        return self._wait(self.cfg.min_wait_domainlist, self.cfg.max_wait_domainlist)

    def wait_retry_report_delivery(self):
        """
        Calculates a random wait period between smin and smax seconds

        :return: seconds to wait before next retry
        """
        return self._wait(self.cfg.min_wait_delivery, self.cfg.max_wait_delivery)

    def schedule_report_delivery(self):
        secs = self.randPoolDelivery.get()
        return tlsrpt_utc_time_now() + datetime.timedelta(seconds=secs)

    def db_clean_up(self, now):
        """
        Delete old data from database
        :param now: the current UTC time
        """
        limit = self.cfg.keep_days
        cur = self.con.cursor()
        cur.execute("DELETE FROM fetchjobs WHERE julianday(?)-julianday(day)>?", (now, limit))
        d = cur.rowcount
        if d > 0:
            logger.info("Deleted %d old fetchjobs", d)
        cur.execute("DELETE FROM reportdata WHERE julianday(?)-julianday(day)>?", (now, limit))
        d = cur.rowcount
        if d > 0:
            logger.info("Deleted %d old reportdata", d)
        cur.execute("DELETE FROM destinations WHERE d_r_id in (SELECT r_id FROM reports "
                    "WHERE julianday(?)-julianday(day)>?)", (now, limit))
        d = cur.rowcount
        if d > 0:
            logger.info("Deleted %d old destinations", d)
        cur.execute("DELETE FROM reports WHERE julianday(?)-julianday(day)>?", (now, limit))
        d = cur.rowcount
        if d > 0:
            logger.info("Deleted %d old reports", d)

    def check_day(self):
        """
        Check if a new day has started and create jobs for the new day to be processed in the next steps
        """
        logger.debug("Check day")
        cur = self.con.cursor()
        yesterday = tlsrpt_utc_date_yesterday()
        now = tlsrpt_utc_time_now()
        self.db_clean_up(now)
        cur.execute("SELECT * FROM fetchjobs WHERE day=?", (yesterday,))
        row = cur.fetchone()
        if row is not None:  # Jobs already exist
            self.wake_up_in(300)  # wake up every five minutes to check
            return
        # create now fetcher jobs
        fidx = 0
        for fetcher in self.get_fetchers():
            fidx += 1
            cur.execute("INSERT INTO fetchjobs (day, fetcherindex, fetcher, retries, status, nexttry)"
                        "VALUES (?,?,?,0,NULL,?)", (yesterday, fidx, fetcher, now))
        self.con.commit()

    def collect_domains(self):
        """
        Collect domains from the fetchers
        """
        logger.debug("Collect domains")
        curs = self.con.cursor()
        curu = self.con.cursor()
        now = tlsrpt_utc_time_now()
        curs.execute("SELECT day, fetcherindex, fetcher, retries FROM fetchjobs "
                     "WHERE status IS NULL AND nexttry<?", (now,))
        for (day, fetcherindex, fetcher, retries) in curs:
            if self.collect_domains_from(day, fetcher, fetcherindex):
                logger.info("Fetcher %d %s finished in run %d", fetcherindex, fetcher, retries)
                curu.execute("UPDATE fetchjobs SET status='ok' WHERE day=? AND fetcherindex=?", (day, fetcherindex))
            elif retries < self.cfg.max_retries_domainlist:
                logger.warning("Fetcher %d %s failed in run %d", fetcherindex, fetcher, retries)
                curu.execute("UPDATE fetchjobs SET retries=retries+1, nexttry=? WHERE day=? AND fetcherindex=?",
                             (self.wake_up_in(self.wait_domainlist()), day, fetcherindex))
            else:
                logger.warning("Fetcher %d %s timedout after %d retries", fetcherindex, fetcher, retries)
                curu.execute("UPDATE fetchjobs SET status='timedout' WHERE day=? AND fetcherindex=?",
                             (day, fetcherindex))
        self.con.commit()

    def collect_domains_from(self, day, fetcher, fetcherindex):
        """
        Fetch the list of domains from one of the fetchers

        :param day: Day for which to fetch the domain list
        :type fetcher: The fetcher to run
        :type fetcherindex: The fetchers index in the configuration
        :return: True if the job completed successfully, False if a retry is necessary
        """
        logger.debug("Collect domains from %d %s", fetcherindex, fetcher)
        duration = Duration()
        args = fetcher.split()
        args.append(day.__str__())
        try:
            fetcherpipe = subprocess.Popen(args, stdout=subprocess.PIPE)
        except Exception as e:
            logger.error("Could not collect domains from fetcher '%s': %s", fetcher, e.__str__())
            return False
        versionheader = fetcherpipe.stdout.readline().decode('utf-8').rstrip()
        logger.debug("From fetcher %d got version header: %s", fetcherindex, versionheader)
        if versionheader != TLSRPT_FETCHER_VERSION_STRING_V1:
            logger.error("Unsupported protocol version from fetcher %d '%s' :%s", fetcherindex, fetcher, versionheader)
            return False
        # get current time of this collectd
        collectd_time_string = fetcherpipe.stdout.readline().decode('utf-8').rstrip()
        collectd_time = datetime.datetime.strptime(collectd_time_string, TLSRPT_TIMEFORMAT). \
            replace(tzinfo=datetime.timezone.utc)
        reportd_time = tlsrpt_utc_time_now()
        dt = reportd_time - collectd_time
        if abs(dt.total_seconds()) > self.cfg.max_collectd_timediff:
            logger.warning("Collectd time %s and reportd time %s differ more then %s on fetcher %d %s", collectd_time,
                           reportd_time, self.cfg.max_collectd_timediff, fetcherindex, fetcher)
        # Protocol line 3: available day
        available_day = fetcherpipe.stdout.readline().decode('utf-8').rstrip()
        if available_day != day:
            logger.warning("Fetcher not ready %d %s: expected %s but got %s", fetcherindex, fetcher, day,
                           available_day)
            return False
        self.cur.execute("SAVEPOINT domainlist")
        # read the domain list
        result = True
        dc = 0  # domain count
        try:
            while result:
                dom = fetcherpipe.stdout.readline().decode('utf-8').rstrip()
                logger.debug("Got line '%s'", dom)
                if dom == ".":  # end of domain list reached
                    break
                if not dom:  # EOF
                    # this is a warning instead of an error because a remote connection could have been interrupted
                    # and a retry might succeed
                    logger.warning("Unexpected end of domain list")
                    result = False
                    break
                try:
                    self.cur.execute("INSERT INTO reportdata "
                                     "(day, domain, data, fetcherindex, fetcher, retries, status, nexttry) "
                                     "VALUES (?,?,NULL,?,?,0,NULL,?)",
                                     (day, dom, fetcherindex, fetcher, tlsrpt_utc_time_now()))
                    dc += 1
                except sqlite3.IntegrityError as e:
                    logger.warning(e)
        except Exception as e:
            logger.error("Unexpected exception: %s", e.__str__())
            result = False

        if result:
            logger.info("DB-commit for fetcher %d %s", fetcherindex, fetcher)
            self.cur.execute("RELEASE SAVEPOINT domainlist")
            self.con.commit()
        else:
            logger.info("DB-rollback for fetcher %d %s", fetcherindex, fetcher)
            self.cur.execute("ROLLBACK TO SAVEPOINT domainlist")
            self.con.commit()
        duration.add(dc)
        logger.info("Fetching %d domains took %s, %s domains per second", dc, duration.time(), duration.rate())
        return result

    def select_incomplete_days(self, cursor):
        """
        Get days with incomplete fetchjobs from the database
        :param cursor: the DB cursor to use for the query
        :return: the row set of incomplete days
        """
        # select days that are not fully fetched yet for debug loglevel
        cursor.execute("SELECT day FROM fetchjobs WHERE status IS NULL")
        incompletedays = cursor.fetchall()
        return incompletedays

    def fetch_data(self):
        """
        Fetch details for the domains not yet processed
        """
        logger.debug("Fetch data")
        curtofetch = self.con.cursor()
        incompletedays = self.select_incomplete_days(curtofetch)
        if len(incompletedays) != 0:
            logger.debug("The are %d incomplete days: %s", len(incompletedays), incompletedays.__str__())

        # select jobs that are due
        now = tlsrpt_utc_time_now()
        curtofetch.execute(
            "SELECT day, fetcher, fetcherindex, domain FROM reportdata "
            "WHERE data IS NULL AND nexttry<? AND day NOT IN (SELECT day FROM fetchjobs WHERE status IS NULL)",
            (now,))
        for (day, fetcher, fetcherindex, domain) in curtofetch:
            self.fetch_data_from_fetcher_for_domain(day, fetcher, fetcherindex, domain)

    def fetch_data_from_fetcher_for_domain(self, day, fetcher, fetcherindex, dom):
        """
        Fetch details for one domain from one fetcher for a specific day
        :param day: Day for which to fetch the domain details
        :type fetcher: The fetcher to run
        :type fetcherindex: The fetchers index in the configuration
        :param dom: The domain for which to fetch the details
        """
        logger.debug("Fetch data from %d %s for domain %s", fetcherindex, fetcher, dom)
        args = fetcher.split()
        args.append(day.__str__())
        args.append(dom)
        try:
            fetcherpipe = subprocess.Popen(args, stdout=subprocess.PIPE)
        except FileNotFoundError as e:
            logger.error("File not found when trying to run fetcher %s: %s", fetcher, e.__str__())
            return
        alldata = fetcherpipe.stdout.read(TLSRPT_MAX_READ_FETCHER)
        try:
            j = json.loads(alldata)
        except json.JSONDecodeError as e:
            logger.error("Invalid JSON: %s", e.__str__())
            return
        gotdom = j.pop("d")
        if gotdom != dom:
            logger.error("Domain mismatch! Asked for %s but got reply for %s", dom, gotdom)
            return
        data = j.pop("policies")
        self.curtoupdate.execute("UPDATE reportdata SET data=?, status='fetched' "
                                 "WHERE day=? AND fetcherindex=? AND domain=?",
                                 (json.dumps(data), day, fetcherindex, dom))
        self.con.commit()

    def aggregate_report_from_data(self, r, data):
        """
        Aggregate data into report
        :param r: the report into which to aggregate the data
        :param data: the data
        """
        # spolicy is the whole policy as a string, do not to be confused with the "policy-string" inside it
        for spolicy in data:
            tmp = data[spolicy]
            cntrtotal = tmp["cntrtotal"]
            cntrfailure = tmp["cntrfailure"]
            failures = tmp["failures"]
            if spolicy not in r:
                r[spolicy] = {"cntrtotal": 0, "cntrfailure": 0, "failures": {}}
            r[spolicy]["cntrtotal"] += cntrtotal
            r[spolicy]["cntrfailure"] += cntrfailure
            for failure in failures:
                if failure not in r[spolicy]["failures"]:
                    r[spolicy]["failures"][failure] = 0
                r[spolicy]["failures"][failure] += failures[failure]

    def render_report(self, day, dom, tlsrptrecord, data, report):
        """
        Render a report into its final form
        :param day: Day for which to create the report
        :param dom: Domain for which to create the report
        :param tlsrptrecord: TLSRPT DNS record describing the recipients of the report
        :param data: The data from which to create the report
        :param report: The report
        """
        policies = []
        for spolicy in data:
            tmp = data[spolicy]
            cntrtotal = tmp["cntrtotal"]
            cntrfailure = tmp["cntrfailure"]
            failures = tmp["failures"]
            policy = json.loads(spolicy)
            policy_type_names = {1: "tlsa", 2: "sts", 9: "no-policy-found"}  # mapping of policy types
            policy["policy-type"] = policy_type_names[policy["policy-type"]]
            npol = {"summary": {"total-failure-session-count": cntrfailure,
                                "total-successful-session-count": cntrtotal - cntrfailure}}
            npol["policy"] = policy
            npol["failure-details"] = []
            for sfailure in failures:
                fdet = {}
                failure = json.loads(sfailure)
                fdmap = {  # mapping of failure detail short keys from collectd to long keys conforming to RFC8460
                    "a": "additional-information",
                    # "c": "failure-code",  # will be mapped via fcmap below
                    "f": "failure-reason-code",
                    "h": "receiving-mx-helo",
                    "n": "receiving-mx-hostname",
                    "r": "receiving-ip",
                    "s": "sending-mta-ip"
                }

                fcmap = {  # failure code map
                    # maps integer numbers from the internal collectd protocol to result-types defined in RFC8460
                    # TLS negotiation failures
                    201: "starttls-not-supported",
                    202: "certificate-host-mismatch",
                    203: "certificate-not-trusted",
                    204: "certificate-expired",
                    205: "validation-failure",

                    # mta-sts related failures
                    301: "sts-policy-fetch-error",
                    302: "sts-policy-invalid",
                    303: "sts-webpki-invalid",

                    # dns related failures
                    304: "tlsa-invalid",
                    305: "dnssec-invalid",
                    306: "dane-required"
                }
                for k in fdmap:
                    if k in failure:
                        fdet[fdmap[k]] = failure[k]
                rtcode = "c"  # key for numeric result-type code in collectd data
                if rtcode in failure:
                    if failure[rtcode] in fcmap:
                        fdet["result-type"] = fcmap[failure[rtcode]]
                    else:
                        logger.error("Undefined result type code %d", rtcode)
                fdet["failed-session-count"] = failures[sfailure]
                npol["failure-details"].append(fdet)
            policies.append(npol)
        report["policies"] = policies
        cur = self.con.cursor()
        cur.execute("SELECT COUNT(*)+1 FROM reports WHERE day=? AND domain=?", (day, dom))
        uniqid = 0
        for (uniqid,) in cur:
            break
        report["report-id"] = self.report_id(day, uniqid, dom)
        cur.execute("INSERT INTO reports (day, domain, uniqid, report) VALUES(?,?,?,?)",
                    (day, dom, uniqid, json.dumps(report)))
        r_id = cur.lastrowid
        ruas = []
        try:
            ruas = parse_tlsrpt_record(tlsrptrecord)
        except MalformedTlsrptRecordException as e:
            logger.error("Bad TLSRPT record on day %s for domain %s: '%s' => %s", day, dom, tlsrptrecord, e)
        for rua in ruas:
            cur.execute("INSERT INTO destinations (destination, d_r_id, retries, status, nexttry) VALUES(?,?,0,NULL,?)",
                        (rua, r_id, self.schedule_report_delivery()))

    def create_report_for(self, day, dom):
        """
        Creates one or multiple reports for a domain and a specific day.
        Multiple reports can be created if there are different TLSRPT records and therefore different recipients.
        :param day: Day for which to create the reports
        :param dom: Domain for which to create the reports
        """
        logger.debug("Will create report for day %s domain %s", day, dom)
        cur = self.con.cursor()
        cur.execute("SELECT data FROM reportdata WHERE day=? AND domain=?", (day, dom))
        reports = {}
        for (data,) in cur:
            j = json.loads(data)
            for tlsrptrecord in j:
                if tlsrptrecord not in reports:  # need to create new dict entry
                    reports[tlsrptrecord] = {}
                self.aggregate_report_from_data(reports[tlsrptrecord], j[tlsrptrecord])

        for tlsrptrecord in reports:
            rawreport = reports[tlsrptrecord]
            report_start_datetime = tlsrpt_report_start_datetime(day)
            report_end_datetime = tlsrpt_report_end_datetime(day)
            report = {"organization-name": self.cfg.organization_name,
                      "date-range": {
                          "start-datetime": report_start_datetime,
                          "end-datetime": report_end_datetime},
                      "contact-info": self.cfg.contact_info,
                      }
            self.render_report(day, dom, tlsrptrecord, rawreport, report)
        self.con.commit()

    def create_reports(self):
        """
        Create all reports possible, i.e. where no data is pending.
        """
        logger.debug("Create reports")
        curtofetch = self.con.cursor()
        self.curtoupdate = self.con.cursor()
        # Some diagnostic information
        curtofetch.execute("SELECT fetcherindex, domain FROM reportdata WHERE data IS NULL")
        for (fetcherindex, domain) in curtofetch:
            logger.warning("Incomplete data for domain %s by fetcher index %d", domain, fetcherindex)
        # fetch all data keys with complete data and no report yet
        curtofetch.execute("SELECT DISTINCT day, domain FROM reportdata WHERE status='fetched' "
                           "AND NOT (day, domain) IN "
                           "(SELECT day, domain FROM reportdata WHERE status IS NULL) "
                           "AND NOT (day, domain) IN "
                           "(SELECT day, domain FROM reports)")
        for (day, dom) in curtofetch:
            self.create_report_for(day, dom)

    def send_out_report_to_file(self, dom, d_r_id, destination, report, debugdir):
        """
        Save report to a local file for debugging
        :param dom: the domain for which the reported was created
        :param d_r_id: id of the report
        :param destination: the destination the report is to be sent to
        :param report: the report
        :param debugdir: the directory where to create the file
        """
        filename = debugdir + "/testreport-" + dom + "-" + str(d_r_id) + "-" + destination.replace("/", "_") + ".json"
        logger.debug("Would send out report %s to %s, saving to %s", str(d_r_id), destination, filename)
        with open(filename, "w") as file:
            file.write(report)

    def send_out_report_to_mail(self, day, dom, d_r_id, uniqid, destination, zreport) -> DeliveryResult:
        """
        Send out a report via email
        :param day: the day the report was created for
        :param dom: the domain for which the reported was created
        :param d_r_id: id of the report
        :param uniqid: unique id to distinguish multiple reports for the same day and domain
        :param destination: the destination the report is to be sent to
        :param zreport: the compressed report
        :return: DeliveryResult.SUCCEEDED if the smtp_script finished without errors, TRYAGAIN otherwise
        """
        # Check for debug override of destination
        dest = self.cfg.debug_send_mail_dest
        if dest is None or dest == "":
            dest = destination
        else:
            logger.warning("Overriding destination %s to %s", destination, dest)

        # Call send script
        msg = EmailReport()
        msg['Subject'] = self.create_email_subject(dom, self.report_id(day, uniqid, dom))
        msg['From'] = self.cfg.sender_address
        msg['To'] = dest
        msg.add_header("Message-ID", email.utils.make_msgid(domain=msg["From"].groups[0].addresses[0].domain))
        msg.add_header("TLS-Report-Domain", dom)
        msg.add_header("TLS-Report-Submitter", self.cfg.organization_name)
        msg.add_header("TLS-Required", "No")  # use RFC 8689 header

        nr = uniqid
        n = self.create_report_filename(dom, day, nr)
        data = zreport
        intro = "This is an aggregate TLS report from "+self.cfg.organization_name  # .encode("ascii")
        msg.set_content(intro, charset="ascii")
        msg.add_attachment(data, maintype="application", subtype="tlsrpt+gzip", filename=n)

        # Replace MIME multipart header with TLSRPT report header
        h = msg.get_header("Content-Type")
        nh = h.replace("multipart/mixed", "multipart/report; report-type=""tlsrpt""")
        msg.replace_header("Content-Type", nh)

        reportemail = msg.as_string(policy=email.policy.SMTP)
        debugdir = self.cfg.debug_send_file_dest
        if debugdir is not None and debugdir != "":
            self.send_out_report_to_file(dom, d_r_id, "THE_EMAIL_TO_"+destination, reportemail, debugdir)
        try:
            logger.debug("Calling sendmail_script %s", self.cfg.sendmail_script)
            proc = subprocess.Popen(self.cfg.sendmail_script, shell=True, stdin=subprocess.PIPE, close_fds=True)
            proc.stdin.write(msg.as_string(policy=email.policy.SMTP).encode(encoding="utf8"))
            proc.stdin.close()
            mail_command_result = proc.wait(timeout=self.cfg.sendmail_timeout)
            if mail_command_result == 0:
                return DeliveryResult.SUCCEEDED
            else:
                logger.warning(f"Mail command exit code {mail_command_result}")
        except subprocess.TimeoutExpired as e:
            logger.error("Timeout after %d seconds sending report email to %s: %s", self.cfg.sendmail_timeout, dest, e)
        except Exception as e:
            logger.error("Exception %s in sending report email to %s: %s", e.__class__.__name__, dest, e)
        return DeliveryResult.TRYAGAIN

    def send_out_report_to_http(self, destination, zreport) -> DeliveryResult:
        """
        Send out a report via HTTP(S)
        :param destination: the destination the report is to be sent to
        :param zreport: the compressed report
        :return: DeliveryResult.SUCCEEDED if the http_script finished without errors, TRYAGAIN otherwise
        """
        # Check for debug override of destination
        dest = self.cfg.debug_send_http_dest
        if dest is None or dest == "":
            dest = destination
        else:
            logger.warning("Overriding destination %s to %s", destination, dest)

        # Post the report using http_script
        try:
            script = self.cfg.http_script + " " + shlex.quote(dest)
            logger.debug("Calling http_script %s", script)
            proc = subprocess.Popen(script, shell=True, stdin=subprocess.PIPE, close_fds=True)
            proc.stdin.write(zreport)
            proc.stdin.close()
            http_command_result = proc.wait(timeout=self.cfg.http_timeout)
            if http_command_result == 0:
                return DeliveryResult.SUCCEEDED
            else:
                logger.warning(f"HTTP command exit code {http_command_result}")
        except subprocess.TimeoutExpired as e:
            logger.error("Timeout after %d seconds uploading report to %s: %s", self.cfg.http_timeout, dest, e)
        except Exception as e:
            logger.error("Exception %s in uploading report to %s: %s", e.__class__.__name__, dest, e)
        return DeliveryResult.TRYAGAIN

    def send_out_report(self, day, dom, d_r_id, uniqid, destination, report) -> DeliveryResult:
        """
        Send out a report to one destination: HTTP(S) or SMTP.
        If the debugdir option is configured an additional copy is saved to a local file.
        :param day: the day the report was created for
        :param dom: the domain for which the reported was created
        :param d_r_id: id of the report
        :param uniqid: unique id to distinguish multiple reports for the same day and domain
        :param destination: the destination the report is to be sent to
        :param report: the compressed report
        :return: DeliveryResult.SUCCEEDED if the delivery script finished without errors, TRYAGAIN otherwise
        """
        # Dump report as a file for debugging
        debugdir = self.cfg.debug_send_file_dest
        if debugdir is not None and debugdir != "":
            self.send_out_report_to_file(dom, d_r_id, destination, report, debugdir)
        # Zip the report
        zreport = gzip.compress(report.encode("utf-8"), self.cfg.compression_level)
        # Send out the actual report
        if destination.startswith("mailto:"):
            destination = destination[7:]  # remove "mailto:" URL scheme
            return self.send_out_report_to_mail(day, dom, d_r_id, uniqid, destination, zreport)
        elif destination.startswith("https:"):
            return self.send_out_report_to_http(destination, zreport)
        else:
            logger.error("Unknown RUA scheme in report destination '%s'", destination)
            return DeliveryResult.UNKNOWNRUA

    def send_out_reports(self):
        """
        Send out the finished reports.
        """
        now = tlsrpt_utc_time_now()
        logger.debug("Send out reports")
        cur = self.con.cursor()  # cursor for selects
        curu = self.con.cursor()  # cursor for updates
        cur.execute(
            "SELECT destination, d_r_id, uniqid, report, domain, day, retries FROM destinations "
            "LEFT JOIN reports on r_id=d_r_id WHERE destinations.status IS NULL and nexttry<?", (now,))
        for (destination, d_r_id, uniqid, report, dom, day, retries) in cur:
            logger.info("Report delivery %d for domain %s succeeded in run %d", d_r_id, dom, retries)
            deliveryresult = self.send_out_report(day, dom, d_r_id, uniqid, destination, report)
            if deliveryresult == DeliveryResult.SUCCEEDED:
                curu.execute("UPDATE destinations SET status='sent' WHERE destination=? AND d_r_id=?",
                             (destination, d_r_id))
            elif deliveryresult != DeliveryResult.TRYAGAIN:
                curu.execute("UPDATE destinations SET status=? WHERE destination=? AND d_r_id=?",
                             (deliveryresult.name.lower(), destination, d_r_id))
            elif retries < self.cfg.max_retries_delivery:
                logger.warning("Report delivery %d for domain %s failed in run %d", d_r_id, dom, retries)
                curu.execute("UPDATE destinations SET retries=retries+1, nexttry=? WHERE destination=? AND d_r_id=?",
                             (self.wake_up_in(self.wait_retry_report_delivery()), destination, d_r_id))
            else:
                logger.warning("Report delivery %d for domain %s timedout after %d  retries", d_r_id, dom, retries)
                curu.execute("UPDATE destinations SET status='timedout' WHERE destination=? AND d_r_id=?",
                             (destination, d_r_id))
            self.con.commit()

    def wake_up_in(self, secs, force=False):
        """
        Schedule next main loop run in secs seconds
        :param secs: The number of seconds to sleep at most
        :param force: Set this wake up time as an override even if a shorter wake up time is already set
        :return: The new wake up time
        """
        return self.wake_up_at(tlsrpt_utc_time_now() + datetime.timedelta(seconds=secs), force)

    def wake_up_at(self, t, force=False):
        """
        Schedule next main loop run at time t
        :param t: The time to start the next main loop run
        :param force: Set this wake up time as an override even if a shorter wake up time is already set
        :return: The new wake up time
        """
        if self.wakeuptime > t:
            logger.debug("Changing wake up time from %s to %s", self.wakeuptime, t)
            self.wakeuptime = t
        elif force:
            logger.debug("Enforcing wake up time from %s to %s", self.wakeuptime, t)
            self.wakeuptime = t
        else:
            logger.debug("Not changing wake up time from %s to %s", self.wakeuptime, t)
        return t

    def run_loop(self):
        """
        Main loop processing the various jobs and steps.
        """
        sel = DefaultSelector()
        sel.register(interrupt_read, EVENT_READ)
        while True:
            self.wake_up_in(self.cfg.interval_main_loop, True)
            self.check_day()
            self.collect_domains()
            self.fetch_data()
            self.create_reports()
            self.send_out_reports()
            dt = self.wakeuptime - tlsrpt_utc_time_now()
            seconds_to_sleep = dt.total_seconds()
            if seconds_to_sleep >= 0:
                logger.debug("Sleeping for %d seconds", seconds_to_sleep)
            else:
                logger.debug("Skipping sleeping for negative %d seconds", seconds_to_sleep)
            for key, _ in sel.select(timeout=seconds_to_sleep):
                if key.fileobj == interrupt_read:
                    signumb = interrupt_read.recv(1)
                    signum = ord(signumb)
                    logger.info("Caught signal %d, cleaning up", signum)
                    self.con.commit()
                    logger.info("Done")
                    return 0

    def report_id(self, day, report_index, report_domain):
        """
        Creates a report id
        :param day: Day of the report
        :param report_index: Running index of this report in case there might be multiple reports on the same day
        :param report_domain: Domain this report is for
        :return: a report id to be used in the report_id JOSN field and in the email subject
        """
        return tlsrpt_report_start_datetime(day) + "_idx" + str(report_index) + "_" + report_domain

    def create_email_subject(self, dom, report_id):
        return "Report Domain: " + dom + " Submitter: " + self.cfg.organization_name + \
               " Report-ID: <" + str(report_id) + "@" + self.cfg.organization_name + ">"

    def create_report_filename(self, dom, day, nr):
        start = tlsrpt_report_start_timestamp(day)
        end = tlsrpt_report_end_timestamp(day)
        return self.cfg.organization_name + "!" + dom + "!" + str(start) + "!" + str(end) + "!" + str(nr) + ".json.gz"


def log_config_info(logger, configvars, sources, warnings):
    """
    Log all configuration settings
    :param logger: the logger instance to use
    :param configvars: the dict containing the configuration values
    :param sources: the dict containing the sources form where the configuration was set
    :param warnings: the warnings returned by the config parsers
    """
    source_name = {"c": "cmd", "f": "cfg", "e": "env", "d": "def"}
    logger.info("CONFIGURATION with %d settings:", len(configvars))
    for k in configvars.keys():
        logger.info("CONFIG from %s option %s is %s", source_name[sources[k]], k, configvars[k])
    for w in warnings:
        logger.warning(w)


def tlsrpt_collectd_main():
    """
    Contains the main TLSRPT collectd loop. This listens on a socket to
    receive TLSRPT datagrams from the MTA (e.g. Postfix). and writes the
    datagrams to the database.
    """
    setup_daemon_signalhandlers()
    (configvars, params, sources, warnings) = options_from_cmd_env_cfg(options_collectd,
                                                                       TLSRPTCollectd.DEFAULT_CONFIG_FILE,
                                                                       TLSRPTCollectd.CONFIG_SECTION,
                                                                       TLSRPTCollectd.ENVIRONMENT_PREFIX,
                                                                       {})
    config = ConfigCollectd(**configvars)
    setup_logging(config.logfilename, config.log_level, "tlsrpt_collectd")
    log_config_info(logger, configvars, sources, warnings)
    exitcode = EXIT_OTHER
    with PidFile(config.pidfilename):
        try:
            exitcode = tlsrpt_collectd_daemon(config)
        except Exception as e:
            logger.error("Exception %s in tlsrpt_collectd_daemon: %s", e.__class__.__name__, e)
    if exitcode != 0:
        logger.error("process terminates with exit code %s", exitcode)
    else:
        logger.info("process terminates with exit code %s", exitcode)
    exit(exitcode)

def remove_datagram_socket(server_address, when):
    """
    Remove unix domain socket file.
    :param server_address: The name of the unix domain socket to be removed from the filesystem
    :param when: informational string  for logging to disinguish errors during startup from errors during shutdown
    """
    try:
        if os.path.exists(server_address):
            os.unlink(server_address)
    except OSError as err:
        logger.error("Failed to remove existing socket %s during %s: %s", server_address, when, err)

def tlsrpt_collectd_daemon(config: ConfigCollectd):
    """
    Daemon function for collectd to be run after configuration was setup
    :param config: the ConfigCollectd for this daemon
    :return: exitcode to be returned from the process, zero on successful termination
    """
    server_address = config.socketname
    logger.info("TLSRPT collectd starting")
    # Make sure the socket does not already exist
    remove_datagram_socket(server_address, "startup")

    # Create a Unix Domain Socket
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    except Exception as e:
        logger.error("Error %s while creating socket: %s", e.__class__.__name__, e)
        return EXIT_SOCKET

    # Bind the socket to the port
    if server_address is None or server_address == "":
        logger.error("No collectd_socketname configured")
        return EXIT_USAGE
    logger.info("Listening on socket '%s'", server_address)
    try:
        sock.bind(server_address)
        sock.setblocking(False)
    except Exception as e:
        logger.error("Error %s while binding socket: %s", e.__class__.__name__, e)
        return EXIT_SOCKET

    # adjust socket user/group
    kwargs = {}
    kwargs["path"] = server_address
    if config.socketuser is not None and config.socketuser != "":
        kwargs["user"] = config.socketuser
    if config.socketgroup is not None and config.socketgroup != "":
        kwargs["group"] = config.socketgroup
    try:
        if len(kwargs) > 1:  # we have at least one of user and group
            logger.info("Chmoding socket %s", str(kwargs))
            shutil.chown(**kwargs)
    except Exception as e:
        logger.error("Could not chown socket %s: %s", str(kwargs), e)
    # adjust socket permissions
    try:
        if config.socketmode is not None and config.socketmode != "":
            mode = int(config.socketmode, base=8)
            if config.socketmode[0] != '0':
                logger.warning("Config option socketmode '%s' does not look like octal", config.socketmode)
            logger.info("Chmoding socket %s to permissions 0%o (decimal %d)", server_address, mode, mode)
            os.chmod(path=server_address, mode=mode)
    except Exception as e:
        logger.error("Could not chmod socket %s to mode %s: %s", server_address, config.socketmode, e)

    # Multiple collectds to be set-up from configuration
    collectds = []
    for r in config.storage.split(","):
        if r != "":
            collectds.append(TLSRPTCollectd.factory(r, config))
    if len(collectds) == 0:
        logger.error("No collectd storage configured")
        return EXIT_USAGE

    sel = DefaultSelector()
    sel.register(interrupt_read, EVENT_READ)
    sel.register(sock, EVENT_READ)
    while True:
        alldata = None  # clear old data to prevent accidentally processing it twice
        try:
            # Uncomment to test very low throughput
            # time.sleep(1)

            had_data = 0
            for key, _ in sel.select(timeout=config.sockettimeout):
                if key.fileobj == interrupt_read:
                    signumb = interrupt_read.recv(1)
                    signum = ord(signumb)
                    if signum == signal.SIGUSR2:
                        logger.info("Caught signal %d, enforce debug day roll-over for development", signum)
                        for collectd in collectds:
                            collectd.switch_to_next_day(RolloverReason.MANUALLYINDUCED)
                    else:
                        logger.info("Caught signal %d, cleaning up", signum)
                        exitcode = 0
                        try:
                            sock.close()
                            remove_datagram_socket(server_address, "shutdown")
                        except Exception as e:  # catch all exceptions to avoid interrupting shutdown
                            logger.error("Exception %s during shutdown: %s", e.__class__.__name__, e)
                            exitcode = EXIT_SHUTDOWN_SOCKETCLOSE
                        for collectd in collectds:
                            logger.info("Triggering socket timeout on collectd")
                            try:
                                collectd.socket_timeout()
                            except Exception as e:  # catch all exceptions to avoid interrupting shutdown
                                logger.error("Exception %s during shutdown: %s", e.__class__.__name__, e)
                                exitcode = EXIT_SHUTDOWN_COLLECTDPLUGIN
                        logger.info("Done")
                        return exitcode
                if key.fileobj == sock:
                    had_data += 1
                    alldata, srcaddress = sock.recvfrom(TLSRPT_MAX_READ_COLLECTD)
                    j = json.loads(alldata)
                    for collectd in collectds:
                        try:
                            collectd.add_datagram(j)
                        except KeyError as err:
                            logger.error("KeyError %s during processing datagram: %s", str(err), json.dumps(j))
            if had_data == 0:
                for collectd in collectds:
                    collectd.socket_timeout()
        except socket.timeout:
            for collectd in collectds:
                collectd.socket_timeout()
        except OSError as err:
            logger.error("OS-Error: %s", str(err))
            raise
        except UnicodeDecodeError as err:
            logger.error("Malformed utf8 data received: %s", str(err))
            Path(config.dump_path_for_invalid_datagram).write_bytes(alldata)
        except json.decoder.JSONDecodeError as err:
            logger.error("JSON decode error: %s", str(err))
            Path(config.dump_path_for_invalid_datagram).write_text(alldata.decode("utf-8"), encoding="utf-8")
        except sqlite3.OperationalError as err:
            logger.error("Database error: %s", str(err))


def tlsrpt_fetcher_main():
    """
    Runs the fetcher main. The fetcher is used by the TLSRPT-reportd to
    read the database entries that were written by the collectd.
    """
    # TLSRPT-fetcher is tightly coupled to TLSRPT-collectd and uses its config and database
    (configvars, params, sources, warnings) = options_from_cmd_env_cfg(options_fetcher,
                                                                       TLSRPTFetcher.DEFAULT_CONFIG_FILE,
                                                                       TLSRPTFetcher.CONFIG_SECTION,
                                                                       TLSRPTFetcher.ENVIRONMENT_PREFIX,
                                                                       pospars_fetcher)
    config = ConfigFetcher(**configvars)

    setup_logging(config.logfilename, config.log_level, "tlsrpt_fetcher")
    log_config_info(logger, configvars, sources, warnings)

    # Fetcher uses the first configured storage
    # To be consistent with collectd the storage parameter is parsed in the same way, but fetcher ignores
    # and warns about additional storage being configured
    urls = config.storage.split(",")
    url = urls.pop(0)
    for ignored_url in urls:
        logger.warning("Ignoring additional storage: %s", ignored_url)
    try:
        fetcher = TLSRPTFetcher.factory(url, config)
    except Exception as e:
        logger.error("Can not create fetcher from storage URL '%s': %s", url, str(e))
        sys.exit(EXIT_USAGE)
    if len(params["day"]) != 1:
        logger.error("Expected exactly one argument for parameter 'day' but got %s", len(params["day"]))
        sys.exit(EXIT_USAGE)
    day = params["day"][0]
    if day is None or day == "":
        logger.error("Invalid value for parameter 'day': '%s'", day)
        sys.exit(EXIT_USAGE)
    domain = params["domain"]
    if domain is None:
        fetcher.fetch_domain_list(day)
    else:
        fetcher.fetch_domain_details(day, domain)


def tlsrpt_reportd_main():
    """
    Entry point to the reportd main. The reportd is the part that finally
    sends the STMP TLS reports out the endpoints that the other MTA operators
    have published.
    """
    setup_daemon_signalhandlers()
    (configvars, params, sources, warnings) = options_from_cmd_env_cfg(options_reportd,
                                                                       TLSRPTReportd.DEFAULT_CONFIG_FILE,
                                                                       TLSRPTReportd.CONFIG_SECTION,
                                                                       TLSRPTReportd.ENVIRONMENT_PREFIX,
                                                                       {})
    config = ConfigReportd(**configvars)
    setup_logging(config.logfilename, config.log_level, "tlsrpt_reportd")
    log_config_info(logger, configvars, sources, warnings)

    logger.info("TLSRPT reportd starting")

    exitcode = EXIT_OTHER
    reportd = None
    with PidFile(config.pidfilename):
        # Setup
        try:
            reportd = TLSRPTReportd(config)
        except TLSRPTReportdSetupException as e:
            logger.error("Setup error for tlsrpt_reportd_daemon: %s", e)
        except Exception as e:
            logger.error("Exception %s during setup of tlsrpt_reportd_daemon: %s", e.__class__.__name__, e)
        # Run
        try:
            if not reportd is None:
                exitcode = reportd.run_loop()
            else:
                logger.info("Can not run reportd due to setup failure")
        except Exception as e:
            logger.error("Exception %s while running tlsrpt_reportd_daemon: %s", e.__class__.__name__, e)


    if exitcode != 0:
        logger.error("process terminates with exit code %s", exitcode)
    else:
        logger.info("process terminates with exit code %s", exitcode)
    exit(exitcode)


if __name__ == "__main__":
    print("Call tlsrpt fetcher, collectd or reportd instead of this file", file=sys.stderr)
