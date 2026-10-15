# Generated from docs/arch/requirements.yaml. Do not hand-edit.
Feature: REQ-740 — Security
  # A masked column is its mask wherever the statement references it -- the select list, expressions, JOIN ON, GROUP BY, ORD…

  Scenario: REQ-740 default behaviour
    Given a column masked for a role and referenced in the select list and in a JOIN ON
    When the role runs the statement
    Then both references read the masked expression, so the join does not match on the real value
    And a WHERE or HAVING reference to the masked column is refused with V005
