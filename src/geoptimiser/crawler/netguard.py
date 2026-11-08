"""Network address policy: which resolved addresses the crawler may connect to.

The policy is applied to the addresses actually used for a connection (after DNS
resolution, and again on the connected peer), never to the hostname alone. A host
that resolves to any non-public address is refused entirely.
"""

import ipaddress
import socket
from collections.abc import Callable

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
IPPolicy = Callable[[IPAddress], bool]
Resolver = Callable[[str, int], list[str]]

# Ranges that Python's ``is_global`` may still treat as global, or that embed or
# translate another address (6to4, Teredo, NAT64), plus documentation ranges.
_EXTRA_BLOCKED = tuple(
    ipaddress.ip_network(n)
    for n in (
        "0.0.0.0/8",
        "100.64.0.0/10",  # carrier-grade NAT; includes Alibaba metadata 100.100.100.200
        "192.0.0.0/24",
        "192.0.2.0/24",
        "192.88.99.0/24",
        "198.18.0.0/15",
        "198.51.100.0/24",
        "203.0.113.0/24",
        "224.0.0.0/4",
        "240.0.0.0/4",
        "64:ff9b::/96",
        "64:ff9b:1::/48",
        "100::/64",
        "2001::/32",
        "2001:db8::/32",
        "2002::/16",
        "fc00::/7",  # unique local; includes AWS IPv6 metadata fd00:ec2::254
        "fe80::/10",
        "ff00::/8",
    )
)


class PolicyViolation(Exception):
    """A target was refused by the crawler's safety policy."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


def parse_ip(value: str) -> IPAddress:
    """Parse an address string, dropping an IPv6 zone id (``fe80::1%eth0``)."""
    return ipaddress.ip_address(value.split("%", 1)[0])


def is_public_address(ip: IPAddress) -> bool:
    """True only for globally routable unicast addresses."""
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or not ip.is_global
    ):
        return False
    return not any(ip.version == net.version and ip in net for net in _EXTRA_BLOCKED)


def system_resolver(host: str, port: int) -> list[str]:
    """Resolve ``host`` with the OS resolver, returning unique address strings."""
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return list(dict.fromkeys(str(info[4][0]) for info in infos))


def resolve_allowed(
    host: str, port: int, resolver: Resolver, policy: IPPolicy
) -> list[str]:
    """Resolve ``host`` once and return its addresses, all of which must pass.

    Raises ``socket.gaierror`` if resolution fails and ``PolicyViolation`` if the
    host resolves to nothing or to any address the policy rejects. The caller
    connects to the returned addresses, never to the hostname, so a second
    (rebinding) DNS answer is never used.
    """
    literal = host.strip("[]")
    try:
        addresses = [str(parse_ip(literal))]
    except ValueError:
        addresses = resolver(host, port)
    if not addresses:
        raise PolicyViolation("blocked_address", f"{host} resolved to no addresses")
    for raw in addresses:
        try:
            ip = parse_ip(raw)
        except ValueError:
            raise PolicyViolation(
                "blocked_address", f"{host} resolved to an invalid address"
            ) from None
        if not policy(ip):
            raise PolicyViolation(
                "blocked_address", f"{host} resolves to a non-public address ({ip})"
            )
    return addresses
