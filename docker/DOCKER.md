# TLSRPT reporting in a Container

## Build

```sh
git clone https://github.com/sys4/tlsrpt-reporter.git
cd tlsrpt-reporter/
docker-compose build
```

## Running

The container may run in two different modes selected by env[MODE].
By default, if env[MODE] is unset, a shell is executed.

## Running the collectd

This mode is active if env[MODE] is set to `collectd`.

The collectd MUST run near the MTA. Communication between a MTA and `tlsrpt-collectd`
happen over a unix domain socket created by `tlsrpt-collectd`

```sh
docker-compose up -d tlsrpt-collectd
```

The container uses two volumes. One with the socket exposed to an MTA and a
second one for persistent storage of database files.

Recommended names to the volumes are `tlsrpt-data` and `tlsrpt-socket`. The
volumes are mounted writable as `/tlsrpt-data` and `/tlsrpt-socket` inside a
container.

The following environment variables are relevant:

* `TLSRPT_COLLECTD_DAILY_ROLLOVER_SCRIPT`

  default: `<empty>`

  Set a scriptname to transfer the collectd database to an other host running
  a central `tlsrpt-reportd`-instance. The container provides `/usr/local/bin/daily_rollover_script`
  to do the transfer using `curl`. See [MULTI_COLLECTOR_REPORTING.md](MULTI_COLLECTOR_REPORTING.md)
  for details.

## Running the reportd

This mode is active if env[MODE] is set to `reportd`.

```sh
docker-compose up -d tlsrpt-reportd
```

The container uses one volume for persistent storage of database files.

Recommended name for the volume is `tlsrpt-data`. The volume is mounted
writable as `/tlsrpt-data` inside the container.

The same volume `tlsrpt-data` can be shared between one `tlsrpt-collectd` and
one `tlsrpt-reportd`.

The following environment settings are required:

* `SSMTP_MAILHUB`

  The host to send mail to, in the form _host_ | _IPv4_addr_ _[: port]_.
  The default port is 25. Support for IPv6 addresses depend on your ssmtp
  version)

* `TLSRPT_REPORTD_CONTACT_INFO`

* `TLSRPT_REPORTD_ORGANIZATION_NAME`

* `TLSRPT_REPORTD_SENDER_ADDRESS`

## Limitations

The container are designed to run as __one instance__. Running many "collectd"
or "reportd" container parallel is not supported.

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
