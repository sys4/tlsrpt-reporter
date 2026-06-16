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

import datetime


def remove_prefix(s:str, prefix:str):
    """
    Removes a prefix from a string, helper function for pre-3.9 python
    :param s: the string potentially beginning with a prefix that should be removed
    :param prefix: The prefix to be removed if present
    :return: Result of stripping prefix from s
    """
    if s.startswith(prefix):
        return s[len(prefix):]
    return s


def remove_suffix(s:str, suffix:str):
    """
    Removes a suffix from a string, helper function for pre-3.9 python
    :param s: the string potentially ending in a suffix that should be removed
    :param suffix: The suffix to be removed if present
    :return: Result of stripping suffix from s
    """
    if len(suffix) == 0:  # special case to avoid [:-0] acting like [:0]
        return s
    if s.endswith(suffix):
        return s[:-len(suffix)]
    return s


class MalformedTlsrptRecordException(Exception):
    pass

class MalformedEmailAddressException(Exception):
    pass

def parse_tlsrpt_record(tlsrpt_record):
    """
    Parses a TLSRPT DNS record and extracts the destination URIs
    :param tlsrpt_record: The TLSRPT DNS record to be parsed
    :return: A list of report destinations extracted from the TLSRPT DNS record
    """
    # first split into the main parts: version and RUAs
    mparts = tlsrpt_record.split(";")
    if len(mparts) < 2:
        raise MalformedTlsrptRecordException("Malformed TLSRPT record: No semicolon found")
    if mparts[0] != "v=TLSRPTv1":
        raise MalformedTlsrptRecordException("Unsupported TLSRPT version: " + mparts[0])
    ruapart = mparts[1].strip()
    if not ruapart.startswith("rua="):
        raise MalformedTlsrptRecordException("Malformed TLSRPT record: No rua found")
    ruapart=ruapart[4:]  # remove leading "rua="
    ruas=ruapart.split(",")
    return ruas


def normalize_domain_name(domain: str):
    """
    Normalize a domain name: transform to lower case and remove one single trailing dot
    :param domain: domain name to be normalized
    """
    domain = domain.lower()
    if domain.endswith(".") and not domain.endswith("..") and domain !=".":  # strip one single trailing dot
        domain = domain[:-1]
    return domain

def extract_domain_from_email_address(email: str):
    '''
    Extract the domain part from an email address
    :param email: The email address from which to extract the domain part
    :type email: str
    :return: The domain part of the email address
    :rtype: str
    '''
    parts = email.rsplit('@', 1)
    if len(parts) != 2:
        raise MalformedEmailAddressException("Could not extract domain part from " + email)
    return parts[1]

def make_yesterday_dbname(dbname):
    """
    Create name for the database to store data of the previous day
    :param dbname: name of todays database
    :return: name of yesterdays database
    """
    return dbname+".yesterday"


def tlsrpt_report_start_datetime(day):
    """
    Return start time of report for a specific day.
    :param day:  Day for which to create the start time.
    :return: Timestamp of the report start in the format required by RFC 8460
    """
    return day + "T00:00:00Z"


def tlsrpt_report_end_datetime(day):
    """
    Return end time of report for a specific day.
    :param day:  Day for which to create the end time.
    :return: Timestamp of the report end in the format required by RFC 8460
    """
    return day + "T23:59:59Z"


def tlsrpt_report_start_timestamp(day):
    """
    Return start time of report for a specific day.
    :param day:  Day for which to create the start time.
    :return: Timestamp of the report start as unix timestamp
    """
    day = datetime.datetime.fromisoformat(day)
    day = day.replace(tzinfo=datetime.timezone.utc)
    return int(day.timestamp())


def tlsrpt_report_end_timestamp(day):
    """
    Return timestamp of report for a specific day.
    :param day:  Day for which to create the timestamp.
    :return: Timestamp of the report end as unix timestamp
    """
    start = tlsrpt_report_start_timestamp(day)
    return int(start+24*3600-1)


def tlsrpt_utc_time_now():
    """
    Returns a timezone aware datetime object of the current UTC time.
    """
    return datetime.datetime.now(datetime.timezone.utc)


def tlsrpt_utc_date_now():
    """
    Returns the current date in UTC.
    """
    return tlsrpt_utc_time_now().date()


def tlsrpt_utc_date_yesterday():
    """
    Returns the date of yesterday in UTC.
    """
    ts = tlsrpt_utc_time_now()   # Making sure, ts is timezone-aware and UTC.
    dt = datetime.timedelta(days=-1)
    return (ts + dt).date()


class Duration:
    """
    Time duration and rate measurement class
    """
    def __init__(self):
        self.start()
        self.count = 0

    def start(self):
        self.begin = datetime.datetime.now(datetime.timezone.utc)
        self.begin -= datetime.timedelta(microseconds=1)  # prevent div/0 exception

    def time(self):
        n = datetime.datetime.now(datetime.timezone.utc)
        d = n - self.begin
        return d

    def add(self, n=1):
        self.count += n

    def rate(self):
        return self.count / self.time().total_seconds()
