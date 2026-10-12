# Copyright (c) 2026 Kenneth Stott
#
# This source code is licensed under the Business Source License 1.1
"""Amazon Web Services log presets (REQ-1996): Application, Network and Classic Load Balancer
access logs, CloudFront standard logs, S3 server access logs, VPC Flow Logs, WAF logs and Route 53
Resolver query logs, each in the form its AWS documentation gives. AWS writes every time in UTC."""

from __future__ import annotations

from typing import Any

from provisa.logparse.base import Column, FileContext, Format
from provisa.logparse.coltypes import infer_type
from provisa.logparse.formats import W3C, _column_name
from provisa.logparse.presets._shared import (
    BatchJsonFormat,
    JsonFormat,
    TokenFormat,
    epoch,
    host_port,
    request_parts,
    utc,
)

GROUP = "amazon"


def _endpoint(row: dict[str, Any], prefix: str, value: str | None) -> None:
    row[f"{prefix}_ip"], row[f"{prefix}_port"] = host_port(value)


# --- Application Load Balancer -----------------------------------------------------------------

_ALB_FIELDS = [
    "type",
    "time",
    "elb",
    "client",
    "target",
    "request_processing_time",
    "target_processing_time",
    "response_processing_time",
    "elb_status_code",
    "target_status_code",
    "received_bytes",
    "sent_bytes",
    "request",
    "user_agent",
    "ssl_cipher",
    "ssl_protocol",
    "target_group_arn",
    "trace_id",
    "domain_name",
    "chosen_cert_arn",
    "matched_rule_priority",
    "request_creation_time",
    "actions_executed",
    "redirect_url",
    "error_reason",
    "target_port_list",
    "target_status_code_list",
    "classification",
    "classification_reason",
    "conn_trace_id",
]


def _alb(f: dict[str, str | None], ctx: FileContext) -> dict[str, Any]:
    row: dict[str, Any] = {
        "type": f["type"],
        "timestamp": utc(f["time"]),
        "elb": f["elb"],
    }
    _endpoint(row, "client", f["client"])
    _endpoint(row, "target", f["target"])
    row.update(
        request_processing_time=f["request_processing_time"],
        target_processing_time=f["target_processing_time"],
        response_processing_time=f["response_processing_time"],
        elb_status_code=f["elb_status_code"],
        target_status_code=f["target_status_code"],
        received_bytes=f["received_bytes"],
        sent_bytes=f["sent_bytes"],
        request=f["request"],
        **request_parts(f["request"]),
        user_agent=f["user_agent"],
        ssl_cipher=f["ssl_cipher"],
        ssl_protocol=f["ssl_protocol"],
        target_group_arn=f["target_group_arn"],
        trace_id=f["trace_id"],
        domain_name=f["domain_name"],
        chosen_cert_arn=f["chosen_cert_arn"],
        matched_rule_priority=f["matched_rule_priority"],
        request_creation_time=utc(f["request_creation_time"]),
        actions_executed=f["actions_executed"],
        redirect_url=f["redirect_url"],
        error_reason=f["error_reason"],
        target_port_list=f["target_port_list"],
        target_status_code_list=f["target_status_code_list"],
        classification=f["classification"],
        classification_reason=f["classification_reason"],
        conn_trace_id=f["conn_trace_id"],
    )
    return row


ALB = TokenFormat(
    "aws_alb",
    "AWS Application Load Balancer access log",
    GROUP,
    _ALB_FIELDS,
    [
        Column("type", "string"),
        Column("timestamp", "timestamp"),
        Column("elb", "string"),
        Column("client_ip", "string"),
        Column("client_port", "integer"),
        Column("target_ip", "string"),
        Column("target_port", "integer"),
        Column("request_processing_time", "float"),
        Column("target_processing_time", "float"),
        Column("response_processing_time", "float"),
        Column("elb_status_code", "integer"),
        Column("target_status_code", "integer"),
        Column("received_bytes", "integer"),
        Column("sent_bytes", "integer"),
        Column("request", "string"),
        Column("method", "string"),
        Column("url", "string"),
        Column("protocol", "string"),
        Column("user_agent", "string"),
        Column("ssl_cipher", "string"),
        Column("ssl_protocol", "string"),
        Column("target_group_arn", "string"),
        Column("trace_id", "string"),
        Column("domain_name", "string"),
        Column("chosen_cert_arn", "string"),
        Column("matched_rule_priority", "integer"),
        Column("request_creation_time", "timestamp"),
        Column("actions_executed", "string"),
        Column("redirect_url", "string"),
        Column("error_reason", "string"),
        Column("target_port_list", "string"),
        Column("target_status_code_list", "string"),
        Column("classification", "string"),
        Column("classification_reason", "string"),
        Column("conn_trace_id", "string"),
    ],
    _alb,
    # The fields up to the request creation time are in every version of the log.
    required=22,
)

