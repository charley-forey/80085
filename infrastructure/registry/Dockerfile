# 80085's own artifact registry.
#
# Artifacts are OCI images referenced by digest, so they have to live
# somewhere any worker can pull from. Hosting it here keeps the deployment
# self-contained: no external registry account, and the reference an
# Experience records is meaningful to everyone, not just the machine that
# built it.
#
# Both push and pull require the credentials in ./htpasswd -- registry:2's
# htpasswd auth has no anonymous read mode. Workers run `docker login` once.
# The file holds a bcrypt hash of a 24-byte random password, which is why it
# can live in the repository.
FROM registry:2

COPY htpasswd /auth/htpasswd

ENV REGISTRY_AUTH=htpasswd \
    REGISTRY_AUTH_HTPASSWD_REALM="80085 artifact registry" \
    REGISTRY_AUTH_HTPASSWD_PATH=/auth/htpasswd \
    REGISTRY_STORAGE_FILESYSTEM_ROOTDIRECTORY=/data \
    REGISTRY_STORAGE_DELETE_ENABLED=true
