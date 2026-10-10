# Copyright (c) 2026 Kenneth Stott
# Canary: 64242961-276b-4b26-b980-082c87845157
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.

"""The Microsoft 365 mail reader: Graph's answers become rows of the canonical mail tables,
column for column; a collection is read to its end; a throttled call is waited out within a
bound and otherwise fails by name; an enumeration value Graph's table does not list fails the
read. Graph is a stand-in answering in the forms Microsoft's reference documents."""

from __future__ import annotations

from urllib.parse import parse_qs, urlencode, urlsplit

import pyarrow as pa
import pytest

from provisa.core import canonical_mail as cm
from provisa.core.ir_arrow import arrow_schema, rows_to_batch
from provisa.microsoft365 import mail
from provisa.microsoft365.graph import (
    BASE_URL,
    Answer,
    Graph,
    GraphRefused,
    GraphThrottled,
)

ACCOUNT = "Megan@Contoso.com"
ROOT = "/users/Megan@Contoso.com"


def _person(name: str, address: str) -> dict:
    return {"emailAddress": {"name": name, "address": address}}


def _message(n: int, **over) -> dict:
    item = {
        "@odata.etag": 'W/"x"',
        "id": f"m{n}",
        "conversationId": "c1",
        "conversationIndex": "AQHa",
        "internetMessageId": f"<{n}@contoso.com>",
        "subject": f"Subject {n}",
        "bodyPreview": f"Preview {n}",
        "from": _person("Dana Swope", "danas@contoso.com"),
        "sender": _person("Dana Swope", "danas@contoso.com"),
        "toRecipients": [_person("Megan", "megan@contoso.com"), _person("Sam", "sam@x.org")],
        "ccRecipients": [],
        "bccRecipients": [],
        "replyTo": [],
        "sentDateTime": f"2026-01-0{n}T10:00:00Z",
        "receivedDateTime": f"2026-01-0{n}T10:00:05Z",
        "createdDateTime": f"2026-01-0{n}T10:00:05Z",
        "lastModifiedDateTime": f"2026-01-0{n}T11:00:00Z",
        "isRead": True,
        "isDraft": False,
        "flag": {"flagStatus": "notFlagged"},
        "importance": "normal",
        "hasAttachments": False,
        "parentFolderId": "f-inbox",
        "categories": ["Blue"],
        "inferenceClassification": "focused",
        "isReadReceiptRequested": False,
        "isDeliveryReceiptRequested": False,
        "body": {"contentType": "text", "content": f"Text {n}"},
        "internetMessageHeaders": [
            {"name": "In-Reply-To", "value": "<0@contoso.com>"},
            {"name": "References", "value": "<a@contoso.com> <0@contoso.com>"},
        ],
        "changeKey": "CQAAAB",
        "webLink": "https://outlook.office365.com/owa/?ItemID=m",
    }
    item.update(over)
    return item


class FakeGraph:
    """Answers GETs from a table of path -> pages (a list of ``value`` lists) or one object,
    and ``$batch`` by answering each request in it from the same table."""

    def __init__(self, table: dict) -> None:
        self.table = table
        self.calls: list[tuple[str, str, dict, dict]] = []
        self.queued: list[Answer] = []  # answers given before the table is consulted
        #: delta path -> the items a round started from a kept link gives (changes since).
        self.since: dict[str, list] = {}
        #: delta path -> the whole body a followed link answers with, when a test states it.
        self.answers: dict[str, object] = {}
        #: delta paths whose kept link Graph no longer honours.
        self.gone: set[str] = set()
        #: The mailbox's messages as they are now (pages), where a test changes them after a
        #: first read; None while they are as the table states them.
        self.now: list | None = None

    def _folders_of(self, root: str) -> list[dict]:
        """The mailbox's folders: the ones the table lists, or, where it lists none, one for
        each folder its messages say they are in."""
        if f"{root}/mailFolders" in self.table:
            return [f for page in self.table[f"{root}/mailFolders"] for f in page]
        messages = [m for page in self.table.get(f"{root}/messages", []) for m in page]
        return [{"id": i} for i in dict.fromkeys(m["parentFolderId"] for m in messages)]

    def _tracked(self, path: str) -> list | None:
        """What a delta path gives on its first round: its own entry in the table, else what
        the mailbox's ``/messages`` and ``/mailFolders`` entries say (so a table written for
        one listing of the mailbox also answers its folder-by-folder reading)."""
        if path in self.table:
            return self.table[path]
        if path.endswith("/mailFolders/delta"):
            return [self._folders_of(path.removesuffix("/mailFolders/delta"))]
        if path.endswith("/messages/delta") and "/mailFolders/" in path:
            root, folder = path.removesuffix("/messages/delta").split("/mailFolders/")
            pages = [
                [m for m in page if m["parentFolderId"] == folder]
                for page in self.table.get(f"{root}/messages", [])
            ]
            return [page for page in pages if page] or [[]]
        return None

    def _one(self, url: str) -> tuple[int, object]:
        parts = urlsplit(url)
        path = parts.path.removeprefix("/v1.0")
        query = parse_qs(parts.query)
        if path.endswith("/delta"):
            if path in self.gone and "$deltatoken" in query:  # a first round is always given
                return 410, {"error": {"code": "SyncStateNotFound", "message": "expired"}}
            if "$deltatoken" in query and path in self.answers:
                return 200, self.answers[path]  # a followed link's answer, as a test gives it
            if "$deltatoken" in query:
                # What changed since the link was given: nothing, unless a test says so.
                changed = self.since.get(path, [])
                return 200, {
                    "value": changed,
                    "@odata.deltaLink": f"{BASE_URL}{path}?$deltatoken=again",
                }
            answer = self._tracked(path)
        elif path not in self.table and path.endswith("/mailFolders"):
            folders = self._folders_of(path.removesuffix("/mailFolders"))
            answer = [folders] if folders else None
        elif path.endswith("/messages") and "$filter" in query:
            # The messages of one conversation, as the mailbox holds them now.
            wanted = query["$filter"][0].removeprefix("conversationId eq '").removesuffix("'")
            held = self.now if self.now is not None else self.table.get(path, [])
            answer = [[m for page in held for m in page if m["conversationId"] == wanted]]
        else:
            answer = self.table.get(path)
        if answer is None:
            return 404, {"error": {"code": "ErrorItemNotFound", "message": "not found"}}
        if isinstance(answer, list):
            page = int(query.get("$skiptoken", ["0"])[0])
            body: dict = {"value": answer[page]}
            if page + 1 < len(answer):
                body["@odata.nextLink"] = f"{BASE_URL}{path}?$skiptoken={page + 1}"
            elif path.endswith("/delta"):
                body["@odata.deltaLink"] = f"{BASE_URL}{path}?$deltatoken=first"
            return 200, body
        return 200, answer

    def send(self, method, url, params, headers, body) -> Answer:
        self.calls.append((method, url, dict(params or {}), dict(headers)))
        if self.queued:
            return self.queued.pop(0)
        if method == "POST":
            responses = []
            for request in body["requests"]:
                status, answer = self._one(BASE_URL + request["url"])
                responses.append({"id": request["id"], "status": status, "body": answer})
            return Answer(200, {}, {"responses": list(reversed(responses))})
        if params and "$filter" in params:
            url += ("&" if "?" in url else "?") + urlencode(params)
        status, answer = self._one(url)
        return Answer(status, {}, answer)


