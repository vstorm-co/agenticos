"""Real SDK/TLS requests use vetted addresses without changing AWS identity."""

import datetime
import http.client
import io
import select
import socket
import ssl
import threading
from concurrent.futures import CancelledError
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

import boto3
import pytest
from botocore.auth import S3SigV4Auth
from botocore.awsrequest import AWSRequest, AWSResponse
from botocore.config import Config
from botocore.credentials import Credentials
from botocore.exceptions import (
    BotoCoreError,
    ConnectTimeoutError,
    EndpointConnectionError,
    HTTPClientError,
    InvalidRegionError,
    SSLError,
)
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from app.core.config import settings
from app.core.sanitize import SSRFBlockedError
from app.core.secret_kinds import AwsCredentialsSecret
from app.services.rag.connectors._s3_http import pin_s3_client
from app.services.rag.connectors.s3 import S3Connector

PUBLIC = "93.184.216.34"
NAME = "store.s3.test"


@pytest.fixture
def tls_files(tmp_path: Path) -> tuple[Path, Path]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, NAME)])
    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(NAME)]), critical=False)
        .sign(key, hashes.SHA256())
    )
    cert_path, key_path = tmp_path / "cert.pem", tmp_path / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return cert_path, key_path


@contextmanager
def s3_server(tls_files=None, redirect_region=None, paginate=False, ipv6=False):
    received = []
    sni = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            received.append((self.path, dict(self.headers)))
            if redirect_region and len(received) == 1:
                self.send_response(301)
                self.send_header("x-amz-bucket-region", redirect_region)
                body = b"<Error><Code>PermanentRedirect</Code></Error>"
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            body = (
                b'<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
                b"<IsTruncated>false</IsTruncated><Name>bucket</Name></ListBucketResult>"
                if "list-type" in self.path
                else b"synthetic document"
            )
            if paginate and "list-type" in self.path and "continuation-token" not in self.path:
                body = body.replace(
                    b"<IsTruncated>false</IsTruncated>",
                    b"<IsTruncated>true</IsTruncated><NextContinuationToken>next</NextContinuationToken>",
                )
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_PUT(self):
            self.send_response_only(100)
            self.end_headers()
            body = self.rfile.read(int(self.headers["Content-Length"]))
            received.append((self.path, dict(self.headers), body))
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.send_header("ETag", '"synthetic-etag"')
            self.end_headers()

        def log_message(self, *_args):
            pass

    if ipv6:

        class IPv6Server(ThreadingHTTPServer):
            address_family = socket.AF_INET6

        server = IPv6Server(("::1", 0), Handler)
    else:
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    if tls_files:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(*tls_files)
        context.set_servername_callback(lambda _socket, name, _context: sni.append(name))
        server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_port, received, sni
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@contextmanager
def proxy_server(tls_files=None, refused_address=None):
    targets = []

    class Handler(BaseHTTPRequestHandler):
        def do_CONNECT(self):
            targets.append((self.path, self.headers.get("Proxy-Authorization")))
            host, port = self.path.rsplit(":", 1)
            if host == refused_address:
                self.send_response(502)
                self.end_headers()
                return
            with socket.create_connection((host.strip("[]"), int(port))) as upstream:
                self.send_response(200)
                self.end_headers()
                while True:
                    readable, _, _ = select.select([self.connection, upstream], [], [], 3)
                    if not readable:
                        return
                    for source in readable:
                        data = source.recv(65536)
                        if not data:
                            return
                        (upstream if source is self.connection else self.connection).sendall(data)

        def do_GET(self):
            targets.append((self.path, self.headers.get("Proxy-Authorization")))
            parsed = urlsplit(self.path)
            upstream = http.client.HTTPConnection(parsed.hostname, parsed.port)
            try:
                path = parsed.path + ("?" + parsed.query if parsed.query else "")
                headers = {
                    key: value
                    for key, value in self.headers.items()
                    if key.lower() != "proxy-authorization"
                }
                upstream.request("GET", path, headers=headers)
                response = upstream.getresponse()
                body = response.read()
                self.send_response(response.status)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            finally:
                upstream.close()

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    if tls_files:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(*tls_files)
        server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_port, targets
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.fixture
def network(monkeypatch):
    """Route the synthetic public address into a local fixture after recording it."""
    real_connect = socket.socket.connect
    real_dns = socket.getaddrinfo
    answers = {NAME: [PUBLIC]}
    connects = []

    def dns(host, port, *args, **kwargs):
        if host in answers:
            return [
                (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (ip, port))
                for ip in answers[host]
            ]
        return real_dns(host, port, *args, **kwargs)

    def connect(sock, address):
        connects.append(address)
        if address[0] in (PUBLIC, "10.255.255.9"):
            address = ("127.0.0.1", address[1])
        elif address[0] == "2606:4700:4700::1111":
            address = ("::1", address[1])
        return real_connect(sock, address)

    monkeypatch.setattr(socket, "getaddrinfo", dns)
    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(settings, "OUTBOUND_PRIVATE_ALLOWLIST", [])
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.delenv(key, raising=False)
    return answers, connects


