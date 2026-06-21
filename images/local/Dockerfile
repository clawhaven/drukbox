# Minimal sandbox image for the local `docker` provider: Ubuntu + sshd.
# Build once, then point the provider at it:
#
#   docker build -t drukbox/sandbox:latest images/local/
#
# The entrypoint seeds authorized_keys from $DRUKBOX_AUTHORIZED_KEY (injected by
# drukbox per host) and runs sshd in the foreground. Key-only auth; no password.
FROM ubuntu:24.04

RUN apt-get update \
    && apt-get install -y --no-install-recommends openssh-server ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /run/sshd

COPY entrypoint.sh /usr/local/bin/drukbox-entrypoint
RUN chmod +x /usr/local/bin/drukbox-entrypoint

EXPOSE 22
ENTRYPOINT ["/usr/local/bin/drukbox-entrypoint"]
