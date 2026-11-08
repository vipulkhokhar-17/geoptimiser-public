import ipaddress
import socket

import pytest

from geoptimiser.crawler.netguard import (
    PolicyViolation,
    is_public_address,
    resolve_allowed,
)


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "127.1.2.3",
        "10.0.0.1",
        "172.16.5.4",
        "192.168.1.1",
        "169.254.169.254",  # cloud metadata (link-local)
        "100.100.100.200",  # Alibaba metadata (carrier-grade NAT range)
        "100.64.0.1",
        "0.0.0.0",
        "224.0.0.1",
        "255.255.255.255",
        "198.18.0.1",
        "192.0.2.1",
        "::1",
        "::",
        "fe80::1",
        "fd00:ec2::254",  # AWS IPv6 metadata (unique local)
        "fc00::1",
        "ff02::1",
        "::ffff:127.0.0.1",  # IPv4-mapped loopback
        "::ffff:10.0.0.1",
        "::ffff:169.254.169.254",
        "64:ff9b::7f00:1",  # NAT64
        "2002:7f00:1::",  # 6to4
        "2001:db8::1",
    ],
)
def test_non_public_addresses_are_rejected(address: str) -> None:
    assert not is_public_address(ipaddress.ip_address(address))


@pytest.mark.parametrize(
    "address", ["93.184.216.34", "8.8.8.8", "1.1.1.1", "2606:4700:4700::1111"]
)
def test_public_addresses_are_accepted(address: str) -> None:
    assert is_public_address(ipaddress.ip_address(address))


def test_resolve_allowed_returns_vetted_addresses() -> None:
    assert resolve_allowed(
        "a.test", 443, lambda h, p: ["8.8.8.8"], is_public_address
    ) == ["8.8.8.8"]


def test_one_private_address_poisons_the_whole_answer() -> None:
    resolver = lambda h, p: ["8.8.8.8", "10.0.0.5"]  # noqa: E731
    with pytest.raises(PolicyViolation) as caught:
        resolve_allowed("a.test", 443, resolver, is_public_address)
    assert caught.value.reason == "blocked_address"


@pytest.mark.parametrize("literal", ["127.0.0.1", "[::1]", "169.254.169.254"])
def test_ip_literals_never_reach_the_resolver(literal: str) -> None:
    def resolver(host: str, port: int) -> list[str]:
        raise AssertionError("resolver must not be called for literals")

    with pytest.raises(PolicyViolation):
        resolve_allowed(literal, 80, resolver, is_public_address)


def test_empty_resolution_is_refused() -> None:
    with pytest.raises(PolicyViolation):
        resolve_allowed("a.test", 80, lambda h, p: [], is_public_address)


def test_resolver_failure_propagates_as_gaierror() -> None:
    def resolver(host: str, port: int) -> list[str]:
        raise socket.gaierror("no such host")

    with pytest.raises(socket.gaierror):
        resolve_allowed("a.test", 80, resolver, is_public_address)


def test_ipv6_zone_id_is_ignored_when_parsing() -> None:
    with pytest.raises(PolicyViolation):
        resolve_allowed("a.test", 80, lambda h, p: ["fe80::1%eth0"], is_public_address)
