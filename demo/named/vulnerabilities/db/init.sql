-- Copyright (c) 2026 Kenneth Stott
--
-- This source code is licensed under the Business Source License 1.1
-- found in the LICENSE file in the root directory of this source tree.
--
-- NOTICE: Use of this software for training artificial intelligence or
-- machine learning models is strictly prohibited without explicit written
-- permission from the copyright holder.
--
-- The vulnerabilities demo's private data: a software company's code, as its source-control host
-- reports it. Generated, and the same on every build: each value is derived from a repository's
-- and a package's numbers, never random. The packages pinned at a vulnerable version are real, and
-- so are the CVEs their alerts name -- what joins this database to the NVD and CISA's catalog of
-- known exploited vulnerabilities in govdata.
--
--   repositories       the company's repositories: the team that owns each, its language, how
--                      critical it is to the business and whether it serves the internet
--   dependencies       each repository's dependency manifest: the packages it pins, by version
--   dependabot_alerts  one alert per vulnerable package pin and CVE, as Dependabot raises them:
--                      open, fixed or dismissed

CREATE TABLE repositories (
  repo_id         integer PRIMARY KEY,
  name            varchar NOT NULL UNIQUE,
  team            varchar NOT NULL,
  language        varchar NOT NULL,
  ecosystem       varchar NOT NULL,
  criticality     varchar NOT NULL,  -- high, medium or low
  internet_facing boolean NOT NULL
);

INSERT INTO repositories VALUES
  (1, 'payments-api', 'payments', 'Java', 'maven', 'high', true),
  (2, 'ledger-service', 'payments', 'Java', 'maven', 'high', false),
  (3, 'fraud-scoring', 'payments', 'Python', 'pip', 'high', false),
  (4, 'identity-gateway', 'identity', 'Java', 'maven', 'high', true),
  (5, 'sso-admin', 'identity', 'TypeScript', 'npm', 'medium', true),
  (6, 'token-broker', 'identity', 'Go', 'go', 'high', true),
  (7, 'storefront-web', 'storefront', 'TypeScript', 'npm', 'high', true),
  (8, 'catalog-service', 'storefront', 'Java', 'maven', 'medium', true),
  (9, 'search-indexer', 'storefront', 'Java', 'maven', 'medium', false),
  (10, 'checkout-ui', 'storefront', 'TypeScript', 'npm', 'high', true),
  (11, 'order-events', 'data-platform', 'Java', 'maven', 'medium', false),
  (12, 'etl-pipelines', 'data-platform', 'Python', 'pip', 'medium', false),
  (13, 'metrics-api', 'data-platform', 'Python', 'pip', 'low', false),
  (14, 'warehouse-loader', 'data-platform', 'Java', 'maven', 'medium', false),
  (15, 'mobile-bff', 'mobile', 'TypeScript', 'npm', 'high', true),
  (16, 'push-notifier', 'mobile', 'Go', 'go', 'medium', true),
  (17, 'partner-portal', 'partners', 'PHP', 'composer', 'medium', true),
  (18, 'billing-portal', 'partners', 'PHP', 'composer', 'high', true),
  (19, 'legacy-struts-admin', 'internal-tools', 'Java', 'maven', 'low', false),
  (20, 'support-console', 'internal-tools', 'TypeScript', 'npm', 'low', false),
  (21, 'report-builder', 'internal-tools', 'Python', 'pip', 'low', false),
  (22, 'docs-site', 'internal-tools', 'TypeScript', 'npm', 'low', true),
  (23, 'ml-feature-store', 'data-platform', 'Python', 'pip', 'medium', false),
  (24, 'admin-dashboard', 'internal-tools', 'TypeScript', 'npm', 'medium', false);

-- The packages the company's repositories depend on. A package with an advisory has the version
-- it is vulnerable at and the version that fixes it, and the CVE and severity of the advisory; a
-- package of two advisories (log4j-core) has a row for each. Used to generate the tables below.
CREATE TEMPORARY TABLE packages (
  pkg_no             integer NOT NULL,
  ecosystem          varchar NOT NULL,
  package_name       varchar NOT NULL,
  vulnerable_version varchar,
  fixed_version      varchar NOT NULL,
  cve_id             varchar,
  severity           varchar
);

