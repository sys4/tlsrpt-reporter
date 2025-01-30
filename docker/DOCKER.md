# TLSRPT in a Container

## Build

```sh
git glone https://github.com/sys4/tlsrpt-reporter.git
cd tlsrpt-reporter/
docker-compose build
```

## Running

The Container may run in different modes selected by ENV[MODE]
By default, if ENV[MODE] is unset, a shell is executed.

## Running the collectd

This mode is active if ENV[MODE] is set to `collectd`.

The collectd MUST run near the MTA. Communication between a MTA and `tlsrpt-collectd`
happen over a unix domain socket created by `tlsrpt-collectd`

```sh
docker-compose up -d tlsrpt-collectd
```

The Container uses two volumes. One with the socket and a second one persist
the database files.

The following environment variables are relevant:

* `TLSRPT_COLLECTD_DAILY_ROLLOVER_SCRIPT`

  default: `<empty>`

  Set a scriptname to transfer the collectd database to an other host running
  a central `tlsrpt-reportd`-instance. The Container provides `/usr/local/bin/daily_rollover_script`
  to do the transfer using `curl`. See ... for details.

## Running the reportd

This mode is active if ENV[MODE] is set to `reportd`.

```sh
docker-compose up -d tlsrpt-reportd
```

The Container uses one volume to persist database files. Also, the following
environment settings are required:

* `SSMTP_MAILHUB`

* `TLSRPT_REPORTD_CONTACT_INFO`

* `TLSRPT_REPORTD_ORGANIZATION_NAME`

* `TLSRPT_REPORTD_SENDER_ADDRESS`

## Debugging

The image contains the [Debian package `sqlite3`](https://packages.debian.org/stable/sqlite3)
for debugging purposes. It SHOULD be removed in a production grade environment.

For example, use the following command to dump the
collectd' database:

```sh
echo .dump | sqlite3 /tlsrpt-data/collectd.sqlite
```

The image also contains the  [Debian package `man-db`](https://packages.debian.org/stable/man-db)
and some manpages. This SHOULD also be removed in a production grade
environment.