def _rounds(fake: FakeGraph) -> list[tuple[str, str, dict, dict]]:
    """The requests that read a folder's messages (its delta rounds), in order."""
    return [
        c for c in fake.calls if c[0] == "GET" and urlsplit(c[1]).path.endswith("/messages/delta")
    ]


def _graph(table: dict, **kw) -> tuple[Graph, FakeGraph, list[float]]:
    fake, slept = FakeGraph(table), []
    return Graph(fake.send, lambda: "access-token", sleep=slept.append, **kw), fake, slept


def _mailbox(table: dict, **kw) -> tuple[mail.Mailbox, FakeGraph]:
    graph, fake, _ = _graph(table)
    return mail.Mailbox(graph, ACCOUNT, **kw), fake


def _all(mailbox: mail.Mailbox, table: str) -> list[dict]:
    return [row for batch in mailbox.rows(table) for row in batch]


def _html(*numbers: int) -> dict:
    return {
        f"{ROOT}/messages/m{n}": {"body": {"contentType": "html", "content": f"<p>{n}</p>"}}
        for n in numbers
    }


# ------------------------------------------------------------------------------ the tables


@pytest.mark.parametrize("table", mail.MAIL_TABLES)
def test_every_row_has_exactly_the_canonical_columns_and_lands_as_them(table):
    """The loader's output schema is the canonical one, column for column, and its values are
    ones the replica write face takes for those types."""
    source = {
        f"{ROOT}/messages": [[_message(1, hasAttachments=True), _message(2)]],
        **_html(1, 2),
        f"{ROOT}/mailFolders": [
            [{"id": "f-inbox", "displayName": "Inbox", "childFolderCount": 0, "isHidden": False}]
        ],
        f"{ROOT}/mailFolders/inbox": {"id": "f-inbox"},
        f"{ROOT}/messages/m1/attachments": [
            [
                {
                    "@odata.type": "#microsoft.graph.fileAttachment",
                    "id": "a1",
                    "name": "plan.pdf",
                    "contentType": "application/pdf",
                    "size": 2048,
                    "isInline": False,
                    "lastModifiedDateTime": "2026-01-01T10:00:00Z",
                }
            ]
        ],
    }
    mailbox, _ = _mailbox(source)
    rows = _all(mailbox, table)
    assert rows
    columns = cm.ir_columns(table)
    for row in rows:
        assert list(row) == [name for name, _ in columns]
        assert (row["provider"], row["account"]) == ("microsoft", "megan@contoso.com")
    batch = rows_to_batch(rows, columns, arrow_schema(columns))
    assert batch.schema == arrow_schema(columns)
    assert batch.num_rows == len(rows)


def test_a_message_row():
    mailbox, fake = _mailbox({f"{ROOT}/messages": [[_message(1)]], **_html(1)})
    (row,) = _all(mailbox, "messages")
    assert row["id"] == "m1" and row["thread_id"] == "c1"
    assert row["from_address"] == "danas@contoso.com" and row["from_name"] == "Dana Swope"
    assert row["to_addresses"] == ["megan@contoso.com", "sam@x.org"]
    assert row["cc_addresses"] == []
    assert row["in_reply_to"] == "<0@contoso.com>"
    assert row["reference_ids"] == ["<a@contoso.com>", "<0@contoso.com>"]
    assert row["flag_status"] == "none" and row["is_flagged"] is False
    assert row["importance"] == "normal" and row["inference_classification"] == "focused"
    assert row["folder_ids"] == ["f-inbox"]
    assert row["body_text"] == "Text 1" and row["body_html"] == "<p>1</p>"
    assert row["received_at"] == "2026-01-01T10:00:05Z"
    # Columns Microsoft has no value for are None, never an empty stand-in.
    assert row["size_bytes"] is None and row["classification_labels"] is None
    # The folder's messages are read as the first round of its change tracking: the page
    # size is the header Graph takes it by there, and what is selected rides in the link.
    listing = _rounds(fake)[0]
    assert "$top" not in listing[2] and "internetMessageHeaders" in listing[2]["$select"]
    assert listing[3]["Prefer"] == (
        'IdType="ImmutableId", odata.maxpagesize=50, outlook.body-content-type="text"'
    )
    assert listing[3]["Authorization"] == "Bearer access-token"


def test_a_flagged_message_carries_its_flag_times_in_utc():
    flag = {
        "flagStatus": "flagged",
        "startDateTime": {"dateTime": "2026-01-05T08:00:00.0000000", "timeZone": "UTC"},
        "dueDateTime": {"dateTime": "2026-01-06T08:00:00.0000000", "timeZone": "UTC"},
    }
    mailbox, _ = _mailbox({f"{ROOT}/messages": [[_message(1, flag=flag)]], **_html(1)})
    (row,) = _all(mailbox, "messages")
    assert row["is_flagged"] is True and row["flag_status"] == "flagged"
    assert row["flag_start_at"] == "2026-01-05T08:00:00.000000+00:00"
    assert row["flag_completed_at"] is None
    columns = cm.ir_columns("messages")
    landed = rows_to_batch([row], columns, arrow_schema(columns))
    assert landed.schema.field("flag_due_at").type == pa.timestamp("us")


def test_a_flag_time_in_another_zone_is_refused():
    flag = {
        "flagStatus": "flagged",
        "startDateTime": {
            "dateTime": "2026-01-05T08:00:00.0000000",
            "timeZone": "Pacific Standard Time",
        },
    }
    mailbox, _ = _mailbox({f"{ROOT}/messages": [[_message(1, flag=flag)]], **_html(1)})
    with pytest.raises(mail.UnexpectedAnswer, match="Pacific Standard Time"):
        _all(mailbox, "messages")


