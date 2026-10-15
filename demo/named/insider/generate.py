# Copyright (c) 2026 Kenneth Stott
# Canary: 3e518d42-87b4-4f2d-beba-7d9e1ac1df5f
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""Write the insider demo's data, db/*.tsv (REQ-2056): a fictional bank, Northgate Partners --
its control room's watch list of five code-named deals, its employees, its customers and who read
their records, and two weeks of its employees' mail.

Every name, company and record is invented. The mail carries the cases the review queue must rank:

  - a trader not on deal Falcon tells a personal address about it in his own words -- no name,
    ticker or code name -- before it is announced: it must outrank
  - a Falcon deal-team member's mail to the deal's counsel, naming the company, its ticker and the
    code name: expected, and lowered;
  - an operations employee who read the customer records that week mails customers' social
    security and account numbers to a personal address;
  - and the bank's ordinary mail around them.

Deterministic (seed 2056), so the committed files are what this writes.

Usage: python demo/named/insider/generate.py
"""

from __future__ import annotations

import random
from pathlib import Path

HERE = Path(__file__).resolve().parent / "db"
BANK = "northgate.com"

DESKS = ["M&A", "Leveraged Finance", "Equity Capital Markets", "Sales & Trading", "Research",
         "Operations"]  # fmt: skip
# Who reviews a desk's mail first: a first-level reviewer, by role.
DESK_REVIEWER = {
    "M&A": "reviewer_ana",
    "Leveraged Finance": "reviewer_ana",
    "Equity Capital Markets": "reviewer_ana",
    "Sales & Trading": "reviewer_ben",
    "Research": "reviewer_ben",
    "Operations": "reviewer_ben",
}
FIRST = ["Priya", "Jordan", "Dana", "Marcus", "Elena", "Tomas", "Grace", "Hiro", "Amara", "Luca",
         "Sofia", "Owen", "Nadia", "Felix", "Ines", "Rafael", "Chloe", "Victor", "Maya", "Idris",
         "Lena", "Caleb", "Yara", "Simon"]  # fmt: skip
LAST = ["Shah", "Pike", "Whitfield", "Odum", "Varga", "Lindqvist", "Okafor", "Tanaka", "Mensah",
        "Ferraro", "Navarro", "Brennan", "Haddad", "Kruger", "Duarte", "Costa", "Moreau", "Petrov",
        "Rahman", "Bello", "Fischer", "Quinn", "Amari", "Holt"]  # fmt: skip

# The watch list: code name, legal name, aliases, ticker, type, description, announced (or None),
# the deal's counterparties' mail domains.
DEALS = [
    ("D-01", "Falcon", "Halcyon Biosciences, Inc.", "Halcyon;Halcyon Bio", "HLCB", "acquisition",
     "Acquisition of a clinical-stage gene therapy company developing treatments for rare "
     "inherited eye diseases, at a premium to its market price, for a large pharmaceutical buyer.",
     None, "halcyonbio.com;whitlock-law.com"),
    ("D-02", "Osprey", "Meridian Freight Lines Corp.", "Meridian Freight;MFL", "MFRT", "merger",
     "Merger of two regional trucking and logistics carriers to form the largest "
     "less-than-truckload freight network in the Midwest.",
     "2026-10-20", "meridianfreight.com;harlan-burke.com"),
    ("D-03", "Kestrel", "Solace Energy Storage Ltd", "Solace Energy;Solace", "SLCE", "loan",
     "A senior secured term loan to finance construction of grid-scale battery storage sites.",
     None, "solace-energy.com"),
    ("D-04", "Heron", "Arbor Lane Retail Group", "Arbor Lane", "ALRG", "underwriting",
     "Underwriting a follow-on equity offering for a chain of home furnishing stores raising "
     "capital to open new locations.",
     "2026-10-05", "arborlane.com"),
    ("D-05", "Merlin", "Cobaltline Semiconductor Inc.", "Cobaltline", "CBLT", "acquisition",
     "A tender offer for a maker of power management chips used in electric vehicles.",
     None, "cobaltline.com;reyes-associates.com"),
]  # fmt: skip


def _employees() -> list[list[str]]:
    rows = []
    for i, (first, last) in enumerate(zip(FIRST, LAST), start=1):
        desk = DESKS[(i - 1) % len(DESKS)]
        rows.append(
            [f"E{i:03d}", f"{first} {last}", f"{first.lower()}.{last.lower()}@{BANK}", desk]
        )
    return rows


def _deal_teams(employees: list[list[str]]) -> list[list[str]]:
    by_desk: dict[str, list[str]] = {}
    for emp_id, _name, _email, desk in employees:
        by_desk.setdefault(desk, []).append(emp_id)
    teams = {
        "D-01": by_desk["M&A"][:2] + by_desk["Research"][:1],
        "D-02": by_desk["M&A"][2:4],
        "D-03": by_desk["Leveraged Finance"][:2],
        "D-04": by_desk["Equity Capital Markets"][:2],
        "D-05": by_desk["M&A"][1:3],
    }
    rows = []
    for d, (deal_id, members) in enumerate(sorted(teams.items())):
        for m, emp_id in enumerate(members):
            rows.append([deal_id, emp_id, f"2026-09-{10 + d * 2 + m:02d} 09:00:00"])
    return rows


def _field(value: str | None) -> str:
    """A value as COPY's text format reads it: NULL as \\N, a backslash, newline or tab escaped."""
    if value is None:
        return "\\N"
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace("\t", "\\t")


