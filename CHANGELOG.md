All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.6.0] - 2026-08-31 - second public release

### Added
- Release notes file


## [0.6.0rc2] - 2026-08-08

### Fixed
- Issue #64: Check tlsrpt-reportd parameters for valid minimum values
- Issue #63: Fix tox action running inside the GitHub actions framework
- Issue #62: Allow old fetcher jobs to succeed when something was stuck over a daily rollover
- Issue #60: Added missing python module tlsrpt_reporter.tlsrptctl
- Issue #59: Add tlsrptctl tool to installed project scripts
- Issue #58: Duration constructor did reset start to None after it was initialized to the current time

### Changed
- Reduce loglevel for sleep cycle messages in loop


## [0.6.0rc1] - 2026-05-22

### Fixed
- Issue #45: Check fetcher configuration on start-up for early detection of configuration problems by doing test runs 
- Issue #43: Initializing a new collectd.sqlite database on a fresh install now also creates collectd.sqlite.yesterday to avoid errors in reportd
- Catch problems when database rollover failed
- Issue #54: crash on unexpected data when TLSRPT DNS record is lacking "mailto:"

### Added
- New configuration options "tlsrpt_record_map", "mail_destination_map" and "http_upload_map" to selectively modify report destinations
- New tool "tlsrptctl" to show status of "tlsrpt-reportd" and to test the new map-options
- Adder stack trace to logging of unexpected exceptions to allow for better bug reports
- Added support for numeric log levels in configuration


## [0.5.0] - 2025-02-22 - first public release

### Fixed
- docs: fixed typo in the filedaemon service name [PR #2028]
- Renamed package to tlsrpt_reporter
- Improved robustness in case of malformed report destinations
- Separate handling of setup errors and runtime errors for reportd
- Improved error handling: Added typenames when logging generic exceptions   
- Catch all errors when fetcher run fails
- Normalize domain name to avoid sending multiple reports for the same domain in different notations like uppercase vs lowercase.
- fix license statements

### Added
- Log error for datagrams with wrong protocol version

