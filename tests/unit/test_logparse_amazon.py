# Copyright (c) 2026 Kenneth Stott
# Canary: 1c7ca615-abec-44b7-9af4-becb9d7ac2be
#
# This source code is licensed under the Business Source License 1.1
"""REQ-1996: the Amazon log presets read the lines AWS's own documentation gives for each log
(tests/unit/fixtures/logparse/amazon), one fixture per preset."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from provisa.logparse import BUILT_IN, FileContext, ParseError, catalog, records

_FIXTURES = Path(__file__).parent / "fixtures" / "logparse" / "amazon"
_UTC = timezone.utc


def _ctx() -> FileContext:
    return FileContext(mtime=datetime(2026, 10, 12, 9, 0, tzinfo=_UTC))


def rows(name: str, fixture: str | None = None) -> list[dict]:
    """A fixture read as the Logs source reads a file: header lines to the format, the rest
    framed into records, each record's rows."""
    fmt = BUILT_IN[name]
    ctx = _ctx()
    lines = (_FIXTURES / (fixture or f"{name}.log")).read_text().splitlines()
    body: list[tuple[int, str]] = []
    for i, line in enumerate(lines):
        if fmt.header_prefix and line.startswith(fmt.header_prefix):
            fmt.on_header(line, ctx)
        elif line:
            body.append((i, line))
    out: list[dict] = []
    for _, record in records(body, fmt.record_start):
        out.extend(fmt.parse_many(record, ctx))
    return out


def test_the_amazon_presets_are_offered_under_their_family():
    names = {e["name"]: e["group"] for e in catalog()}
    for name in (
        "aws_alb",
        "aws_nlb",
        "aws_elb",
        "aws_cloudfront",
        "aws_s3_access",
        "aws_cloudtrail",
        "aws_vpc_flow",
        "aws_waf",
        "aws_route53_resolver",
    ):
        assert names[name] == "amazon"


def test_alb_access_log():
    first, second = rows("aws_alb")
    assert first["timestamp"] == datetime(2018, 7, 2, 22, 23, 0, 186641, tzinfo=_UTC)
    assert (first["type"], first["elb"]) == ("http", "app/my-loadbalancer/50dc6c495c0c9188")
    assert (first["client_ip"], first["client_port"]) == ("192.168.131.39", 2817)
    assert (first["target_ip"], first["target_port"]) == ("10.0.0.1", 80)
    assert (first["elb_status_code"], first["sent_bytes"]) == ("200", "366")
    assert (first["method"], first["url"], first["protocol"]) == (
        "GET",
        "http://www.example.com:80/",
        "HTTP/1.1",
    )
    assert first["user_agent"] == "curl/7.46.0"
    assert first["ssl_cipher"] is None and first["domain_name"] is None
    assert first["request_creation_time"] == datetime(2018, 7, 2, 22, 22, 48, 364000, tzinfo=_UTC)
    assert first["conn_trace_id"] == "TID_1234abcd5678ef90"
    assert second["actions_executed"] == "authenticate,forward"
    assert second["ssl_protocol"] == "TLSv1.2"
    assert second["domain_name"] == "www.example.com"


def test_alb_keeps_fields_a_newer_version_adds_in_order():
    line = (_FIXTURES / "aws_alb.log").read_text().splitlines()[0] + ' "new" 7'
    row = BUILT_IN["aws_alb"].parse(line, _ctx())
    assert row["trailing"] == ["new", "7"]


def test_nlb_tls_access_log():
    (row,) = rows("aws_nlb")
    assert row["timestamp"] == datetime(2018, 12, 20, 2, 59, 40, tzinfo=_UTC)
    assert (row["client_ip"], row["client_port"]) == ("72.21.218.154", 51341)
    assert (row["destination_ip"], row["destination_port"]) == ("172.100.100.185", 443)
    assert (row["tls_cipher"], row["tls_protocol_version"]) == ("ECDHE-RSA-AES128-SHA", "tlsv12")
    assert row["incoming_tls_alert"] is None
    assert row["alpn_client_preference_list"] == '"h2","http/1.1"'
    assert row["tls_connection_creation_time"] == datetime(2020, 4, 1, 8, 51, 42, tzinfo=_UTC)


def test_classic_elb_access_log():
    http, tcp_error = rows("aws_elb")
    assert http["timestamp"] == datetime(2015, 5, 13, 23, 39, 43, 945958, tzinfo=_UTC)
    assert (http["backend_ip"], http["backend_port"]) == ("10.0.0.1", 80)
    assert http["method"] == "GET" and http["ssl_cipher"] is None
    # The documentation's example of a request that never reached a backend.
    assert tcp_error["elb_status_code"] is None and tcp_error["user_agent"] is None


def test_cloudfront_standard_log_by_its_header():
    (row,) = rows("aws_cloudfront")
    assert row["timestamp"] == datetime(2019, 12, 4, 21, 2, 31, tzinfo=_UTC)
    assert row["x_edge_location"] == "LAX1"
    assert row["cs_host"] == "d111111abcdef8.cloudfront.net"
    assert row["cs_uri_stem"] == "/index.html"
    assert row["sc_status"] == "200"
    assert row["cs_referer"] is None
    assert row["sc_content_type"] == "text/html"


