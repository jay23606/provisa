# Generated from docs/arch/requirements.yaml. Do not hand-edit.
Feature: REQ-423 — Vector Search
  # A `cosine_similarity(column, query)` function is available in Provisa SQL (and so in Cypher, which compiles to it). The…

  Scenario: REQ-423 default behaviour
    Given a query using cosine_similarity(column, query_vector)
    When compiled for a native-capable source
    Then the call is written in that source's own SQL; for a source without it the statement routes to the engine, which computes it