@contextmanager
def client(endpoint, verify=True, **options):
    result = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id="synthetic-key",
        aws_secret_access_key="synthetic-secret",
        region_name="us-east-1",
        verify=verify,
        config=Config(signature_version="s3v4", retries={"max_attempts": 0}, **options),
    )
    pin_s3_client(result)
    try:
        yield result
    finally:
        result.close()


def assert_signature(endpoint, path, headers, region="us-east-1"):
    authorization = headers["Authorization"]
    signed_names = authorization.split("SignedHeaders=", 1)[1].split(",", 1)[0].split(";")
    selected = {key: value for key, value in headers.items() if key.lower() in signed_names}
    request = AWSRequest(method="GET", url=endpoint + path, headers=selected)
    time = datetime.datetime.strptime(headers["X-Amz-Date"], "%Y%m%dT%H%M%SZ").replace(
        tzinfo=datetime.UTC
    )
    with patch("botocore.auth.get_current_datetime", return_value=time):
        S3SigV4Auth(Credentials("synthetic-key", "synthetic-secret"), "s3", region).add_auth(
            request
        )
    assert request.headers["Authorization"] == authorization


def test_real_tls_preserves_sni_host_signature_and_stream(network, tls_files):
    with s3_server(tls_files) as (port, requests, sni):
        endpoint = f"https://{NAME}:{port}"
        with client(endpoint, str(tls_files[0])) as sdk:
            assert sdk.list_objects_v2(Bucket="bucket")["Name"] == "bucket"
            response = sdk.get_object(Bucket="bucket", Key="document")
            try:
                assert response["Body"].read() == b"synthetic document"
            finally:
                response["Body"].close()
        assert sni == [NAME, NAME]
        assert all(headers["Host"] == f"{NAME}:{port}" for _, headers in requests)
        for path, headers in requests:
            assert_signature(endpoint, path, headers)
        assert (PUBLIC, port) in network[1]


def test_dns_change_after_client_creation_is_refused_without_connect(network):
    answers, connects = network
    with client(f"http://{NAME}") as sdk:
        answers[NAME] = ["10.0.0.5"]
        with pytest.raises(HTTPClientError) as refusal:
            sdk.list_objects_v2(Bucket="bucket")
    assert isinstance(refusal.value.kwargs["error"], SSRFBlockedError)
    assert connects == []


def test_ipv6_address_is_dialed_numerically_with_original_tls_name(network, tls_files):
    network[0][NAME] = ["2606:4700:4700::1111"]
    with s3_server(tls_files, ipv6=True) as (port, requests, sni):
        with client(f"https://{NAME}:{port}", str(tls_files[0])) as sdk:
            sdk.list_objects_v2(Bucket="bucket")
        assert sni == [NAME]
        assert requests[0][1]["Host"] == f"{NAME}:{port}"
        assert ("2606:4700:4700::1111", port) in network[1]


def test_mixed_dns_answers_refuse_every_address(network):
    network[0][NAME] = [PUBLIC, "169.254.169.254"]
    with client(f"http://{NAME}") as sdk, pytest.raises(HTTPClientError):
        sdk.list_objects_v2(Bucket="bucket")
    assert network[1] == []


def test_one_vetted_resolution_reaches_socket_without_a_second_hostname_lookup(network):
    original_dns = socket.getaddrinfo
    lookups = []

    def rebinding_dns(host, port, *args, **kwargs):
        if host == NAME:
            lookups.append(host)
            address = PUBLIC if len(lookups) == 1 else "10.255.255.9"
            return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (address, port))]
        return original_dns(host, port, *args, **kwargs)

    with patch.object(socket, "getaddrinfo", rebinding_dns), s3_server() as (port, requests, _sni):
        with client(f"http://{NAME}:{port}") as sdk:
            sdk.list_objects_v2(Bucket="bucket")
        assert len(requests) == 1
    assert lookups == [NAME]


