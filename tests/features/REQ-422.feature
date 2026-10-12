# Generated from docs/arch/requirements.yaml. Do not hand-edit.
Feature: REQ-422 — Vector Search
  # A source's native vector capability is detected when its driver connects, at boot and when the source is registered (exe…

  Scenario: REQ-422 default behaviour
    Given a PostgreSQL source being registered
    When Provisa checks for native vector support
    Then it detects the pgvector extension and marks the source as native-capable, or flags it for the engine
