"""A TLS context that does not depend on the host's certificate store.

The python.org macOS builds ship without a usable CA bundle, so `wss://`
handshakes fail with CERTIFICATE_VERIFY_FAILED unless the user has run
"Install Certificates.command". Bundling certifi removes that as a setup step
and makes the container image behave the same as a laptop.

Verification is always on. This never disables certificate checking.
"""

from __future__ import annotations

import functools
import ssl

import certifi


@functools.cache
def tls_context() -> ssl.SSLContext:
    return ssl.create_default_context(cafile=certifi.where())