# --- Network Load Balancer (TLS listeners) -----------------------------------------------------

_NLB_FIELDS = [
    "type",
    "version",
    "time",
    "elb",
    "listener",
    "client",
    "destination",
    "connection_time",
    "tls_handshake_time",
    "received_bytes",
    "sent_bytes",
    "incoming_tls_alert",
    "chosen_cert_arn",
    "chosen_cert_serial",
    "tls_cipher",
    "tls_protocol_version",
    "tls_named_group",
    "domain_name",
    "alpn_fe_protocol",
    "alpn_be_protocol",
    "alpn_client_preference_list",
    "tls_connection_creation_time",
]


def _nlb(f: dict[str, str | None], ctx: FileContext) -> dict[str, Any]:
    row: dict[str, Any] = {
        "type": f["type"],
        "version": f["version"],
        "timestamp": utc(f["time"]),
        "elb": f["elb"],
        "listener": f["listener"],
    }
    _endpoint(row, "client", f["client"])
    _endpoint(row, "destination", f["destination"])
    for k in _NLB_FIELDS[7:21]:
        row[k] = f[k]
    row["tls_connection_creation_time"] = utc(f["tls_connection_creation_time"])
    return row


NLB = TokenFormat(
    "aws_nlb",
    "AWS Network Load Balancer access log",
    GROUP,
    _NLB_FIELDS,
    [
        Column("type", "string"),
        Column("version", "string"),
        Column("timestamp", "timestamp"),
        Column("elb", "string"),
        Column("listener", "string"),
        Column("client_ip", "string"),
        Column("client_port", "integer"),
        Column("destination_ip", "string"),
        Column("destination_port", "integer"),
        Column("connection_time", "integer"),
        Column("tls_handshake_time", "integer"),
        Column("received_bytes", "integer"),
        Column("sent_bytes", "integer"),
        Column("incoming_tls_alert", "string"),
        Column("chosen_cert_arn", "string"),
        Column("chosen_cert_serial", "string"),
        Column("tls_cipher", "string"),
        Column("tls_protocol_version", "string"),
        Column("tls_named_group", "string"),
        Column("domain_name", "string"),
        Column("alpn_fe_protocol", "string"),
        Column("alpn_be_protocol", "string"),
        Column("alpn_client_preference_list", "string"),
        Column("tls_connection_creation_time", "timestamp"),
    ],
    _nlb,
    required=21,
)

# --- Classic Load Balancer ---------------------------------------------------------------------

_ELB_FIELDS = [
    "time",
    "elb",
    "client",
    "backend",
    "request_processing_time",
    "backend_processing_time",
    "response_processing_time",
    "elb_status_code",
    "backend_status_code",
    "received_bytes",
    "sent_bytes",
    "request",
    "user_agent",
    "ssl_cipher",
    "ssl_protocol",
]


def _elb(f: dict[str, str | None], ctx: FileContext) -> dict[str, Any]:
    row: dict[str, Any] = {"timestamp": utc(f["time"]), "elb": f["elb"]}
    _endpoint(row, "client", f["client"])
    _endpoint(row, "backend", f["backend"])
    for k in _ELB_FIELDS[4:11]:
        row[k] = f[k]
    row.update(
        request=f["request"],
        **request_parts(f["request"]),
        user_agent=f["user_agent"],
        ssl_cipher=f["ssl_cipher"],
        ssl_protocol=f["ssl_protocol"],
    )
    return row


ELB = TokenFormat(
    "aws_elb",
    "AWS Classic Load Balancer access log",
    GROUP,
    _ELB_FIELDS,
    [
        Column("timestamp", "timestamp"),
        Column("elb", "string"),
        Column("client_ip", "string"),
        Column("client_port", "integer"),
        Column("backend_ip", "string"),
        Column("backend_port", "integer"),
        Column("request_processing_time", "float"),
        Column("backend_processing_time", "float"),
        Column("response_processing_time", "float"),
        Column("elb_status_code", "integer"),
        Column("backend_status_code", "integer"),
        Column("received_bytes", "integer"),
        Column("sent_bytes", "integer"),
        Column("request", "string"),
        Column("method", "string"),
        Column("url", "string"),
        Column("protocol", "string"),
        Column("user_agent", "string"),
        Column("ssl_cipher", "string"),
        Column("ssl_protocol", "string"),
    ],
    _elb,
    # A TCP listener's line ends at the bytes sent; the request and TLS fields are HTTP(S)'s.
    required=11,
)