def test_an_importance_graphs_table_does_not_list_fails_the_read_by_name():
    mailbox, _ = _mailbox({f"{ROOT}/messages": [[_message(1, importance="urgent")]], **_html(1)})
    with pytest.raises(cm.UnmappedValue, match="'urgent'.*'importance'"):
        _all(mailbox, "messages")


def test_a_body_not_in_the_form_asked_for_is_refused():
    wrong = _message(1, body={"contentType": "html", "content": "<p>x</p>"})
    mailbox, _ = _mailbox({f"{ROOT}/messages": [[wrong]], **_html(1)})
    with pytest.raises(mail.UnexpectedAnswer, match="text was asked for"):
        _all(mailbox, "messages")


def test_messages_are_read_to_the_last_page_and_html_bodies_match_their_messages():
    pages = [[_message(1), _message(2)], [_message(3)]]
    mailbox, fake = _mailbox({f"{ROOT}/messages": pages, **_html(1, 2, 3)}, page_size=2)
    rows = _all(mailbox, "messages")
    assert [(r["id"], r["body_html"]) for r in rows] == [
        ("m1", "<p>1</p>"),
        ("m2", "<p>2</p>"),
        ("m3", "<p>3</p>"),
    ]
    follow = _rounds(fake)[1]
    assert follow[1].endswith("$skiptoken=1") and follow[2] == {}  # the next link, as given


def test_recipient_rows_name_each_person_in_order():
    mailbox, _ = _mailbox({f"{ROOT}/messages": [[_message(1)]]})
    rows = _all(mailbox, "message_recipients")
    assert [(r["kind"], r["position"], r["address"], r["name"]) for r in rows] == [
        ("from", 1, "danas@contoso.com", "Dana Swope"),
        ("sender", 1, "danas@contoso.com", "Dana Swope"),
        ("to", 1, "megan@contoso.com", "Megan"),
        ("to", 2, "sam@x.org", "Sam"),
    ]


def test_message_folders_has_one_row_a_message():
    mailbox, _ = _mailbox({f"{ROOT}/messages": [[_message(1), _message(2, parentFolderId="f2")]]})
    assert [(r["message_id"], r["folder_id"]) for r in _all(mailbox, "message_folders")] == [
        ("m1", "f-inbox"),
        ("m2", "f2"),
    ]


def test_threads_are_derived_from_the_messages():
    items = [
        _message(2),
        _message(1),
        _message(3, conversationId="c2", subject="Other", bodyPreview="Only"),
    ]
    mailbox, _ = _mailbox({f"{ROOT}/messages": [items]})
    rows = {r["id"]: r for r in _all(mailbox, "threads")}
    assert rows["c1"]["subject"] == "Subject 1"  # the earliest message's
    assert rows["c1"]["snippet"] == "Preview 2"  # the latest message's
    assert rows["c1"]["message_count"] == 2
    assert rows["c1"]["first_message_at"] == "2026-01-01T10:00:05Z"
    assert rows["c1"]["last_message_at"] == "2026-01-02T10:00:05Z"
    assert rows["c2"]["message_count"] == 1


def test_folders_walk_the_tree_and_take_their_role_from_the_well_known_names():
    def folder(fid, name, children=0, parent="root"):
        return {
            "id": fid,
            "displayName": name,
            "parentFolderId": parent,
            "childFolderCount": children,
            "isHidden": False,
            "totalItemCount": 3,
            "unreadItemCount": 1,
        }

    source = {
        f"{ROOT}/mailFolders": [
            [folder("f-inbox", "Posteingang", children=1), folder("f-sent", "Gesendet")],
            [folder("f-conv", "Aufgezeichnete Unterhaltungen")],
        ],
        f"{ROOT}/mailFolders/f-inbox/childFolders": [
            [folder("f-proj", "Projekt", parent="f-inbox")]
        ],
        f"{ROOT}/mailFolders/inbox": {"id": "f-inbox"},
        f"{ROOT}/mailFolders/sentitems": {"id": "f-sent"},
        f"{ROOT}/mailFolders/conversationhistory": {"id": "f-conv"},
    }
    mailbox, fake = _mailbox(source)
    rows = {r["id"]: r for r in _all(mailbox, "folders")}
    assert (rows["f-inbox"]["kind"], rows["f-inbox"]["role"]) == ("system", "inbox")
    assert (rows["f-sent"]["kind"], rows["f-sent"]["role"]) == ("system", "sent")
    # A well-known folder the role table does not list: the declared catch-all.
    assert (rows["f-conv"]["kind"], rows["f-conv"]["role"]) == ("system", "other")
    assert (rows["f-proj"]["kind"], rows["f-proj"]["role"]) == ("user", None)
    assert rows["f-proj"]["parent_id"] == "f-inbox" and rows["f-inbox"]["child_count"] == 1
    assert rows["f-inbox"]["threads_total"] is None  # Google's
    (lookup,) = [c for c in fake.calls if c[0] == "POST"]
    assert lookup  # each name is asked for in that one batch; one the mailbox lacks is skipped
    top = next(c for c in fake.calls if c[1] == BASE_URL + ROOT + "/mailFolders")
    assert top[2]["includeHiddenFolders"] == "true"


def test_attachments_are_listed_for_the_messages_that_have_them():
    source = {
        f"{ROOT}/messages": [[_message(1, hasAttachments=True), _message(2)]],
        f"{ROOT}/messages/m1/attachments": [
            [
                {
                    "@odata.type": "#microsoft.graph.fileAttachment",
                    "id": "a1",
                    "name": "plan.pdf",
                    "contentType": "application/pdf",
                    "size": 2048,
                    "isInline": False,
                    "lastModifiedDateTime": "2026-01-01T10:00:00Z",
                },
                {"@odata.type": "#microsoft.graph.itemAttachment", "id": "a2", "name": "Fwd"},
            ]
        ],
    }
    mailbox, fake = _mailbox(source)
    rows = _all(mailbox, "attachments")
    assert [(r["message_id"], r["id"], r["kind"], r["size_bytes"]) for r in rows] == [
        ("m1", "a1", "file", 2048),
        ("m1", "a2", "item", None),
    ]
    listed = [c for c in fake.calls if c[1].endswith("/attachments")]
    assert len(listed) == 1 and "contentBytes" not in listed[0][2]["$select"]


