FROM nginx:1.27-alpine

# Site assets
COPY site/ /usr/share/nginx/html/
COPY nginx.conf /etc/nginx/nginx.conf

# Symlink access/error log to stdout so Fluent Bit can `tail` them via the
# container log driver instead of needing a hostPath mount.
RUN ln -sf /dev/stdout /var/log/nginx/access.log \
 && ln -sf /dev/stderr /var/log/nginx/error.log

EXPOSE 80
HEALTHCHECK --interval=15s --timeout=3s CMD wget -qO- http://127.0.0.1/healthz || exit 1
