# Generated from docs/arch/requirements.yaml. Do not hand-edit.
Feature: REQ-882 — Materialization Store
  # An aggregate query is answered from a fresh materialized view that pre-aggregates its table, with nothing declared (Amen…

  Scenario: REQ-882 default behaviour
    Given an aggregate MV over "orders" grouping by region and status, storing SUM(amount) and COUNT(*), fresh
    When a compiled query "SELECT SUM(amount) FROM orders WHERE region = 'us'" is routed
    Then it reads the MV target, re-aggregating the stored sums of the rows whose region is 'us', and its sources become the MV catalog
    And an MV pre-computed WITH status = 'active' is never used, so no rows are silently dropped
