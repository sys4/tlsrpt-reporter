# running multiple collector and one central reporter

A larger organization may want to collect TLSRPT data on many MTA hosts and
collect these data on one central reporting instance. This document describes
the setup.

```text
      MTA 1                    MTA 2               ...              MTA n

        |                        |                                    |
        v                        v                                    v

 tlsrpt-collectd 1        tlsrpt-collectd 2        ...        tlsrpt-collectd n  

        |                        |                                    |
        |                        v                                    |
        |                                                             |
        ----------->  webserver's upload directory <-------------------

                                 ^
                                 |   read/write
                                 v

                      central tlsrpt-reportd
```

Each `tlsrpt-collectd` instance has to transfer it's database to the central
`tlsrpt-reportd`.
This can be enabled by setting the environment variable
`TLSRPT_COLLECTD_DAILY_ROLLOVER_SCRIPT` with a path to a script on any
`tlsrpt-collectd` instance.

The provided script `/usr/local/bin/daily_rollover_script` transfer each
database using `curl` to a webserver.

The Script use the following environment variables:

* `ROLLOVER_UPLOAD_URI`

  default: `none`

  example: `https://tlsrpt-collecd.example/upload/`

  This variable MUST be provided and contain an URI.

* `ROLLOVER_UPLOAD_SUBDIR`

  default: if the optional variable is unset, the output of `hostname -f` is
           used

  The value is appended to `${ROLLOVER_UPLOAD_URI}` to form a upload URL uniq
  to an `tlsrpt-collectd` instance

* `ROLLOVER_CURL_ARGS`

  default: if the optional variable is unset, `--retry 3 --no-keep-alive` is
           used

  The value MUST contain any number of arguments understood by your `curl`
  version

  example: `--config /path/to/curl.config`

## setting up a webserver

This section describe a configuration for a `nginx` or `freenginx` webserver.

```text
server {
  listen            ...
  server_name       ...
  tls configuration ...

  location /upload {
    root
    client_body_temp_path	/upload/.client_body_temp_path;
    client_max_body_size        10M;   adjust to the size of your databases
    dav_access                  group:rw all:rw;
    dav_methods                 PUT;

    # poor man's access control
    # step 1: all requests exept PUT are denied
    limit_except PUT {
      deny all;
    }

    # step 2: allow PUT for selected tlsrpt-collectd
    allow 192.0.2.1;    # IPv4 address of `tlsrpt-collectd 1
    allow 2001:db0::2;  # IPv6 address of `tlsrpt-collectd 2
    deny  all;
  }

  location /upload/.client_body_temp_path {
    deny  all;
  }

  # other settings
}
```