def test_an_attachment_kind_graphs_table_does_not_list_fails_the_read():
    source = {
        f"{ROOT}/messages": [[_message(1, hasAttachments=True)]],
        f"{ROOT}/messages/m1/attachments": [
            [{"@odata.type": "#microsoft.graph.newKind", "id": "a"}]
        ],
    }
    mailbox, _ = _mailbox(source)
    with pytest.raises(cm.UnmappedValue, match="attachment_kind"):
        _all(mailbox, "attachments")


def test_a_table_that_is_not_a_mail_table_is_refused():
    mailbox, _ = _mailbox({})
    with pytest.raises(KeyError, match="not a Microsoft 365 mail table"):
        _all(mailbox, "events")


def test_a_row_cannot_carry_a_column_microsoft_does_not_populate():
    with pytest.raises(KeyError, match="not a column Microsoft populates"):
        mail._row("messages", "a@b.c", size_bytes=1)
    with pytest.raises(KeyError, match="no column"):
        mail._row("messages", "a@b.c", nonsense=1)


# ---------------------------------------------------------------------------------- Graph


def _throttled(seconds: str | None) -> Answer:
    headers = {} if seconds is None else {"Retry-After": seconds}
    return Answer(429, headers, {"error": {"code": "TooManyRequests", "message": "later"}})


def test_a_throttled_call_waits_as_long_as_graph_asks_and_goes_on():
    graph, fake, slept = _graph({"/x": [[{"id": 1}], [{"id": 2}]]})
    fake.queued = [_throttled("7"), _throttled("3")]
    assert [p for p in graph.pages("/x")] == [[{"id": 1}], [{"id": 2}]]
    assert slept == [7.0, 3.0]


def test_a_call_throttled_past_the_bound_fails_by_name_with_no_part_of_the_answer():
    graph, fake, slept = _graph({"/x": [[{"id": 1}], [{"id": 2}]]}, wait_seconds=10.0)
    got = []
    pages = graph.pages("/x")
    got.append(next(pages))
    fake.queued = [_throttled("6"), _throttled("6")]
    with pytest.raises(GraphThrottled, match="Retry-After: 6") as refused:
        got.append(next(pages))
    assert slept == [6.0] and refused.value.retry_after == "6"
    assert "skiptoken" not in str(refused.value)  # the paging token is not in the message


def test_a_wait_of_87_seconds_is_waited_out_under_the_builds_bound_and_the_read_goes_on():
    """From a live build: Graph asked for 87 s and the read was refused having waited 0 s of
    the 60 s a call may. A replica's build takes the operator's bound (15 minutes unless it
    is changed), waits as asked, and reads on."""
    from provisa.core import settings_registry

    setting = settings_registry.setting("mail.throttle_wait_seconds")
    assert (setting.type, setting.effect, setting.default, setting.unit) == (
        "int",
        "live",
        900,
        "seconds",
    )
    graph, fake, slept = _graph(
        {"/x": [[{"id": 1}], [{"id": 2}]]}, wait_seconds=float(setting.default)
    )
    fake.queued = [_throttled("87")]
    assert [p for p in graph.pages("/x")] == [[{"id": 1}], [{"id": 2}]]
    assert slept == [87.0]


def test_a_wait_past_the_bound_fails_by_name_and_says_what_to_change():
    graph, fake, slept = _graph({"/x": {"id": 1}}, wait_seconds=900.0)
    fake.queued = [_throttled("901")]
    with pytest.raises(GraphThrottled) as refused:
        graph.get("/x")
    said = str(refused.value)
    assert slept == [] and "Retry-After: 901" in said and "of the 900s it may" in said
    assert "Longest wait when a mail service is throttling" in said
    assert "Mailboxes read at once" in said


def test_whoever_watches_the_read_is_told_of_a_wait_and_of_its_end():
    told: list[float] = []
    fake = FakeGraph({"/x": {"id": 1}})
    graph = Graph(
        fake.send,
        lambda: "t",
        wait_seconds=900.0,
        sleep=lambda s: told.append(-s),
        waiting=told.append,
    )
    fake.queued = [_throttled("87")]
    graph.get("/x")
    assert told == [87.0, -87.0, 0.0]  # said, waited, said to be over


def test_a_throttled_request_of_a_batch_says_it_is_waiting_too():
    told: list[float] = []
    fake = FakeGraph({"/a": {"id": 1}})
    graph = Graph(fake.send, lambda: "t", sleep=lambda s: None, waiting=told.append)
    fake.queued = [
        Answer(
            200,
            {},
            {"responses": [{"id": "0", "status": 429, "headers": {"Retry-After": "30"}}]},
        )
    ]
    assert graph.batch(["/a"]) == [{"id": 1}]
    assert told == [30.0, 0.0]


def test_a_throttled_call_that_names_no_wait_fails_by_name():
    graph, fake, slept = _graph({"/x": {"id": 1}})
    fake.queued = [_throttled(None)]
    with pytest.raises(GraphThrottled):
        graph.get("/x")
    assert slept == []


def test_a_refusal_carries_graphs_code_and_no_token():
    graph, fake, _ = _graph({})
    fake.queued = [
        Answer(403, {}, {"error": {"code": "ErrorAccessDenied", "message": "Access is denied."}})
    ]
    with pytest.raises(GraphRefused, match="403 ErrorAccessDenied: Access is denied") as refused:
        graph.get("/users/a@b.c/messages")
    assert refused.value.code == "ErrorAccessDenied" and "access-token" not in str(refused.value)


def test_find_answers_none_only_for_an_item_graph_says_is_not_there():
    graph, fake, _ = _graph({})
    assert graph.find("/users/a@b.c/mailFolders/archive") is None
    fake.queued = [Answer(404, {}, {"error": {"code": "ResourceNotFound", "message": "no user"}})]
    with pytest.raises(GraphRefused, match="ResourceNotFound"):
        graph.find("/users/nobody@b.c/mailFolders/archive")


def test_a_batch_answers_in_the_order_asked_and_is_cut_at_graphs_limit():
    table = {f"/i/{n}": {"n": n} for n in range(45)}
    graph, fake, _ = _graph(table)
    answers = graph.batch([f"/i/{n}" for n in range(45)], prefer=("a=b",))
    assert [a["n"] for a in answers] == list(range(45))  # the stand-in answers in reverse
    posts = [c for c in fake.calls if c[0] == "POST"]
    assert len(posts) == 3 and all(c[1] == BASE_URL + "/$batch" for c in posts)