INSERT INTO packages VALUES
  (1, 'maven', 'org.apache.logging.log4j:log4j-core', '2.14.1', '2.17.1', 'CVE-2021-44228', 'critical'),
  (1, 'maven', 'org.apache.logging.log4j:log4j-core', '2.14.1', '2.17.1', 'CVE-2021-45046', 'critical'),
  (2, 'maven', 'org.springframework:spring-beans', '5.3.17', '5.3.18', 'CVE-2022-22965', 'critical'),
  (3, 'maven', 'org.apache.struts:struts2-core', '2.3.31', '2.5.33', 'CVE-2017-5638', 'critical'),
  (4, 'maven', 'org.apache.tomcat.embed:tomcat-embed-core', '9.0.30', '9.0.31', 'CVE-2020-1938', 'critical'),
  (5, 'maven', 'org.apache.activemq:activemq-client', '5.18.2', '5.18.3', 'CVE-2023-46604', 'critical'),
  (6, 'maven', 'io.netty:netty-codec-http2', '4.1.99.Final', '4.1.100.Final', 'CVE-2023-44487', 'high'),
  (7, 'maven', 'org.apache.commons:commons-text', '1.9', '1.10.0', 'CVE-2022-42889', 'critical'),
  (8, 'maven', 'org.yaml:snakeyaml', '1.33', '2.0', 'CVE-2022-1471', 'high'),
  (9, 'maven', 'com.alibaba:fastjson', '1.2.80', '1.2.83', 'CVE-2022-25845', 'critical'),
  (10, 'maven', 'com.fasterxml.jackson.core:jackson-databind', NULL, '2.17.1', NULL, NULL),
  (11, 'maven', 'com.google.guava:guava', NULL, '33.2.0-jre', NULL, NULL),
  (12, 'maven', 'org.slf4j:slf4j-api', NULL, '2.0.13', NULL, NULL),
  (1, 'npm', 'lodash', '4.17.20', '4.17.21', 'CVE-2021-23337', 'high'),
  (2, 'npm', 'moment', '2.29.1', '2.29.4', 'CVE-2022-24785', 'high'),
  (3, 'npm', 'jquery', '3.3.1', '3.5.0', 'CVE-2019-11358', 'medium'),
  (4, 'npm', 'minimist', '1.2.5', '1.2.6', 'CVE-2021-44906', 'critical'),
  (5, 'npm', 'react', NULL, '18.3.1', NULL, NULL),
  (6, 'npm', 'express', NULL, '4.19.2', NULL, NULL),
  (7, 'npm', 'axios', NULL, '1.7.2', NULL, NULL),
  (1, 'pip', 'PyYAML', '5.3.1', '5.4', 'CVE-2020-14343', 'critical'),
  (2, 'pip', 'Pillow', '9.0.0', '9.0.1', 'CVE-2022-22817', 'critical'),
  (3, 'pip', 'urllib3', '1.26.4', '1.26.5', 'CVE-2021-33503', 'high'),
  (4, 'pip', 'requests', '2.25.1', '2.31.0', 'CVE-2023-32681', 'medium'),
  (5, 'pip', 'numpy', NULL, '1.26.4', NULL, NULL),
  (6, 'pip', 'pandas', NULL, '2.2.2', NULL, NULL),
  (7, 'pip', 'fastapi', NULL, '0.111.0', NULL, NULL),
  (1, 'composer', 'facade/ignition', '2.5.1', '2.5.2', 'CVE-2021-3129', 'critical'),
  (2, 'composer', 'laravel/framework', NULL, '10.48.12', NULL, NULL),
  (3, 'composer', 'guzzlehttp/guzzle', NULL, '7.8.1', NULL, NULL),
  (1, 'go', 'golang.org/x/net', '0.15.0', '0.17.0', 'CVE-2023-44487', 'high'),
  (2, 'go', 'github.com/gin-gonic/gin', NULL, '1.10.0', NULL, NULL),
  (3, 'go', 'google.golang.org/grpc', NULL, '1.64.0', NULL, NULL);

