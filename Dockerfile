FROM debian:bookworm-slim AS build

WORKDIR /tmp

COPY README.md ./
COPY pyproject.toml ./
COPY tlsrpt/ ./tlsrpt/

# hadolint ignore=DL3008,DL4006
RUN    apt-get -y -qq update \
    && DEBIAN_FRONTEND=noninteractive apt-get -y -qq install --no-install-recommends \
         python3-pip \
    && pip3 install \
         --break-system-packages \
         --no-cache-dir \
         --no-deps \
         --no-warn-script-location \
         --root-user-action ignore \
         pyproject.toml \
         . \
    # cleanup unneeded files
    && find /usr/local -type d \( -name 'pyproject_toml*' -o -name '__pycache__' \) -print0 | xargs -0 rm -rf

FROM debian:bookworm-slim

COPY --from=build /usr/local/ /usr/local/
COPY doc/tlsrpt-*.1 /usr/local/share/man/man1/
COPY docker/cmd /cmd
COPY docker/entrypoint /entrypoint
COPY docker/daily_rollover_script /usr/local/bin/

# hadolint ignore=DL3008
RUN apt-get -y -qq update \
    && DEBIAN_FRONTEND=noninteractive apt-get -y -qq install --no-install-recommends \
         ca-certificates \
         curl \
         libpython3-stdlib \
         man-db \
         python3-minimal \
         ssmtp \
         sqlite3 \
    && apt-get -y -qq clean \
    && rm -rf /var/lib/apt/lists/* \
    #
    && chmod 0555 /cmd \
                  /entrypoint \
                  /usr/local/bin/daily_rollover_script \
    #
    # create a unpriveleged user
    && useradd --no-create-home \
               --shell /usr/sbin/nologin \
               --user-group tlsrpt \
    #
    # install some directories
    && install --directory \
               --owner tlsrpt \
               --group tlsrpt \
         /home/tlsrpt/ \
         /tlsrpt-data/ \
         /tlsrpt-socket/ \
    #
    # see https://github.com/sys4/tlsrpt/issues/26
    && chmod 0777 /tlsrpt-socket/ \
    #
    # would be better if the reportd implement smtp instead of submission
    # via /usr/sbin/sendmail ...
    && rm -rf /etc/ssmtp/ \
    && install -d /etc/ssmtp/ \
    && ln -sf /tmp/ssmtp.conf /etc/ssmtp/ssmtp.conf \
    && ln -sf /tmp/revaliases /etc/ssmtp/revaliases


CMD ["/cmd"]
ENTRYPOINT ["/entrypoint"]
ENV TLSRPT_COLLECTD_STORAGE="sqlite:///tlsrpt-data/collectd.sqlite"
ENV TLSRPT_FETCHER_STORAGE="sqlite:///tlsrpt-data/collectd.sqlite"
ENV TLSRPT_REPORTD_DBNAME="/tlsrpt-data/reportd.sqlite"
ENV TLSRPT_REPORTD_FETCHERS="/usr/local/bin/tlsrpt-fetcher"
ENV TLSRPT_FETCHER_LOGFILENAME="/proc/1/fd/1"
USER tlsrpt
WORKDIR /home/tlsrpt