def test_a_throttled_request_of_a_batch_is_asked_again_alone():
    graph, fake, slept = _graph({"/i/0": {"n": 0}, "/i/1": {"n": 1}})
    fake.queued = [
        Answer(
            200,
            {},
            {
                "responses": [
                    {"id": "0", "status": 200, "body": {"n": 0}},
                    {"id": "1", "status": 429, "headers": {"Retry-After": "4"}, "body": {}},
                ]
            },
        )
    ]
    assert graph.batch(["/i/0", "/i/1"]) == [{"n": 0}, {"n": 1}]
    assert slept == [4.0]
    assert len(fake.calls) == 2


def test_a_refused_request_of_a_batch_fails_the_batch():
    graph, _, _ = _graph({"/i/0": {"n": 0}})
    with pytest.raises(GraphRefused, match="ErrorItemNotFound"):
        graph.batch(["/i/0", "/i/missing"])


def test_a_message_whose_html_body_graph_will_not_give_keeps_its_row(caplog):
    """The build completes: the row is kept with that body column None and the rest filled,
    and the count and ids are reported once when the table's read ends."""
    import logging

    source = {f"{ROOT}/messages": [[_message(1), _message(2)]], **_html(1)}  # no body for m2
    mailbox, _ = _mailbox(source)
    with caplog.at_level(logging.WARNING, logger="provisa.microsoft365.mail"):
        rows = _all(mailbox, "messages")
    assert [(r["id"], r["body_html"], r["body_text"]) for r in rows] == [
        ("m1", "<p>1</p>", "Text 1"),
        ("m2", None, "Text 2"),
    ]
    assert rows[1]["subject"] == "Subject 2"
    (record,) = caplog.records
    assert "1 message(s)" in record.getMessage() and "m2" in record.getMessage()
    assert "megan@contoso.com" in record.getMessage()


def test_batch_each_gives_each_request_its_answer_or_its_refusal():
    graph, _, _ = _graph({"/i/0": {"n": 0}})
    first, second = graph.batch_each(["/i/0", "/i/missing"])
    assert first == {"n": 0}
    assert isinstance(second, GraphRefused) and second.code == "ErrorItemNotFound"


# ------------------------------------------------------ one listing, every message table


def _mailbox_of_three() -> dict:
    return {
        f"{ROOT}/messages": [
            [_message(1, hasAttachments=True), _message(2)],
            [_message(3, conversationId="c2")],
        ],
        **_html(1, 2, 3),
        f"{ROOT}/messages/m1/attachments": [
            [{"@odata.type": "#microsoft.graph.fileAttachment", "id": "a1", "name": "x.pdf"}]
        ],
    }


def test_one_listing_of_the_mailbox_gives_every_message_table():
    mailbox, fake = _mailbox(_mailbox_of_three(), page_size=2)
    got: dict[str, list[dict]] = {}
    for table, rows in mailbox.message_tables(mail.MESSAGE_TABLES):
        got.setdefault(table, []).extend(rows)
    # The two pages of ONE reading of the mailbox's one folder; no table read it again.
    assert len(_rounds(fake)) == 2
    # Each table's rows are the ones it gives when read on its own.
    for table in mail.MESSAGE_TABLES:
        alone, _ = _mailbox(_mailbox_of_three(), page_size=2)
        assert got[table] == _all(alone, table), table
    assert set(got) == set(mail.MESSAGE_TABLES)


def test_a_group_read_without_messages_asks_for_no_bodies():
    mailbox, fake = _mailbox(_mailbox_of_three())
    tables = ("message_recipients", "message_folders", "threads")
    got = {table for table, _rows in mailbox.message_tables(tables)}
    assert got == set(tables)
    assert not [c for c in fake.calls if c[0] == "POST"]  # no HTML body was read
    assert "body" not in _rounds(fake)[0][2]["$select"].split(",")


def test_folders_do_not_come_from_the_messages():
    mailbox, _ = _mailbox({})
    with pytest.raises(KeyError, match="folders do not come from"):
        list(mailbox.message_tables(("messages", "folders")))


def test_a_group_read_names_the_messages_kept_without_a_body():
    source = {f"{ROOT}/messages": [[_message(1), _message(2)]], **_html(1)}
    mailbox, _ = _mailbox(source)
    unreadable: list[str] = []
    rows = [r for t, batch in mailbox.message_tables(("messages",), unreadable) for r in batch]
    assert [r["body_html"] for r in rows] == ["<p>1</p>", None] and unreadable == ["m2"]


# --- a read is made of delta rounds, and keeps where it reached ---

_INBOX, _SENT = "f-inbox", "f-sent"


def _two_folders() -> dict:
    return {
        f"{ROOT}/mailFolders": [[{"id": _INBOX}, {"id": _SENT}]],
        f"{ROOT}/messages": [
            [_message(1), _message(2, parentFolderId=_SENT)],
            [_message(3, parentFolderId=_SENT)],
        ],
        **_html(1, 2, 3),
    }


def test_every_folder_is_read_and_each_keeps_the_link_its_round_ended_with():
    mailbox, fake = _mailbox(_two_folders())
    assert mailbox.links is None  # nothing is kept before a read has ended
    rows = _all(mailbox, "messages")
    assert sorted(r["id"] for r in rows) == ["m1", "m2", "m3"]
    assert {r["id"]: r["folder_ids"] for r in rows}["m3"] == [_SENT]
    read = [urlsplit(c[1]).path.removeprefix("/v1.0") for c in _rounds(fake)]
    assert f"{ROOT}/mailFolders/{_INBOX}/messages/delta" in read
    assert f"{ROOT}/mailFolders/{_SENT}/messages/delta" in read
    assert mailbox.links is not None
    # One link for each folder, under the folder's id, and one for the list of folders.
    assert set(mailbox.links) == {_INBOX, _SENT, mail.MAILBOX}
    assert mailbox.links[_SENT].endswith(f"/mailFolders/{_SENT}/messages/delta?$deltatoken=first")
    assert mailbox.links[mail.MAILBOX].endswith("/mailFolders/delta?$deltatoken=first")


def test_a_message_met_in_two_folders_is_given_once_and_a_replayed_removal_is_not_a_message():
    moved = _message(2, parentFolderId=_SENT)
    table = {
        f"{ROOT}/mailFolders": [[{"id": _INBOX}, {"id": _SENT}]],
        f"{ROOT}/mailFolders/{_INBOX}/messages/delta": [
            [_message(1), moved, {"id": "m9", "@removed": {"reason": "deleted"}}]
        ],
        f"{ROOT}/mailFolders/{_SENT}/messages/delta": [[moved]],
    }
    mailbox, _ = _mailbox(table)
    assert [r["message_id"] for r in _all(mailbox, "message_folders")] == ["m1", "m2"]