CREATE TABLE dependencies (
  repo_id      integer NOT NULL REFERENCES repositories (repo_id),
  ecosystem    varchar NOT NULL,
  package_name varchar NOT NULL,
  version      varchar NOT NULL,
  scope        varchar NOT NULL,  -- runtime or development
  PRIMARY KEY (repo_id, package_name)
);

-- Pins left at a vulnerable version whatever the rule below says: the struts admin console nobody
-- touches, and the billing portal's debug page package, never upgraded with its framework.
CREATE TEMPORARY TABLE stuck_pins (repo_name varchar NOT NULL, package_name varchar NOT NULL);
INSERT INTO stuck_pins VALUES
  ('legacy-struts-admin', 'org.apache.struts:struts2-core'),
  ('billing-portal', 'facade/ignition');

-- A repository pins most of its ecosystem's packages (about seven in nine); one in three of the
-- pins of a package with an advisory is still at the vulnerable version.
INSERT INTO dependencies
SELECT DISTINCT r.repo_id, p.ecosystem, p.package_name,
       CASE WHEN p.vulnerable_version IS NOT NULL
                 AND ((r.repo_id + p.pkg_no * 2) % 3 = 0
                      OR s.repo_name IS NOT NULL)
            THEN p.vulnerable_version ELSE p.fixed_version END,
       CASE WHEN (r.repo_id + p.pkg_no) % 5 = 0 THEN 'development' ELSE 'runtime' END
FROM repositories AS r
JOIN packages AS p ON p.ecosystem = r.ecosystem
LEFT JOIN stuck_pins AS s ON s.repo_name = r.name AND s.package_name = p.package_name
WHERE (r.repo_id * 7 + p.pkg_no * 5) % 9 < 7 OR s.repo_name IS NOT NULL;

CREATE TABLE dependabot_alerts (
  alert_id           integer PRIMARY KEY,
  repo_id            integer NOT NULL REFERENCES repositories (repo_id),
  ecosystem          varchar NOT NULL,
  package_name       varchar NOT NULL,
  vulnerable_version varchar NOT NULL,
  fixed_version      varchar NOT NULL,
  cve_id             varchar NOT NULL,
  severity           varchar NOT NULL,  -- the advisory's: critical, high, medium or low
  state              varchar NOT NULL,  -- open, fixed or dismissed
  created_at         date NOT NULL,
  fixed_at           date
);

-- One alert per vulnerable pin and CVE. Most are open; one in seven has been fixed (and its pin
-- is still shown at the vulnerable version, as the manifest was when the alert was raised), one
-- in thirteen dismissed. A stuck pin's alerts are open: nobody has acted on them.
INSERT INTO dependabot_alerts
SELECT n,
       repo_id, ecosystem, package_name, vulnerable_version, fixed_version, cve_id, severity,
       CASE WHEN stuck THEN 'open' WHEN n % 7 = 0 THEN 'fixed' WHEN n % 13 = 0 THEN 'dismissed'
            ELSE 'open' END,
       DATE '2024-01-15' + (n * 37) % 540,
       CASE WHEN NOT stuck AND n % 7 = 0 THEN DATE '2024-01-15' + (n * 37) % 540 + 5 + n % 40 END
FROM (
  SELECT ROW_NUMBER() OVER (ORDER BY d.repo_id, d.package_name, p.cve_id)::integer AS n,
         d.repo_id, d.ecosystem, d.package_name, p.vulnerable_version, p.fixed_version,
         p.cve_id, p.severity, s.repo_name IS NOT NULL AS stuck
  FROM dependencies AS d
  JOIN repositories AS r ON r.repo_id = d.repo_id
  LEFT JOIN stuck_pins AS s ON s.repo_name = r.name AND s.package_name = d.package_name
  JOIN packages AS p
    ON p.ecosystem = d.ecosystem AND p.package_name = d.package_name
   AND p.vulnerable_version = d.version
) AS pins;

DROP TABLE packages, stuck_pins;