def main() -> None:
    rng = random.Random(2056)
    employees = _employees()
    name_of = {e[0]: e[1] for e in employees}
    email_of = {e[0]: e[2] for e in employees}
    teams = _deal_teams(employees)
    falcon_team = [t[1] for t in teams if t[0] == "D-01"]
    trader = next(e[0] for e in employees if e[3] == "Sales & Trading" and e[0] not in falcon_team)
    ops = next(e[0] for e in employees if e[3] == "Operations")

    customers = []
    for i in range(1, 41):
        first, last = rng.choice(FIRST), rng.choice(LAST)
        ssn = f"{rng.randint(100, 899)}-{rng.randint(10, 99)}-{rng.randint(1000, 9999)}"
        customers.append([f"C{i:04d}", f"{first} {last}", f"{first.lower()}{i}@example.net", ssn,
                          f"ACCT-{rng.randint(10_000_000, 99_999_999)}"])  # fmt: skip
    access = []
    readers = [e[0] for e in employees if e[3] in ("Operations", "Sales & Trading")]
    for i in range(1, 31):
        day = rng.randint(1, 14)
        access.append([str(i), rng.choice(readers), f"2026-10-{day:02d} {rng.randint(8, 18):02d}:15:00",
                       "customer", str(rng.randint(1, 5))])  # fmt: skip
    access.append([str(len(access) + 1), ops, "2026-10-09 16:40:00", "customer", "240"])

    messages: list[list[str]] = []
    recipients: list[list[str]] = []

    def mail(sender: str, sent: str, subject: str, body: str, to: list[tuple[str, str]]) -> None:
        mid = f"M{len(messages) + 1:04d}"
        # The envelope's own count of who it went outside the bank to, as a mail system keeps it.
        outside = sum(1 for _address, kind in to if kind != "internal")
        personal = sum(1 for _address, kind in to if kind == "personal")
        messages.append([mid, sender, sent, subject, body, str(outside), str(personal)])
        for address, kind in to:
            recipients.append([mid, address, address.split("@", 1)[1], kind])

    internal = [e for e in employees]
    topics = [
        (
            "Desk lunch Thursday",
            "Booking the usual place for Thursday at noon. Reply if you are in.",
        ),
        ("Weekly risk report", "Attached is this week's risk report. Limits held; no breaches."),
        ("Client call notes", "Notes from this morning's coverage call are in the shared folder."),
        ("Training reminder", "Annual compliance training is due by the end of the month."),
        ("Expense approvals", "Please approve the pending expense reports in the portal."),
        ("Market wrap", "Rates rallied into the close; credit spreads tightened a little."),
        ("Offsite agenda", "Draft agenda for the November offsite is attached for comments."),
        ("Holiday coverage", "Please add your holiday cover to the team calendar."),
    ]
    for i in range(110):
        sender = rng.choice(internal)
        rcpt = rng.choice([e for e in internal if e[0] != sender[0]])
        subject, body = rng.choice(topics)
        day, hour = rng.randint(1, 14), rng.randint(7, 19)
        mail(sender[0], f"2026-10-{day:02d} {hour:02d}:{rng.randint(0, 59):02d}:00", subject, body,
             [(rcpt[2], "internal")])  # fmt: skip

    # The cases the queue must rank.
    mail(trader, "2026-10-08 21:12:00", "fyi",
         "Heads up: the gene therapy outfit working on inherited eye disease is about to be bought "
         "out by one of the big pharma names, and at a fat premium. Nothing public yet. Might be "
         "worth a look before it hits the tape.",
         [("jp.homebox@gmail.com", "personal")])  # fmt: skip
    mail(falcon_team[0], "2026-10-07 10:30:00", "Project Falcon - draft merger agreement",
         "Attached is the latest draft merger agreement for Halcyon Biosciences. Please send "
         "comments on the HLCB tender offer mechanics and the Falcon timetable by Friday.",
         [("r.whitlock@whitlock-law.com", "external")])  # fmt: skip
    mail(falcon_team[1], "2026-10-09 08:05:00", "Falcon model",
         "Updated the Falcon valuation model with the new Halcyon trial readouts.",
         [(email_of[falcon_team[0]], "internal")])  # fmt: skip
    osprey_team = [t[1] for t in teams if t[0] == "D-02"]
    mail(osprey_team[0], "2026-10-06 14:20:00", "Osprey diligence list",
         "Sending the Meridian Freight diligence request list ahead of Monday's session.",
         [("counsel@harlan-burke.com", "external")])  # fmt: skip
    researcher = next(e[0] for e in employees if e[3] == "Research" and e[0] not in falcon_team)
    mail(researcher, "2026-10-10 11:45:00", "freight consolidation",
         "Hearing the two big Midwest trucking carriers may be combining into one network. Anyone "
         "know more?",
         [(email_of[trader], "internal")])  # fmt: skip
    sales = next(e[0] for e in employees if e[3] == "Sales & Trading" and e[0] != trader)
    mail(sales, "2026-10-06 09:10:00", "Arbor Lane follow-on priced",
         "Arbor Lane Retail's follow-on priced last night; allocations go out this morning.",
         [("pm@harbor-capital.com", "external")])  # fmt: skip
    leaked = "\n".join(f"{c[1]}, SSN {c[3]}, account {c[4]}" for c in customers[:12])
    mail(ops, "2026-10-10 19:55:00", "list", f"As discussed:\n{leaked}",
         [("dw.files@proton.me", "personal")])  # fmt: skip
    mail(ops, "2026-10-03 10:00:00", "Account fix",
         f"Corrected the mailing address on {customers[20][4]}; ticket closed.",
         [(email_of[sales], "internal")])  # fmt: skip

    team_rows = teams
    counterparties = [[d[0], dom] for d in DEALS for dom in d[8].split(";")]
    deals = [[d[0], d[1], d[2], d[3], d[4], d[5], d[6], d[7]] for d in DEALS]
    desk_reviewer = [[desk, reviewer] for desk, reviewer in DESK_REVIEWER.items()]
    for name, rows in {
        "employee": employees,
        "desk_reviewer": desk_reviewer,
        "deal": deals,
        "deal_team": team_rows,
        "deal_counterparty": counterparties,
        "customer": customers,
        "customer_access": access,
        "message": messages,
        "recipient": recipients,
    }.items():
        lines = ["\t".join(_field(v) for v in row) for row in rows]
        (HERE / f"{name}.tsv").write_text("\n".join(lines) + "\n")
    print(f"employees {len(employees)}, deals {len(deals)}, messages {len(messages)}, "
          f"customers {len(customers)}, accesses {len(access)}; trader {name_of[trader]}, "
          f"operations {name_of[ops]}")  # fmt: skip


if __name__ == "__main__":
    main()