# --- CloudFront standard logs ------------------------------------------------------------------


class CloudFront(W3C):
    """CloudFront standard (access) logs: W3C extended, tab-separated, with ``#Fields`` naming
    the columns of each file."""

    name, label, group = "aws_cloudfront", "Amazon CloudFront standard log", GROUP
    separator = "\t"


# --- S3 server access logs ---------------------------------------------------------------------

_S3_FIELDS = [
    "bucket_owner",
    "bucket",
    "time",
    "remote_ip",
    "requester",
    "request_id",
    "operation",
    "key",
    "request_uri",
    "http_status",
    "error_code",
    "bytes_sent",
    "object_size",
    "total_time",
    "turn_around_time",
    "referer",
    "user_agent",
    "version_id",
    "host_id",
    "signature_version",
    "cipher_suite",
    "authentication_type",
    "host_header",
    "tls_version",
    "access_point_arn",
    "acl_required",
]


def _s3(f: dict[str, str | None], ctx: FileContext) -> dict[str, Any]:
    row: dict[str, Any] = dict(f)
    row.pop("time")
    row["timestamp"] = utc(f["time"], "%d/%b/%Y:%H:%M:%S %z")
    row.update(request_parts(f["request_uri"]))
    return row


S3 = TokenFormat(
    "aws_s3_access",
    "Amazon S3 server access log",
    GROUP,
    _S3_FIELDS,
    [
        Column("timestamp", "timestamp"),
        *[
            Column(
                f,
                "integer"
                if f
                in ("http_status", "bytes_sent", "object_size", "total_time", "turn_around_time")
                else "string",
            )
            for f in _S3_FIELDS
            if f != "time"
        ],
        Column("method", "string"),
        Column("url", "string"),
        Column("protocol", "string"),
    ],
    _s3,
    # Older logs end at the user agent or the version id; the later fields came one by one.
    required=17,
)

# --- VPC Flow Logs -----------------------------------------------------------------------------

#: Version 2, the default format, when a file names no fields of its own.
_VPC_DEFAULT = (
    "version account-id interface-id srcaddr dstaddr srcport dstport protocol packets bytes "
    "start end action log-status"
).split()
_VPC_TIMES = {"start", "end", "flow-direction-start", "flow-direction-end"}
_VPC_HEADER = "version "


class VpcFlow(W3C):
    """VPC Flow Logs of any version: a file delivered to S3 names its fields on its first line
    (``version account-id ...``); a file that does not is in the default version 2 form. ``-`` is
    no value (a NODATA or SKIPDATA record's); start and end are epoch seconds."""

    name, label, group = "aws_vpc_flow", "Amazon VPC Flow Logs", GROUP
    header_prefix = _VPC_HEADER
    separator = None

    def _header_fields(self, preview: list[str]) -> list[str]:
        for line in preview:
            if line.startswith(_VPC_HEADER):
                return line.split()
        return list(_VPC_DEFAULT)

    def columns(self, preview: list[str]) -> list[Column]:
        fields = self._header_fields(preview)
        values: dict[str, list[str]] = {f: [] for f in fields}
        for line in preview:
            if not line or line.startswith(_VPC_HEADER):
                continue
            for f, v in zip(fields, line.split()):
                values[f].append("" if v == "-" else v)
        return [
            Column(_column_name(f), "timestamp" if f in _VPC_TIMES else infer_type(values[f]))
            for f in fields
        ] + [Column("extra", "json")]

    def on_header(self, line: str, ctx: FileContext) -> None:
        ctx.fields = line.split()

    def parse(self, record: str, ctx: FileContext) -> dict[str, Any]:
        if not ctx.fields:
            ctx.fields = list(_VPC_DEFAULT)
        row = super().parse(record, ctx)
        for t in _VPC_TIMES:
            col = _column_name(t)
            if col in row:
                row[col] = epoch(row[col])
        return row


# --- CloudTrail --------------------------------------------------------------------------------


def _cloudtrail(row: dict[str, Any], doc: dict[str, Any]) -> dict[str, Any]:
    row["event_time"] = utc(row["event_time"])
    return row


