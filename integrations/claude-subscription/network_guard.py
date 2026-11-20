"""Restrict native users' network access before dropping network administration."""

import ctypes
import ipaddress
import os
import subprocess

NATIVE_UID_MIN = 20000
BLOCKED_V4 = (
    "0.0.0.0/8",
    "10.0.0.0/8",
    "100.64.0.0/10",
    "127.0.0.0/8",
    "169.254.0.0/16",
    "172.16.0.0/12",
    "192.0.0.0/24",
    "192.168.0.0/16",
    "198.18.0.0/15",
    "224.0.0.0/4",
    "240.0.0.0/4",
)


def run_filter(*arguments: str) -> None:
    subprocess.run(["iptables", "-w", "5", *arguments], check=True, capture_output=True)


def install_network_guard() -> None:
    """Fail closed; root's authenticated control traffic is outside this UID range."""
    if os.getuid() != 0:
        raise RuntimeError(
            "Native session startup requires its container root identity"
        )
    with open("/proc/sys/net/ipv6/conf/all/disable_ipv6", encoding="ascii") as handle:
        if handle.read().strip() != "1":
            raise RuntimeError("IPv6 must be disabled in the native service namespace")
    extra = os.environ.get("CLAUDE_SUBSCRIPTION_BLOCKED_CIDRS", "").split(",")
    if not any(item.strip() for item in extra):
        raise RuntimeError(
            "CLAUDE_SUBSCRIPTION_BLOCKED_CIDRS must include the host public addresses"
        )
    blocked = [*BLOCKED_V4]
    for item in extra:
        if item.strip():
            network = ipaddress.ip_network(item.strip(), strict=False)
            if network.version != 4:
                raise RuntimeError(
                    "IPv6 is disabled; blocked host addresses must be IPv4"
                )
            blocked.append(str(network))
    run_filter("-N", "NATIVE_USERS")
    # Docker rewrites the embedded resolver's destination port before filter OUTPUT.
    # The original destination-port match permits DNS, not the broker on loopback.
    for protocol in ("udp", "tcp"):
        run_filter(
            "-A",
            "NATIVE_USERS",
            "-d",
            "127.0.0.11/32",
            "-p",
            protocol,
            "-m",
            "conntrack",
            "--ctorigdstport",
            "53",
            "-j",
            "ACCEPT",
        )
    for network in blocked:
        run_filter("-A", "NATIVE_USERS", "-d", network, "-j", "REJECT")
    run_filter("-A", "NATIVE_USERS", "-p", "tcp", "--dport", "443", "-j", "ACCEPT")
    run_filter("-A", "NATIVE_USERS", "-j", "REJECT")
    run_filter(
        "-I",
        "OUTPUT",
        "1",
        "-m",
        "owner",
        "--uid-owner",
        f"{NATIVE_UID_MIN}:2147483647",
        "-j",
        "NATIVE_USERS",
    )
    libc = ctypes.CDLL(None, use_errno=True)
    # CAP_SETPCAP permits dropping the bounding set. It too is removed before exec.
    for capability in (12, 8):  # NET_ADMIN, SETPCAP
        if libc.prctl(24, capability, 0, 0, 0) != 0:
            raise OSError(ctypes.get_errno(), "Cannot remove startup capability")
    if libc.prctl(38, 1, 0, 0, 0) != 0:  # PR_SET_NO_NEW_PRIVS
        raise OSError(ctypes.get_errno(), "Cannot enforce no_new_privileges")
