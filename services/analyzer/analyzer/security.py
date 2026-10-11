"""Analyzer boundary: local HTTP only; no credentials, proxy or redirects."""
import os
import urllib.request
from urllib.parse import urlsplit

SECRET_NAMES = {'api_key', 'api_secret', 'access_token', 'refresh_token', 'client_secret', 'authorization', 'credentials'}


def assert_clean_environment():
    # Refuse inherited collector configuration without reading/logging values.
    if any(name.upper().startswith('ETSY') for name in os.environ):
        raise ValueError('Collector environment detected. Use ./run-services.sh (clean environment).')


def reject_secrets(value):
    if isinstance(value, dict):
        for key, child in value.items():
            name = str(key).lower()
            if name in SECRET_NAMES or name.startswith('etsy_') and any(x in name for x in ('key', 'secret', 'token', 'credential')):
                raise ValueError('Credential-shaped field forbidden in analyzer input/configuration')
            reject_secrets(child)
    elif isinstance(value, list):
        for child in value:
            reject_secrets(child)


def local_url(url):
    parsed = urlsplit(url)
    if parsed.scheme != 'http' or parsed.hostname not in {'127.0.0.1', '::1'} or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('Only numeric-loopback HTTP endpoints allowed at this stage')
    if not parsed.port:
        raise ValueError('Explicit local HTTP port required')
    return url.rstrip('/')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('HTTP redirects forbidden')


class LocalHTTP:
    def __init__(self):
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def __call__(self, request, timeout=10):
        local_url(request if isinstance(request, str) else request.full_url)
        return self.opener.open(request, timeout=timeout)