CLOUDTRAIL = BatchJsonFormat(
    "aws_cloudtrail",
    "AWS CloudTrail log",
    GROUP,
    "Records",
    [
        (Column("event_time", "timestamp"), "eventTime"),
        (Column("event_version", "string"), "eventVersion"),
        (Column("event_source", "string"), "eventSource"),
        (Column("event_name", "string"), "eventName"),
        (Column("aws_region", "string"), "awsRegion"),
        (Column("source_ip_address", "string"), "sourceIPAddress"),
        (Column("user_agent", "string"), "userAgent"),
        (Column("user_type", "string"), "userIdentity.type"),
        (Column("user_arn", "string"), "userIdentity.arn"),
        (Column("user_account_id", "string"), "userIdentity.accountId"),
        (Column("user_identity", "json"), "userIdentity"),
        (Column("error_code", "string"), "errorCode"),
        (Column("error_message", "string"), "errorMessage"),
        (Column("request_parameters", "json"), "requestParameters"),
        (Column("response_elements", "json"), "responseElements"),
        (Column("request_id", "string"), "requestID"),
        (Column("event_id", "string"), "eventID"),
        (Column("read_only", "boolean"), "readOnly"),
        (Column("event_type", "string"), "eventType"),
        (Column("management_event", "boolean"), "managementEvent"),
        (Column("recipient_account_id", "string"), "recipientAccountId"),
        (Column("event_category", "string"), "eventCategory"),
    ],
    _cloudtrail,
)

# --- WAF ---------------------------------------------------------------------------------------


def _waf(row: dict[str, Any], doc: dict[str, Any]) -> dict[str, Any]:
    row["timestamp"] = epoch(row["timestamp"], millis=True)
    return row


WAF = JsonFormat(
    "aws_waf",
    "AWS WAF log",
    GROUP,
    [
        (Column("timestamp", "timestamp"), "timestamp"),
        (Column("format_version", "integer"), "formatVersion"),
        (Column("webacl_id", "string"), "webaclId"),
        (Column("terminating_rule_id", "string"), "terminatingRuleId"),
        (Column("terminating_rule_type", "string"), "terminatingRuleType"),
        (Column("action", "string"), "action"),
        (Column("http_source_name", "string"), "httpSourceName"),
        (Column("http_source_id", "string"), "httpSourceId"),
        (Column("client_ip", "string"), "httpRequest.clientIp"),
        (Column("country", "string"), "httpRequest.country"),
        (Column("uri", "string"), "httpRequest.uri"),
        (Column("args", "string"), "httpRequest.args"),
        (Column("http_version", "string"), "httpRequest.httpVersion"),
        (Column("http_method", "string"), "httpRequest.httpMethod"),
        (Column("request_id", "string"), "httpRequest.requestId"),
        (Column("http_request", "json"), "httpRequest"),
        (Column("rule_group_list", "json"), "ruleGroupList"),
        (Column("non_terminating_matching_rules", "json"), "nonTerminatingMatchingRules"),
        (Column("labels", "json"), "labels"),
    ],
    _waf,
)

# --- Route 53 Resolver query logs --------------------------------------------------------------


def _route53(row: dict[str, Any], doc: dict[str, Any]) -> dict[str, Any]:
    row["query_timestamp"] = utc(row["query_timestamp"])
    return row


ROUTE53 = JsonFormat(
    "aws_route53_resolver",
    "Amazon Route 53 Resolver query log",
    GROUP,
    [
        (Column("query_timestamp", "timestamp"), "query_timestamp"),
        (Column("version", "string"), "version"),
        (Column("account_id", "string"), "account_id"),
        (Column("region", "string"), "region"),
        (Column("vpc_id", "string"), "vpc_id"),
        (Column("query_name", "string"), "query_name"),
        (Column("query_type", "string"), "query_type"),
        (Column("query_class", "string"), "query_class"),
        (Column("rcode", "string"), "rcode"),
        (Column("answers", "json"), "answers"),
        (Column("srcaddr", "string"), "srcaddr"),
        (Column("srcport", "integer"), "srcport"),
        (Column("transport", "string"), "transport"),
        (Column("srcids", "json"), "srcids"),
        (Column("firewall_rule_action", "string"), "firewall_rule_action"),
    ],
    _route53,
)

PRESETS: list[Format] = [
    ALB,
    NLB,
    ELB,
    CloudFront(),
    S3,
    CLOUDTRAIL,
    VpcFlow(),
    WAF,
    ROUTE53,
]