def test_connector_client_revalidates_after_its_creation_check(network):
    credential = AwsCredentialsSecret(
        aws_access_key_id="synthetic", aws_secret_access_key="synthetic", region_name="us-east-1"
    )
    sdk = S3Connector()._get_s3_client(
        {"bucket": "bucket", "endpoint_url": f"http://{NAME}"}, credential
    )
    network[0][NAME] = ["10.255.255.9"]
    try:
        with pytest.raises(HTTPClientError):
            sdk.list_objects_v2(Bucket="bucket")
        assert network[1] == []
    finally:
        sdk.close()


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (TimeoutError("synthetic timeout"), ConnectTimeoutError),
        (ConnectionRefusedError("synthetic refusal"), EndpointConnectionError),
        (CancelledError("synthetic cancellation"), CancelledError),
    ],
)
def test_failed_or_cancelled_connect_closes_its_socket_without_sending(network, failure, expected):
    original = socket.socket.connect
    attempted = []

    def abort(sock, address):
        if address[0] == PUBLIC:
            attempted.append(sock)
            raise failure
        return original(sock, address)

    with (
        patch.object(socket.socket, "connect", abort),
        client(f"http://{NAME}") as sdk,
        pytest.raises(expected),
    ):
        sdk.list_objects_v2(Bucket="bucket")
    assert len(attempted) == 1
    assert attempted[0].fileno() == -1


def test_vault_session_token_is_sent_and_signed_by_the_connector_client(network):
    credential = AwsCredentialsSecret(
        aws_access_key_id="synthetic-key",
        aws_secret_access_key="synthetic-secret",
        aws_session_token="synthetic-session-token",
        region_name="us-east-1",
    )
    with s3_server() as (port, requests, _sni):
        endpoint = f"http://{NAME}:{port}"
        sdk = S3Connector()._get_s3_client(
            {"bucket": "bucket", "endpoint_url": endpoint}, credential
        )
        try:
            sdk.list_objects_v2(Bucket="bucket")
        finally:
            sdk.close()
        headers = requests[0][1]
        assert headers["X-Amz-Security-Token"] == "synthetic-session-token"
        assert (
            "x-amz-security-token"
            in headers["Authorization"].split("SignedHeaders=", 1)[1].split(",", 1)[0]
        )


def test_tls_certificate_still_checks_original_name(network, tls_files):
    network[0]["wrong.s3.test"] = [PUBLIC]
    with s3_server(tls_files) as (port, requests, _sni):
        with (
            client(f"https://wrong.s3.test:{port}", str(tls_files[0])) as sdk,
            pytest.raises(SSLError),
        ):
            sdk.list_objects_v2(Bucket="bucket")
        assert requests == []


@pytest.mark.parametrize("secure_proxy", [False, True])
def test_connect_proxies_receive_numeric_target_and_keep_original_tls_and_auth(
    network, tls_files, secure_proxy
):
    with (
        s3_server(tls_files) as (port, requests, sni),
        proxy_server(tls_files if secure_proxy else None) as (proxy_port, targets),
    ):
        endpoint = f"https://{NAME}:{port}"
        proxy = (
            f"{'https' if secure_proxy else 'http'}://proxy-user:proxy-password@{NAME}:{proxy_port}"
        )
        with client(endpoint, str(tls_files[0]), proxies={"https": proxy}) as sdk:
            sdk.list_objects_v2(Bucket="bucket")
        assert targets == [(f"{PUBLIC}:{port}", "Basic cHJveHktdXNlcjpwcm94eS1wYXNzd29yZA==")]
        assert sni == [NAME]
        assert_signature(endpoint, *requests[0])
        assert "Proxy-Authorization" not in requests[0][1]


@pytest.mark.parametrize("secure_proxy", [False, True])
def test_http_forward_proxy_receives_numeric_uri_and_original_signed_host(
    network, tls_files, secure_proxy
):
    with (
        s3_server() as (port, requests, _sni),
        proxy_server(tls_files if secure_proxy else None) as (proxy_port, targets),
    ):
        endpoint = f"http://{NAME}:{port}"
        proxy = f"{'https' if secure_proxy else 'http'}://{NAME}:{proxy_port}"
        with client(endpoint, str(tls_files[0]), proxies={"http": proxy}) as sdk:
            sdk.list_objects_v2(Bucket="bucket")
        assert targets[0][0].startswith(f"http://{PUBLIC}:{port}/bucket?")
        assert requests[0][1]["Host"] == f"{NAME}:{port}"
        assert_signature(endpoint, *requests[0])


