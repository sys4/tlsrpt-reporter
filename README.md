# tlsrpt-reporter

tlsrpt-reporter is a TLSRPT reporting service for SMTP TLS Reporting as defined
in [RFC 8460](https://www.rfc-editor.org/rfc/rfc8460). It receives TLSRPT
datagrams from a MTA, collects them, creates a report in conformance with the
TLSRPT [Reporting Schema](https://www.rfc-editor.org/rfc/rfc8460#section-4) and
finally delivers the report either via `SMTP`, indirectly by submitting it to a
local MTA which ultimately will be responsible for delivering the report, or
directly via `HTTP POST`.


## Application Architecture

Mail platform architectures range from single all-in one servers to multi-server
deployments with different server groups handling dedicated tasks. The TLSRPT
reporting service's application architecture consists of three different
programs which allow to provide TLSRPT reporting in simple but also in complex
mail service architectures.

- `tlsrpt-collectd` receives and collects TLSRPT datagrams from a MTA and
  stores them locally in a sqlite database.
- `tlsrpt-fetcher` fetches TLSRPT datagrams collected by `tlsrpt-collectd`
  directly or over the network via `SSH` and aggregates them into a single
  database.
- `tlsrpt-reportd` generates a TLSRPT report from the data provided by
  `tlsrpt-fetcher` and submits the report.


## Installation

The following distributions provide packages for the TLSRPT reporting service:

[![Packaging status](https://repology.org/badge/vertical-allrepos/tlsrpt-reporter.svg)](https://repology.org/project/tlsrpt-reporter/versions)

## Development

### How to setup the virtual environment for Python

The TLSRPT Reporting Service has been written in Python. Setup a virtual
environment like this:

Clone this repository and chdir into to the root directory of the repository:

```
git clone https://github.com/sys4/tlsrpt-reporter.git
cd tlsrpt-reporter
```

Create the new virtual `venv` environment using the following command:

```
python3 -m venv venv
```

After this initial step there will be a new `venv` directory within the `tlsrpt-reporter`
directory containing all the file required to start and run the virtual
environment. Activate the environment by typing this shell command:

```
source venv/bin/activate
```

This should change the shell prompt, you should now see a `(venv)` in front of
the shell prompt. It will look like this as long as the venv is active.

Finally you need to install additional software within the virtual environment
in order to develop and test:

```
python -m pip install ".[test]"
```

This will satisfy the dependencies of the `tlsrpt-reporter` package and it will install
testing tools (e.g. [tox](https://pypi.org/project/tox/)) required to run
automated tests.


#### Unit Testing

In order to run the unit tests manually on the console, first activate the
virtual environment. Then run the tests like this:

```
$ source venv/bin/activate
(venv) $ python -m unittest discover

.
----------------------------------------------------------------------
Ran 1 test in 0.000s

OK
```


## About the project

The tlsrpt-reporter project is part of a joint effort between the [Postfix
project](https://www.postfix.org), namely Wietse Venema who co-designed and
implemented TLSRPT with the help of
[libtlsrpt](https://github.com/sys4/libtlsrpt) into Postfix, and
[sys4](https://sys4.de), who sponsored the project and whose team has put love
and efforts into tlsrpt-reporter and
[libtlsrpt](https://github.com/sys4/libtlsrpt) to make this happen.

We want secure communications and we want people to feel free to communicate
whatever they want to about on the Internet. TLSRPT provides the reporting to
create visibilty about issues regarding secure communications. Use it! It's
[free](LICENSE).

Start a discussion or create a ticket on GitHub if you have specific questions
about the software provided by the project and / or join the
[TLSRPT mailing list](https://list.sys4.de/postorius/lists/tlsrpt.list.sys4.de/)
for general discussions on TLSRPT but also about this project.

