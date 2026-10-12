# Generated from docs/arch/requirements.yaml. Do not hand-edit.
Feature: REQ-424 — Vector Search
  # A table served from its replica (REQ-1912) is the fallback for a vector search: where the engine reads the replica throu…

  Scenario: REQ-424 default behaviour
    Given a table with an embedding column served from its replica on the DuckDB engine
    When a top-k cosine_similarity search is executed
    Then the replica's HNSW index answers it and the answer says the index is approximate