def test_sdk_region_redirect_reconnects_and_signs_for_new_region(network, tls_files):
    with s3_server(tls_files, redirect_region="eu-west-1") as (port, requests, sni):
        endpoint = f"https://{NAME}:{port}"
        with client(endpoint, str(tls_files[0])) as sdk:
            sdk.list_objects_v2(Bucket="bucket")
        assert len(requests) == 2
        assert sni == [NAME, NAME]
        assert_signature(endpoint, *requests[0])
        assert_signature(endpoint, *requests[1], region="eu-west-1")


def test_sdk_paginator_and_upload_part_keep_the_native_connection_protocol(network, tls_files):
    with s3_server(tls_files, paginate=True) as (port, requests, _sni):
        with client(
            f"https://{NAME}:{port}",
            str(tls_files[0]),
            request_checksum_calculation="when_required",
        ) as sdk:
            pages = list(sdk.get_paginator("list_objects_v2").paginate(Bucket="bucket"))
            assert len(pages) == 2
            assert "continuation-token=next" in requests[1][0]
            response = sdk.upload_part(
                Bucket="bucket",
                Key="document",
                PartNumber=1,
                UploadId="synthetic-upload",
                Body=b"part body",
            )
            assert response["ETag"] == '"synthetic-etag"'
        assert requests[2][2] == b"part body"
        assert requests[2][1]["Expect"] == "100-continue"


def test_safe_second_address_is_tried_only_after_failed_connect(network):
    network[0][NAME] = ["93.184.216.35", PUBLIC]
    original = socket.socket.connect

    def refuse_first(sock, address):
        if address[0] == "93.184.216.35":
            raise ConnectionRefusedError("synthetic unreachable first address")
        return original(sock, address)

    with (
        patch.object(socket.socket, "connect", refuse_first),
        s3_server() as (port, requests, _sni),
    ):
        with client(f"http://{NAME}:{port}") as sdk:
            sdk.list_objects_v2(Bucket="bucket")
        assert len(requests) == 1


@pytest.mark.parametrize("secure_proxy", [False, True])
def test_failed_connect_uses_a_fresh_proxy_socket_for_next_safe_address(
    network, tls_files, secure_proxy
):
    network[0][NAME] = ["93.184.216.35", PUBLIC]
    # Proxy TLS uses its own resolvable name and never shares origin authority.
    network[0]["proxy.s3.test"] = [PUBLIC]
    with (
        s3_server(tls_files) as (port, requests, _sni),
        proxy_server(tls_files if secure_proxy else None, refused_address="93.184.216.35") as (
            proxy_port,
            targets,
        ),
    ):
        proxy = f"{'https' if secure_proxy else 'http'}://{NAME}:{proxy_port}"
        # The proxy host resolves to the reachable fixture; the origin answer
        # sequence is independently applied only at the tunnel boundary.
        original_dns = socket.getaddrinfo

        def dns(host, query_port, *args, **kwargs):
            if query_port == proxy_port:
                return [
                    (
                        socket.AF_INET,
                        socket.SOCK_STREAM,
                        socket.IPPROTO_TCP,
                        "",
                        (PUBLIC, query_port),
                    )
                ]
            return original_dns(host, query_port, *args, **kwargs)

        with (
            patch.object(socket, "getaddrinfo", dns),
            client(f"https://{NAME}:{port}", str(tls_files[0]), proxies={"https": proxy}) as sdk,
        ):
            sdk.list_objects_v2(Bucket="bucket")
        assert [target for target, _auth in targets] == [
            f"93.184.216.35:{port}",
            f"{PUBLIC}:{port}",
        ]
        assert len(requests) == 1


@pytest.mark.parametrize("listed", [False, True])
def test_private_virtual_bucket_host_needs_its_own_operator_authority(network, monkeypatch, listed):
    alias = f"bucket.{NAME}"
    network[0][NAME] = ["10.255.255.9"]
    network[0][alias] = ["10.255.255.9"]
    monkeypatch.setattr(
        settings, "OUTBOUND_PRIVATE_ALLOWLIST", [NAME, *([alias] if listed else [])]
    )
    with (
        s3_server() as (port, requests, _sni),
        client(f"http://{NAME}:{port}", s3={"addressing_style": "virtual"}) as sdk,
    ):
        if listed:
            sdk.list_objects_v2(Bucket="bucket")
            assert requests[0][1]["Host"] == f"{alias}:{port}"
        else:
            with pytest.raises(HTTPClientError):
                sdk.list_objects_v2(Bucket="bucket")
            assert requests == []