def test_nothing_changed_while_every_link_answers_nothing():
    mailbox, fake = _mailbox(_two_folders())
    _all(mailbox, "messages")
    links = dict(mailbox.links or {})
    before = len(fake.calls)
    assert mailbox.changed(links) is False
    # Asked in one batch, one item each; the links are followed as kept.
    (asked,) = fake.calls[before:]
    assert asked[0] == "POST" and urlsplit(asked[1]).path.endswith("/$batch")
    assert mailbox.links == links  # asking keeps nothing


@pytest.mark.parametrize("where", [_INBOX, _SENT, "folders"])
def test_a_change_in_any_folder_or_in_the_list_of_folders_is_a_change(where):
    mailbox, fake = _mailbox(_two_folders())
    _all(mailbox, "messages")
    path = (
        f"{ROOT}/mailFolders/delta"
        if where == "folders"
        else f"{ROOT}/mailFolders/{where}/messages/delta"
    )
    # A removal counts: a message deleted or moved away is a change to the rows.
    fake.since[path] = [{"id": "m1", "@removed": {"reason": "deleted"}}]
    assert mailbox.changed(dict(mailbox.links or {})) is True


def test_a_link_graph_no_longer_honours_counts_as_changed_and_no_links_cannot_say_unchanged():
    mailbox, fake = _mailbox(_two_folders())
    _all(mailbox, "messages")
    gone = f"{BASE_URL}{ROOT}/mailFolders/f-gone/messages/delta?$deltatoken=old"
    fake.gone = {f"{ROOT}/mailFolders/f-gone/messages/delta"}
    assert mailbox.changed({**(mailbox.links or {}), "f-gone": gone}) is True
    assert mailbox.changed({}) is True


def test_a_kept_link_that_does_not_lead_to_graph_is_never_followed():
    mailbox, fake = _mailbox(_two_folders())
    before = len(fake.calls)
    with pytest.raises(ValueError, match="does not lead to Microsoft Graph"):
        mailbox.changed({_INBOX: "https://example.com/v1.0/users/x/messages/delta?$deltatoken=t"})
    assert fake.calls[before:] == []  # the access token went nowhere


_INBOX_DELTA = f"{ROOT}/mailFolders/{_INBOX}/messages/delta"
_AGAIN = f"{BASE_URL}{_INBOX_DELTA}?$deltatoken=again"


@pytest.mark.parametrize(
    ("body", "why"),
    [
        # Graph: "there are more pages of data to retrieve in the session, even if the current
        # response contains an empty result".
        ({"value": [], "@odata.nextLink": f"{BASE_URL}{_INBOX_DELTA}?$skiptoken=1"}, "more pages"),
        ({"value": []}, "the round did not end"),
        ({"@odata.deltaLink": _AGAIN}, "no value at all"),
        ({"value": None, "@odata.deltaLink": _AGAIN}, "a value that is not a list"),
        ({"error": {"code": "Something", "message": "inside a 200"}}, "an error in the body"),
        ("not an object", "not an object"),
    ],
)
def test_a_followed_link_says_unchanged_only_by_an_empty_page_that_ends_the_round(body, why):
    mailbox, fake = _mailbox(_two_folders())
    _all(mailbox, "messages")
    links = dict(mailbox.links or {})
    assert mailbox.changed(links) is False  # every link: no item, and the round ended
    fake.answers[_INBOX_DELTA] = body
    assert mailbox.changed(links) is True, why


# ------------------------------------------- a folder the mailbox does not have


def _refuses(fake: FakeGraph, where: str, code: str, *, only_tracked: bool = False) -> None:
    """Graph answers 404 ``code`` to every request whose path ends with ``where``."""
    one = fake._one

    def answering(url: str):
        path = urlsplit(url).path.removeprefix("/v1.0")
        if path.endswith(where):
            return 404, {
                "error": {"code": code, "message": "The specified folder could not be found."}
            }
        return one(url)

    fake._one = answering


def test_a_well_known_folder_the_mailbox_does_not_have_is_absent_not_a_refusal():
    """From a live build: a mailbox with no archive folder answered 404 ErrorFolderNotFound to
    the lookup of that name, and the whole mailbox was declared unreadable. Which well-known
    folders a mailbox has depends on the mailbox; one it lacks simply has no role to give."""
    table = {
        f"{ROOT}/mailFolders": [[{"id": _INBOX, "displayName": "Inbox"}]],
        f"{ROOT}/mailFolders/inbox": {"id": _INBOX},
    }
    mailbox, fake = _mailbox(table)
    _refuses(fake, "/mailFolders/archive", "ErrorFolderNotFound")
    (row,) = _all(mailbox, "folders")
    assert (row["id"], row["role"]) == (_INBOX, "inbox")


def test_the_well_known_names_are_asked_for_in_one_batch():
    table = {
        f"{ROOT}/mailFolders": [[{"id": _INBOX, "displayName": "Inbox"}]],
        f"{ROOT}/mailFolders/inbox": {"id": _INBOX},
    }
    mailbox, fake = _mailbox(table)
    _all(mailbox, "folders")
    lookups = [c for c in fake.calls if c[0] == "POST"]
    assert len(lookups) == 1  # not one call for each of Microsoft's seventeen names
    assert not any(
        c[0] == "GET" and c[1].rsplit("/", 1)[-1].split("?")[0] in mail.WELL_KNOWN_FOLDERS
        for c in fake.calls
    )


def test_a_well_known_lookup_graph_refuses_for_another_reason_still_fails_the_read():
    table = {f"{ROOT}/mailFolders": [[{"id": _INBOX, "displayName": "Inbox"}]]}
    mailbox, fake = _mailbox(table)
    one = fake._one

    def denied(url: str):
        if urlsplit(url).path.endswith("/mailFolders/inbox"):
            return 403, {"error": {"code": "ErrorAccessDenied", "message": "no"}}
        return one(url)

    fake._one = denied
    with pytest.raises(GraphRefused) as refused:
        _all(mailbox, "folders")
    assert refused.value.code == "ErrorAccessDenied"


def test_the_well_known_names_are_microsofts_own():
    """The names of Microsoft's "Well-known folder names" table (mailFolder resource type,
    Microsoft Graph v1.0), which a listing of folders does not give: v1.0 has no property
    that says a folder's role."""
    assert mail.WELL_KNOWN_FOLDERS == (
        "archive",
        "clutter",
        "conflicts",
        "conversationhistory",
        "deleteditems",
        "drafts",
        "inbox",
        "junkemail",
        "localfailures",
        "msgfolderroot",
        "outbox",
        "recoverableitemsdeletions",
        "scheduled",
        "searchfolders",
        "sentitems",
        "serverfailures",
        "syncissues",
    )


