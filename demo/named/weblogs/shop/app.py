# Copyright (c) 2026 Kenneth Stott
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.
"""The weblogs demo's web shop (REQ-1858, REQ-1996): customers, products and orders behind nginx.

Every SQL statement it sends carries the request's id, as nginx generated it and passed it in
X-Request-Id, in a SQLCommenter comment (``/*request_id='…',route='…'*/``). The database logs the
statement with its duration, so a line of the access log and the statements it caused share an
id. Statements are sent with their values inlined (psycopg's ClientCursor), so each is one log
record rather than a parse, bind and execute each. A request has a connection of its own, named
by the request's id (application_name), so every record the database logs for it -- a statement
or an error -- carries the id in a field of its own too."""

from __future__ import annotations

import os
from decimal import Decimal
from typing import Any, LiteralString, cast
from urllib.parse import quote

import psycopg
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

DSN = os.environ["SHOP_DSN"]

app = FastAPI(title="weblogs shop")


def _comment(request: Request) -> str:
    """The SQLCommenter comment for ``request``: its keys sorted, each value URL-encoded and
    quoted."""
    route = request.scope.get("route")
    pairs = {
        "request_id": request.headers.get("x-request-id", ""),
        "route": getattr(route, "path", request.url.path),
    }
    return "/*" + ",".join(f"{k}='{quote(v, safe='')}'" for k, v in sorted(pairs.items())) + "*/"


class Db:
    """One request's connection: every statement goes out with the request's comment."""

    def __init__(self, request: Request) -> None:
        self._comment = _comment(request)
        self._conn = psycopg.connect(
            DSN,
            cursor_factory=psycopg.ClientCursor,
            application_name=request.headers.get("x-request-id", ""),
        )

    def rows(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        with self._conn.cursor() as cur:
            # A literal % in the comment would be read as a placeholder.
            query = f"{sql} {self._comment.replace('%', '%%')}"
            cur.execute(cast(LiteralString, query), params)
            if cur.description is None:
                return []
            names = [d.name for d in cur.description]
            return [dict(zip(names, row)) for row in cur.fetchall()]

    def commit(self) -> None:
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()


def db(request: Request):
    conn = Db(request)
    try:
        yield conn
    finally:
        conn.close()


@app.exception_handler(psycopg.Error)
async def _database_error(_: Request, exc: psycopg.Error) -> JSONResponse:
    # A failed statement is a server error: the database logged it, with the request's id.
    return JSONResponse({"error": "database error", "detail": str(exc).splitlines()[0]}, 500)


def _json(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {k: (float(v) if isinstance(v, Decimal) else v) for k, v in row.items()} for row in rows
    ]


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/products")
def products(category: str | None = None, page: int = 1, conn: Db = Depends(db)):
    if page < 1:
        raise HTTPException(400, "page starts at 1")
    if category is None:
        return _json(
            conn.rows(
                "SELECT id, name, category, price FROM shop.products ORDER BY id LIMIT 20 OFFSET %s",
                ((page - 1) * 20,),
            )
        )
    return _json(
        conn.rows(
            "SELECT id, name, category, price FROM shop.products WHERE category = %s "
            "ORDER BY id LIMIT 20 OFFSET %s",
            (category, (page - 1) * 20),
        )
    )


@app.get("/products/{product_id}")
def product(product_id: int, conn: Db = Depends(db)):
    found = conn.rows("SELECT * FROM shop.products WHERE id = %s", (product_id,))
    if not found:
        raise HTTPException(404, "no such product")
    return _json(found)[0]


@app.get("/search")
def search(q: str, sort: str = "name", conn: Db = Depends(db)):
    if not q.strip():
        raise HTTPException(400, "say what to search for")
    if sort == "popular":
        # Ranked by units sold: an aggregate over every order line, the shop's slow search.
        return _json(
            conn.rows(
                "SELECT p.id, p.name, p.price, coalesce(sum(oi.quantity), 0) AS sold "
                "FROM shop.products AS p LEFT JOIN shop.order_items AS oi ON oi.product_id = p.id "
                "CROSS JOIN pg_sleep(0.12) "
                "WHERE p.name ILIKE %s OR p.description ILIKE %s "
                "GROUP BY p.id, p.name, p.price ORDER BY sold DESC LIMIT 20",
                (f"%{q}%", f"%{q}%"),
            )
        )
    if sort != "name":
        raise HTTPException(400, "sort is name or popular")
    return _json(
        conn.rows(
            "SELECT id, name, price FROM shop.products "
            "WHERE name ILIKE %s OR description ILIKE %s ORDER BY name LIMIT 20",
            (f"%{q}%", f"%{q}%"),
        )
    )


@app.get("/customers/{customer_id}/orders")
def customer_orders(customer_id: int, conn: Db = Depends(db)):
    if not conn.rows("SELECT id FROM shop.customers WHERE id = %s", (customer_id,)):
        raise HTTPException(404, "no such customer")
    return _json(
        conn.rows(
            "SELECT id, placed_at, status FROM shop.orders WHERE customer_id = %s "
            "ORDER BY placed_at DESC",
            (customer_id,),
        )
    )


@app.get("/orders/{order_id}")
def order(order_id: int, conn: Db = Depends(db)):
    found = conn.rows("SELECT * FROM shop.orders WHERE id = %s", (order_id,))
    if not found:
        raise HTTPException(404, "no such order")
    head = _json(found)[0]
    head["items"] = _json(
        conn.rows(
            "SELECT product_id, quantity, unit_price FROM shop.order_items WHERE order_id = %s",
            (order_id,),
        )
    )
    return head


class NewOrder(BaseModel):
    customer_id: int
    product_id: int
    quantity: int


@app.post("/orders", status_code=201)
def place_order(new: NewOrder, conn: Db = Depends(db)):
    if not 1 <= new.quantity <= 10:
        raise HTTPException(400, "a quantity is 1 to 10")
    found = conn.rows("SELECT price FROM shop.products WHERE id = %s", (new.product_id,))
    if not found:
        raise HTTPException(404, "no such product")
    # An unknown customer breaks the orders foreign key, and more than is in stock breaks the
    # products check: both fail in the database, as a 500.
    placed = conn.rows(
        "INSERT INTO shop.orders (id, customer_id, placed_at, status) "
        "VALUES (nextval('shop.orders_id_seq'), %s, now(), 'placed') RETURNING id",
        (new.customer_id,),
    )
    conn.rows(
        "INSERT INTO shop.order_items (id, order_id, product_id, quantity, unit_price) "
        "VALUES (nextval('shop.order_items_id_seq'), %s, %s, %s, %s)",
        (placed[0]["id"], new.product_id, new.quantity, found[0]["price"]),
    )
    conn.rows(
        "UPDATE shop.products SET stock = stock - %s WHERE id = %s",
        (new.quantity, new.product_id),
    )
    conn.commit()
    return {"id": placed[0]["id"]}


@app.get("/reports/top")
def top_products(conn: Db = Depends(db)):
    # The back office's report: every order line totalled, the slowest page of the shop.
    return _json(
        conn.rows(
            "SELECT p.category, sum(oi.quantity * oi.unit_price) AS revenue "
            "FROM shop.order_items AS oi JOIN shop.products AS p ON p.id = oi.product_id "
            "CROSS JOIN pg_sleep(0.2 + random() * 0.4) "
            "GROUP BY p.category ORDER BY revenue DESC"
        )
    )


@app.get("/wishlist")
def wishlist(conn: Db = Depends(db)):
    # A page left behind by a schema change: its table lost the column it reads.
    return _json(conn.rows("SELECT wished_on FROM shop.customers"))