def test_s3_server_access_log():
    first, _ = rows("aws_s3_access")
    assert first["timestamp"] == datetime(2019, 2, 6, 0, 0, 38, tzinfo=_UTC)
    assert first["bucket"] == "awsexamplebucket1"
    assert first["operation"] == "REST.GET.VERSIONING"
    assert first["key"] is None
    assert (first["method"], first["url"]) == ("GET", "/awsexamplebucket1?versioning")
    assert (first["http_status"], first["bytes_sent"], first["object_size"]) == ("200", "113", None)
    assert first["user_agent"] == "S3Console/0.4"
    assert first["tls_version"] == "TLSV1.2"


def test_cloudtrail_is_a_row_per_record():
    started, refused = rows("aws_cloudtrail", "aws_cloudtrail.json")
    assert started["event_time"] == datetime(2023, 7, 19, 21, 17, 28, tzinfo=_UTC)
    assert (started["event_source"], started["event_name"]) == (
        "ec2.amazonaws.com",
        "StartInstances",
    )
    assert started["user_arn"] == "arn:aws:iam::123456789012:user/Mateo"
    assert started["user_identity"]["userName"] == "Mateo"
    assert started["read_only"] is False and started["error_code"] is None
    assert refused["error_code"] == "EntityAlreadyExists"
    assert refused["user_type"] == "AssumedRole"
    assert refused["request_parameters"] == {"userName": "Richard"}


def test_cloudtrail_written_over_several_lines_is_one_document():
    doc = (_FIXTURES / "aws_cloudtrail.json").read_text()
    import json

    pretty = json.dumps(json.loads(doc), indent=2).splitlines()
    fmt = BUILT_IN["aws_cloudtrail"]
    framed = list(records(list(enumerate(pretty)), fmt.record_start))
    assert len(framed) == 1
    assert len(fmt.parse_many(framed[0][1], _ctx())) == 2


def test_a_cloudtrail_document_without_records_is_refused():
    with pytest.raises(ParseError, match="no Records list"):
        BUILT_IN["aws_cloudtrail"].parse_many('{"Events": []}', _ctx())


def test_vpc_flow_log_default_version_2():
    accepted, nodata = rows("aws_vpc_flow")
    assert accepted["account_id"] == "123456789010"
    assert (accepted["srcaddr"], accepted["dstport"], accepted["action"]) == (
        "172.31.16.139",
        "22",
        "ACCEPT",
    )
    assert accepted["start"] == datetime(2014, 12, 14, 4, 6, 50, tzinfo=_UTC)
    assert nodata["log_status"] == "NODATA" and nodata["srcaddr"] is None


def test_vpc_flow_log_with_its_own_fields():
    (row,) = rows("aws_vpc_flow", "aws_vpc_flow_custom.log")
    assert (row["version"], row["vpc_id"], row["instance_id"]) == (
        "3",
        "vpc-12345678",
        "i-07890123456789012",
    )
    assert row["pkt_srcaddr"] == "10.0.0.62" and row["tcp_flags"] == "2"
    assert row["end"] == datetime(2019, 8, 26, 19, 48, 53, tzinfo=_UTC)
    cols = {
        c.name: c.type
        for c in BUILT_IN["aws_vpc_flow"].columns(
            (_FIXTURES / "aws_vpc_flow_custom.log").read_text().splitlines()
        )
    }
    assert cols["start"] == "timestamp" and cols["bytes"] == "integer"


def test_waf_log():
    (row,) = rows("aws_waf")
    assert row["timestamp"] == datetime(2019, 12, 13, 23, 40, 12, 771000, tzinfo=_UTC)
    assert (row["action"], row["terminating_rule_id"]) == ("BLOCK", "STMTest_SQLi_XSS")
    assert (row["client_ip"], row["country"], row["http_method"]) == ("1.1.1.1", "AU", "GET")
    assert row["labels"] == [{"name": "value"}]
    # A field the preset has no column for is kept for the extra column.
    assert row["terminatingRuleMatchDetails"][0]["conditionType"] == "SQL_INJECTION"


def test_route53_resolver_query_log():
    (row,) = rows("aws_route53_resolver")
    assert row["query_timestamp"] == datetime(2021, 2, 4, 17, 51, 55, tzinfo=_UTC)
    assert (row["query_name"], row["query_type"], row["rcode"]) == (
        "amazonaws.com.",
        "A",
        "NOERROR",
    )
    assert row["answers"][0]["Rdata"] == "1.2.3.4"
    assert row["srcport"] == "56067"
    assert row["firewall_rule_action"] is None


@pytest.mark.parametrize("name", ["aws_alb", "aws_elb", "aws_s3_access"])
def test_a_line_in_another_form_is_refused_by_the_preset_s_label(name):
    with pytest.raises(ParseError, match=BUILT_IN[name].label):
        BUILT_IN[name].parse("not a log line", _ctx())
