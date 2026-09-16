"""SSRF (Server-Side Request Forgery) protection validator.
Blocks internal IP ranges (RFC1918), localhost, link-local, and cloud metadata endpoints.
"""

import ipaddress
import socket
from urllib.parse import urlparse


BLOCKED_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),      # Loopback
    ipaddress.ip_network("10.0.0.0/8"),       # RFC1918 Private
    ipaddress.ip_network("172.16.0.0/12"),    # RFC1918 Private
    ipaddress.ip_network("192.168.0.0/16"),   # RFC1918 Private
    ipaddress.ip_network("169.254.0.0/16"),   # Link-local / Cloud Metadata (AWS, GCP, Azure)
    ipaddress.ip_network("::1/128"),          # IPv6 Loopback
    ipaddress.ip_network("fc00::/7"),         # IPv6 Private
    ipaddress.ip_network("fe80::/10"),        # IPv6 Link-local
]


def is_safe_external_url(url: str) -> tuple[bool, str]:
    """Validates URL against SSRF threats.
    Returns (is_safe, reason).
    """
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False, f"Unsupported URL scheme: {parsed.scheme}"

        hostname = parsed.hostname
        if not hostname:
            return False, "Missing hostname in URL"

        # Block localhost variants
        if hostname.lower() in ("localhost", "127.0.0.1", "0.0.0.0", "metadata.google.internal"):
            return False, f"Access to localhost/internal hostname '{hostname}' is blocked"

        # Resolve IP addresses for hostname
        try:
            addr_info = socket.getaddrinfo(hostname, None)
            for item in addr_info:
                ip_str = item[4][0]
                ip_obj = ipaddress.ip_address(ip_str)

                for blocked_net in BLOCKED_NETWORKS:
                    if ip_obj in blocked_net:
                        return False, f"URL resolves to restricted internal IP '{ip_str}' in '{blocked_net}'"

        except socket.gaierror:
            # If DNS resolution fails, reject for security
            return False, f"Could not resolve hostname '{hostname}'"

        return True, "URL validated as safe external destination"

    except Exception as e:
        return False, f"URL validation error: {str(e)}"
