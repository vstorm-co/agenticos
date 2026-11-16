"""Keep oversized WKS bitmap service numbers out of the locked DNS parser."""

import dns.exception
import dns.rdata
import pytest


@pytest.mark.security
def test_dns_zone_parser_refuses_service_numbers_above_the_wire_range() -> None:
    with pytest.raises(dns.exception.SyntaxError):
        dns.rdata.from_text("IN", "WKS", "10.0.0.1 udp 65536")
