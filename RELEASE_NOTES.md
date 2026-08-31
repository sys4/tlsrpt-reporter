# tlsrpt-reporter 0.6.0

Released: 2026-08-31

## Highlights

The 0.6.0 release of tlsrpt-reporter allows for fine-granular modification of report destinations.

## Changes
See [CHANGELOG.md](./CHANGELOG.md).

## Upgrade notes

Existing configurations will continue to work.
However, some new options cannot be used along with some debug options:
 - the existing `debug_send_file_dest` option cannot be used with the new `tlsrpt_record_map` option, use `. APPEND directory:/path/to/dir/` in the map file for a similar effect
 - the existing `debug_send_http_dest` option cannot be used with the new `http_upload_map` option, use `. REPLACE` in the map file for a similar effect
 - the existing `debug_send_mail_dest` option cannot be used with the new `mail_destination_map` option, use `. REPLACE` in the map file for a similar effect


## Artifacts

- `tlsrpt-reporter-0.6.0.tar.gz`     — source distribution
- `tlsrpt-reporter-0.6.0-py3-none-any.whl` — Python wheel
- `tlsrpt-reporter-0.6.0.tar.gz.asc` — detached PGP signature
- `SHA256SUMS`                 — checksums of all artifacts

## Verification
```sh
gpg --verify tlsrpt-reporter-0.6.0.tar.gz.asc tlsrpt-reporter-0.6.0.tar.gz
sha256sum -c SHA256SUMS
```
