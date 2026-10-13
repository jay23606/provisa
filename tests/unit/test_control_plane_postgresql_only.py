# Copyright (c) 2026 Kenneth Stott
# Canary: 307af0e1-acb0-4624-9056-07b7aec62a63
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.
"""REQ-2014: the control plane is PostgreSQL only. A control-plane URL naming any other backend is
refused by name, naming the setting it came from."""

from __future__ import annotations

import pytest

from provisa.core.models import ControlPlaneConfig, ControlPlaneNotPostgresql

_PG = "postgresql+psycopg://provisa:provisa@localhost:5432/provisa"


@pytest.mark.parametrize(
    ("url", "backend"),
    [
        ("sqlite+pysqlite:////data/tenant.db", "sqlite"),
        ("duckdb:////data/control.duckdb", "duckdb"),
        ("mysql+pymysql://u:p@h:3306/db", "mysql"),
        ("mariadb+pymysql://u:p@h:3306/db", "mariadb"),
        ("mssql+pyodbc://u:p@h:1433/db?driver=ODBC+Driver+18+for+SQL+Server", "mssql"),
        ("oracle+oracledb://u:p@h:1521/?service_name=s", "oracle"),
    ],
)
def test_a_control_plane_url_naming_another_backend_is_refused_by_name(url, backend):
    tenant = ControlPlaneConfig(tenant_url=url, platform_url=_PG)
    with pytest.raises(ControlPlaneNotPostgresql, match=f"TENANT_DATABASE_URL names a {backend}"):
        tenant.resolved_tenant_url()
    platform = ControlPlaneConfig(tenant_url=_PG, platform_url=url)
    with pytest.raises(ControlPlaneNotPostgresql, match=f"PLATFORM_DATABASE_URL names a {backend}"):
        platform.resolved_platform_url()


def test_a_postgresql_control_plane_is_taken_as_given():
    socket = "postgresql+psycopg://provisa:provisa@/provisa?host=/run/pg&port=5433"
    plane = ControlPlaneConfig(tenant_url=socket, platform_url=_PG)
    assert plane.resolved_tenant_url() == socket
    assert plane.resolved_platform_url() == _PG