@pytest.mark.parametrize("change_answer", [False, True])
def test_failed_tunnel_stops_when_no_approved_candidate_remains(network, tls_files, change_answer):
    network[0][NAME] = ["93.184.216.35", *([PUBLIC] if change_answer else [])]
    with (
        s3_server(tls_files) as (port, requests, _sni),
        proxy_server(refused_address="93.184.216.35") as (proxy_port, targets),
    ):
        original_dns = socket.getaddrinfo
        origin_queries = []

        def dns(host, query_port, *args, **kwargs):
            if query_port == proxy_port:
                return [
                    (
                        socket.AF_INET,
                        socket.SOCK_STREAM,
                        socket.IPPROTO_TCP,
                        "",
                        (PUBLIC, query_port),
                    )
                ]
            if host == NAME:
                origin_queries.append(host)
                if len(origin_queries) > 1:
                    return [
                        (
                            socket.AF_INET,
                            socket.SOCK_STREAM,
                            socket.IPPROTO_TCP,
                            "",
                            ("93.184.216.36", query_port),
                        )
                    ]
            return original_dns(host, query_port, *args, **kwargs)

        with (
            patch.object(socket, "getaddrinfo", dns),
            client(
                f"https://{NAME}:{port}",
                str(tls_files[0]),
                proxies={"https": f"http://{NAME}:{proxy_port}"},
            ) as sdk,
            pytest.raises(BotoCoreError),
        ):
            sdk.list_objects_v2(Bucket="bucket")
        assert [target for target, _auth in targets] == [f"93.184.216.35:{port}"]
        assert requests == []
        assert ("93.184.216.36", port) not in network[1]


def test_operator_fallback_keeps_its_separate_trusted_transport(network, monkeypatch):
    monkeypatch.setattr(settings, "S3_RAG_ENDPOINT", "http://operator-minio:9000")
    credential = AwsCredentialsSecret(
        aws_access_key_id="synthetic", aws_secret_access_key="synthetic", region_name="us-east-1"
    )
    sdk = S3Connector()._get_s3_client({"bucket": "bucket"}, credential)
    try:
        assert sdk.meta.endpoint_url == "http://operator-minio:9000"
        assert (
            sdk._endpoint.http_session._pool_classes_by_scheme["http"].__name__
            == "AWSHTTPConnectionPool"
        )
        assert network[1] == []
    finally:
        sdk.close()


def test_profile_can_select_virtual_style_but_default_custom_endpoint_uses_path(
    network, tmp_path, monkeypatch
):
    urls = []
    profile = tmp_path / "aws-config"
    monkeypatch.setenv("AWS_CONFIG_FILE", str(profile))
    for style in (None, "virtual"):
        profile.write_text(
            "[default]\n" + ("s3 =\n    addressing_style = virtual\n" if style else "")
        )
        session = boto3.Session()
        sdk = session.client(
            "s3",
            endpoint_url=f"https://{NAME}",
            region_name="us-east-1",
            aws_access_key_id="synthetic",
            aws_secret_access_key="synthetic",
            config=Config(signature_version="s3v4"),
        )

        def capture(request, **_kwargs):
            urls.append(request.url)
            return AWSResponse(request.url, 200, {"Content-Length": "0"}, io.BytesIO())

        sdk.meta.events.register("before-send.s3.GetObject", capture)
        sdk.get_object(Bucket="bucket", Key="document")["Body"].close()
        sdk.close()
    assert urls == [f"https://{NAME}/bucket/document", f"https://bucket.{NAME}/document"]


@pytest.mark.parametrize(
    "region", ["evil.test/path", "evil.test", "x:9000", "x@evil", "x?evil", "x#evil"]
)
def test_region_cannot_choose_an_arbitrary_fallback_endpoint(region):
    with pytest.raises(InvalidRegionError):
        S3Connector()._get_s3_client(
            {"bucket": "bucket", "region": region},
            AwsCredentialsSecret(
                aws_access_key_id="synthetic",
                aws_secret_access_key="synthetic",
                region_name="us-east-1",
            ),
        )
