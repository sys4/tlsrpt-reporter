# running multiple collector and one central reporter

A larger organization may want to collect TLSRPT data on many MTA hosts and
collect these data on one central reporting instance. This document describes
the setup using docker containers.

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

  This variable MUST be provided and contain an URI

* `ROLLOVER_UPLOAD_SUBDIR`

  default: if the optional variable is unset, the output of `hostname -f` is
           used

  The value is appended to `${ROLLOVER_UPLOAD_URI}` to form a upload URL unique
  to an `tlsrpt-collectd` instance

* `ROLLOVER_CURL_ARGS`

  default: if the optional variable is unset, `--retry 3 --no-keep-alive` is
           used

  The value MUST contain any number of arguments understood by your `curl`
  version

  example: `--config /path/to/curl.config`

## setting up a webserver

This section describe a configuration for a `nginx` or `freenginx` webserver.

```yaml
# file: /tmp/docker-compose.yml
services:
  nginx:
    image: nginx
    ports:
    - 8080:8080
    volumes:
    - ./nginx.conf:/etc/nginx/conf.d/nginx.conf:ro
```

```txt
# file: /tmp/nginx.conf
server {
  listen                 8080;

  location /upload {
    alias                /tmp;

    # adjust to the size of your databases
    client_max_body_size 10M;
    dav_access           group:rw all:rw;
    dav_methods          PUT;

    # poor man's access control
    # step 1: all requests exept PUT are denied
    limit_except PUT {
      deny               all;
    }

    # step 2: allow PUT for selected tlsrpt-collectd
    # docker default network space (only for this example)
    allow                172.12.0.0/12;

    # IPv4 address of `tlsrpt-collectd 1
    allow                192.0.2.1;

    # IPv6 address of `tlsrpt-collectd 2
    allow                2001:db0::2;

    # don't forget!
    deny                 all;
  }
}
```

Now start the container and upload a file:

```sh
# docker-compose up -d
# curl --upload-file /etc/issue http://localhost:8080/upload/uploaded_filename
```

The file `/etc/issue` should now exist inside the container:

```sh
# docker-compose exec nginx ls -la /tmp/uploaded_filename
```

On production system, adjust `alias /tmp` to a volume, writable by nginx and
the value of `$ROLLOVER_UPLOAD_URI`. Finally create the nessesary directories
used in `$ROLLOVER_UPLOAD_SUBDIR`. We suggest a docker volume `tlsrpt-data`
mounted at `/tlsrpt-data`

## glue to tlsrpt-reportd

The volume used and writable by `nginx` must also be accessible (with write
access) to a container running `tlsrpt-collectd`. To be used by
`tlsrpt-collectd`, adjust `$TLSRPT_REPORTD_FETCHERS`:

```txt
TLSRPT_REPORTD_FETCHERS = tlsrpt-fetcher --storage sqlite:///tlsrpt-data/upload/tlsrpt-collectd1.example/collectd.sqlite'
```

Repeat the command for any tlsrpt-collectd instance, separated by colons.
Important: even if `daily_rollover_script` upload files named
`collectd.sqlite.yesterday`, `tlsrpt-fetcher` MUST be configured for names
ending without `.yesterday`