@pytest.mark.parametrize("code", ["ErrorFolderNotFound", "ErrorItemNotFound"])
def test_a_folder_removed_between_the_walk_and_its_read_is_skipped(code):
    """The folders are listed, then each is read. One removed in between answers 404 for its
    messages: its messages are no longer there to read, and the others' are."""
    mailbox, fake = _mailbox(_two_folders())
    _refuses(fake, f"/mailFolders/{_SENT}/messages/delta", code)
    rows = _all(mailbox, "messages")
    assert [r["id"] for r in rows] == ["m1"]
    assert mailbox.links is not None and _SENT not in mailbox.links


# ------------------------------------- no more than four requests for one mailbox


def test_three_readers_of_one_mailbox_never_have_more_than_four_requests_in_flight():
    """Microsoft allows an app four concurrent requests for one mailbox. The read of the
    messages, the read of the folders and the check for changes each read a mailbox on their
    own; together they passed four and were throttled. However many readers there are, and
    whether they ask one request or a batch (which Graph runs four at a time), the requests
    in flight for one mailbox stay at four or under, and another mailbox is not held up."""
    import threading
    import time as clock

    from provisa.microsoft365 import graph as graph_module

    guard = threading.Lock()
    flying = {"megan": 0, "sam": 0}
    most = {"megan": 0, "sam": 0}
    overlapped: list[bool] = []

    def send(method, url, params, headers, body) -> Answer:
        if url.endswith("/$batch"):
            who = body["requests"][0]["url"].split("/users/")[1].split("@")[0]
            weight = len(body["requests"])
        else:
            who, weight = url.split("/users/")[1].split("@")[0], 1
        with guard:
            flying[who] += weight
            most[who] = max(most[who], flying[who])
            overlapped.append(flying["megan"] > 0 and flying["sam"] > 0)
        clock.sleep(0.01)
        with guard:
            flying[who] -= weight
        if url.endswith("/$batch"):
            answers = [{"id": r["id"], "status": 200, "body": {"id": 1}} for r in body["requests"]]
            return Answer(200, {}, {"responses": answers})
        return Answer(200, {}, {"value": []})

    def messages(who: str) -> None:  # one request at a time
        client = Graph(send, lambda: "t")
        for _ in range(6):
            client.get(f"/users/{who}@contoso.com/mailFolders/inbox/messages")

    def folders(who: str) -> None:  # the well-known names, in a batch of four at a time
        client = Graph(send, lambda: "t")
        for _ in range(3):
            client.batch([f"/users/{who}@contoso.com/mailFolders/{n}" for n in "abcd"])

    def check(who: str) -> None:  # a batch of kept links
        client = Graph(send, lambda: "t")
        for _ in range(3):
            client.batch(
                [f"/users/{who}@contoso.com/mailFolders/f{n}/messages/delta" for n in "ab"]
            )

    readers = [
        threading.Thread(target=reader, args=(who,))
        for who in ("megan", "megan", "sam")
        for reader in (messages, folders, check)
    ]
    for reader in readers:
        reader.start()
    for reader in readers:
        reader.join(timeout=30)
    assert not any(reader.is_alive() for reader in readers)
    assert 1 < most["megan"] <= graph_module.MAILBOX_CONCURRENCY
    assert most["sam"] <= graph_module.MAILBOX_CONCURRENCY
    assert any(overlapped)  # one mailbox's readers did not hold another's up
    assert graph_module.MAILBOX_GATES.in_flight("megan@contoso.com") == 0  # all room given back
    assert graph_module.MAILBOX_CONCURRENCY == 4  # Microsoft's figure


def test_room_for_a_mailbox_is_given_back_when_a_request_fails_and_not_held_while_waiting():
    from provisa.microsoft365 import graph as graph_module

    held: list[int] = []

    def send(method, url, params, headers, body) -> Answer:
        held.append(graph_module.MAILBOX_GATES.in_flight("megan@contoso.com"))
        raise OSError("the connection dropped")

    with pytest.raises(OSError):
        Graph(send, lambda: "t").get("/users/Megan@Contoso.com/mailFolders")
    assert held == [1] and graph_module.MAILBOX_GATES.in_flight("megan@contoso.com") == 0

    slept: list[int] = []
    fake = FakeGraph({"/users/megan@contoso.com/x": {"id": 1}})
    fake.queued = [_throttled("5")]
    waiting = Graph(
        fake.send,
        lambda: "t",
        sleep=lambda s: slept.append(graph_module.MAILBOX_GATES.in_flight("megan@contoso.com")),
    )
    waiting.get("/users/megan@contoso.com/x")
    assert slept == [0]  # nothing is held across the wait Graph asked for


def test_a_request_for_no_one_mailbox_is_not_counted():
    from provisa.microsoft365.graph import _gated

    assert _gated(BASE_URL + "/users?$filter=x", None) == (None, 1)
    assert _gated(BASE_URL + "/groups/g/members", None) == (None, 1)
    assert _gated(BASE_URL + "/users/Megan%40Contoso.com/mailFolders", None) == (
        "megan@contoso.com",
        1,
    )
    batch = {"requests": [{"url": "/users/a@x.co/m/1"}, {"url": "/users/a@x.co/m/2"}]}
    assert _gated(BASE_URL + "/$batch", batch) == ("a@x.co", 2)


# ------------------------------------------------------------------ a read in units


def _units(mailbox: mail.Mailbox, kept=None, tables=mail.MESSAGE_TABLES) -> list[mail.Unit]:
    return list(mailbox.units(tables, kept))


def _links(units: list[mail.Unit]) -> dict[str, str]:
    return {scope: link for unit in units for scope, link in unit.links.items()}


def _mine(**key) -> dict:
    return {"provider": "microsoft", "account": ACCOUNT.lower(), **key}


def test_a_first_read_lands_a_page_at_a_time_each_message_with_its_dependants():
    mailbox, _ = _mailbox(_two_folders(), page_size=1)
    units = _units(mailbox)
    first, *pages = units
    # What the tables held of this mailbox is replaced by what is read now.
    assert first.forget and first.rows == {}
    assert first.removed == {table: [_mine()] for table in mail.MESSAGE_TABLES}
    landed = [u for u in pages if "messages" in u.rows]
    assert sorted(len(u.rows["messages"]) for u in landed) == [1, 1, 1]
    for unit in landed:
        (message,) = unit.rows["messages"]
        # A message never lands without its recipients and its folder: they are one unit.
        assert {r["message_id"] for r in unit.rows["message_recipients"]} == {message["id"]}
        assert [r["message_id"] for r in unit.rows["message_folders"]] == [message["id"]]
        assert unit.removed["message_recipients"] == [_mine(message_id=message["id"])]
        assert unit.links == {} and not unit.last
    assert sum(u.last for u in units) == 1 and units[-1].last


