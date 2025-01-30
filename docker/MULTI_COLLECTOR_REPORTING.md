# running multiple collector and one central reporter

Larger organization may want to collect TLSRPT data on many MTA hosts and
collect these data on a centralized reporting instance.
This document describes the setup.

```text
       MTA 1                    MTA 2            ...           MTA n

         |                        |                              |
         v                        v                              v

  tlsrpt-collectd 1        tlsrpt-collectd 2     ...     tlsrpt-collectd 1  

         |                        |                              |
         |                        v                              |
         |                                                       |
         ----------->  webserver's upload directory <-------------

                                  ^
                                  | read/write
                                  v

                         central tlsrpt-reportd
```

Each `tlsrpt-collectd` instance has to transfer it's database to the central
`tlsrpt-reportd`.
This can be enabled by setting the environment variable
`TLSRPT_COLLECTD_DAILY_ROLLOVER_SCRIPT` with a path to a script on any
`tlsrpt-collectd` instance.

There is a script `/usr/local/bin/daily_rollover_script` available that
transfer each database using `curl` to a webserver.
