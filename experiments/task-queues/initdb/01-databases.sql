-- Hatchet's engine and the Postgres-backed Prefect variant keep their state in
-- databases of their own on the benchmark's one Postgres, as they would on ours.
CREATE DATABASE hatchet;
CREATE DATABASE prefect;