def test_a_folders_link_is_given_only_when_the_folder_has_been_read_to_its_end():
    mailbox, _ = _mailbox(_two_folders(), page_size=1)
    units = _units(mailbox)
    order = [
        ("link", next(iter(u.links))) if u.links else ("rows", u.rows["messages"][0]["id"])
        for u in units
        if u.links or "messages" in u.rows
    ]
    assert order == [
        ("rows", "m1"),
        ("link", _INBOX),
        ("rows", "m2"),
        ("rows", "m3"),
        ("link", _SENT),
        ("link", mail.MAILBOX),
    ]
    assert set(_links(units)) == {_INBOX, _SENT, mail.MAILBOX}


def test_the_threads_come_with_the_mailboxs_last_unit():
    mailbox, _ = _mailbox(_two_folders())
    last = _units(mailbox)[-1]
    assert last.last and last.links.keys() == {mail.MAILBOX}
    assert sum(row["message_count"] for row in last.rows["threads"]) == 3


def test_what_changed_since_is_one_unit_for_the_mailbox():
    mailbox, fake = _mailbox(_two_folders())
    kept = _links(_units(mailbox))
    changed = _message(2, parentFolderId=_SENT, subject="edited")
    new = _message(4)
    fake.since = {
        f"{ROOT}/mailFolders/{_SENT}/messages/delta": [changed],
        f"{ROOT}/mailFolders/{_INBOX}/messages/delta": [
            new,
            {"id": "m1", "@removed": {"reason": "deleted"}},
        ],
    }
    fake.table.update(_html(4))
    fake.now = [[changed, _message(3, parentFolderId=_SENT), new]]
    (unit,) = _units(mailbox, kept)
    assert unit.last and not unit.forget
    assert sorted(r["id"] for r in unit.rows["messages"]) == ["m2", "m4"]
    assert {r["id"]: r["subject"] for r in unit.rows["messages"]}["m2"] == "edited"
    # A changed message's dependants are replaced whole; a removed one's are removed.
    assert unit.removed["messages"] == [_mine(id="m1")]
    assert sorted(m["message_id"] for m in unit.removed["message_recipients"]) == [
        "m1",
        "m2",
        "m4",
    ]
    assert {r["message_id"] for r in unit.rows["message_recipients"]} == {"m2", "m4"}
    # Every folder's link moves on, and the list of folders' own.
    assert set(unit.links) == {_INBOX, _SENT, mail.MAILBOX}
    assert unit.links[_SENT].endswith("$deltatoken=again")


def test_a_message_moved_between_folders_is_changed_not_removed():
    """Graph says it is removed from one folder and gives it in the other. Whichever folder
    is asked first, the mailbox's one unit keeps the message."""
    mailbox, fake = _mailbox(_two_folders())
    kept = _links(_units(mailbox))
    moved = _message(1, parentFolderId=_SENT)
    fake.since = {
        f"{ROOT}/mailFolders/{_INBOX}/messages/delta": [
            {"id": "m1", "@removed": {"reason": "deleted"}}
        ],
        f"{ROOT}/mailFolders/{_SENT}/messages/delta": [moved],
    }
    fake.now = [[moved, _message(2, parentFolderId=_SENT), _message(3, parentFolderId=_SENT)]]
    (unit,) = _units(mailbox, kept)
    assert "messages" not in unit.removed
    assert [r["id"] for r in unit.rows["messages"]] == ["m1"]
    assert [(r["message_id"], r["folder_id"]) for r in unit.rows["message_folders"]] == [
        ("m1", _SENT)
    ]
    assert unit.removed["message_folders"] == [_mine(message_id="m1")]  # its old folder row


def test_a_thread_a_changed_message_is_in_is_worked_out_again_from_all_its_messages():
    mailbox, fake = _mailbox(_two_folders())
    kept = _links(_units(mailbox))
    thread = _message(1)["conversationId"]
    reply = _message(5, conversationId=thread)
    fake.since = {f"{ROOT}/mailFolders/{_INBOX}/messages/delta": [reply]}
    fake.table.update(_html(5))
    fake.now = [[_message(1), reply]]
    (unit,) = _units(mailbox, kept)
    (row,) = unit.rows["threads"]
    assert (row["id"], row["message_count"]) == (thread, 2)


def test_nothing_changed_is_a_unit_with_only_where_the_read_reached():
    mailbox, _ = _mailbox(_two_folders())
    kept = _links(_units(mailbox))
    (unit,) = _units(mailbox, kept)
    assert unit.last and set(unit.links) == set(kept)
    assert not any(unit.rows.values()) and not any(unit.removed.values())


def test_a_link_graph_no_longer_honours_reads_the_mailbox_again_from_its_start():
    mailbox, fake = _mailbox(_two_folders())
    kept = _links(_units(mailbox))
    fake.gone = {f"{ROOT}/mailFolders/{_SENT}/messages/delta"}
    units = _units(mailbox, kept)
    assert units[0].forget and units[0].removed["messages"] == [_mine()]
    assert sorted(r["id"] for u in units for r in u.rows.get("messages", [])) == ["m1", "m2", "m3"]


def test_a_folder_that_was_kept_and_is_no_longer_listed_reads_the_mailbox_again():
    mailbox, fake = _mailbox(_two_folders())
    kept = {**_links(_units(mailbox)), "a-folder-since-removed": "https://graph.microsoft.com/x"}
    units = _units(mailbox, kept)
    assert units[0].forget


def test_a_folder_met_for_the_first_time_is_read_whole_with_the_others_changes():
    mailbox, fake = _mailbox(_two_folders())
    kept = _links(_units(mailbox))
    del kept[_SENT]  # as if the folder was made since
    (unit,) = _units(mailbox, kept)
    assert sorted(r["id"] for r in unit.rows["messages"]) == ["m2", "m3"]


def test_units_come_only_from_the_message_tables():
    mailbox, _ = _mailbox(_two_folders())
    with pytest.raises(KeyError, match="do not come from a mailbox's messages"):
        list(mailbox.units(("folders",)))
