-- Copyright (c) 2026 Kenneth Stott
--
-- This source code is licensed under the Business Source License 1.1
-- found in the LICENSE file in the root directory of this source tree.
--
-- NOTICE: Use of this software for training artificial intelligence or
-- machine learning models is strictly prohibited without explicit written
-- permission from the copyright holder.
--
-- The sonnets demo's database (REQ-2016): Shakespeare's 154 sonnets, one row a sonnet and one a
-- line, loaded from lines.tsv beside this file (the text of Project Gutenberg eBook #1041, one
-- line a row: sonnet number, line number, text). A line's id is its sonnet's number times 100
-- plus its line number, so 36:13 is line 3613. `echo` is empty: Provisa's link_echoes command
-- fills it. `provisa` is the role Provisa reads the sonnets as and writes the echoes as.

CREATE ROLE provisa LOGIN PASSWORD 'provisa';
CREATE SCHEMA sonnets AUTHORIZATION provisa;
SET search_path = sonnets;

CREATE TABLE line (
    id integer PRIMARY KEY,
    sonnet_number integer NOT NULL,
    line_no integer NOT NULL,
    text text NOT NULL,
    UNIQUE (sonnet_number, line_no)
);

CREATE TEMP TABLE given (sonnet_number integer, line_no integer, text text);
\copy given FROM '/docker-entrypoint-initdb.d/lines.tsv'
INSERT INTO line (id, sonnet_number, line_no, text)
SELECT sonnet_number * 100 + line_no, sonnet_number, line_no, text FROM given;

CREATE TABLE sonnet (
    number integer PRIMARY KEY,
    first_line text NOT NULL,
    sequence text NOT NULL CHECK (sequence IN ('Fair Youth', 'Dark Lady'))
);

INSERT INTO sonnet (number, first_line, sequence)
SELECT sonnet_number, text, CASE WHEN sonnet_number <= 126 THEN 'Fair Youth' ELSE 'Dark Lady' END
FROM line
WHERE line_no = 1;

ALTER TABLE line ADD FOREIGN KEY (sonnet_number) REFERENCES sonnet (number);

-- The themes the demo searches the lines for, each by a phrase of its own; each has a view of
-- the lines nearest its phrase (config.yaml, theme_<id>).
CREATE TABLE theme (
    id text PRIMARY KEY,
    name text NOT NULL,
    phrase text NOT NULL
);

INSERT INTO theme (id, name, phrase) VALUES
    ('time', 'Time', 'the ravages of time'),
    ('beauty', 'Beauty', 'beauty'),
    ('mortality', 'Mortality', 'mortality and death'),
    ('jealousy', 'Jealousy', 'jealousy'),
    ('verse', 'Verse outlives death', 'my verse shall live');

-- Each line's nearest lines in other sonnets, by meaning, with their similarity.
CREATE TABLE echo (
    line_id integer NOT NULL REFERENCES line (id),
    echo_line_id integer NOT NULL REFERENCES line (id),
    score double precision NOT NULL,
    PRIMARY KEY (line_id, echo_line_id)
);

ALTER TABLE line OWNER TO provisa;
ALTER TABLE sonnet OWNER TO provisa;
ALTER TABLE echo OWNER TO provisa;
ALTER TABLE theme OWNER TO provisa;
