#!/bin/sh
# Creates the owner role (runs migrations) and the runtime role (used by api/worker).
# The runtime role gets DML through default privileges; the audit_log migration then
# revokes UPDATE/DELETE/TRUNCATE on audit_log from it.
set -eu
: "${P1_DB_NAME:=project_one}"
: "${P1_OWNER_PASSWORD:?P1_OWNER_PASSWORD is required}"
: "${P1_APP_PASSWORD:?P1_APP_PASSWORD is required}"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
  -v owner_pw="$P1_OWNER_PASSWORD" -v app_pw="$P1_APP_PASSWORD" -v db="$P1_DB_NAME" <<'SQL'
CREATE ROLE p1_owner LOGIN PASSWORD :'owner_pw';
CREATE ROLE p1_app LOGIN PASSWORD :'app_pw';
CREATE DATABASE :"db" OWNER p1_owner;
REVOKE ALL ON DATABASE :"db" FROM PUBLIC;
GRANT CONNECT ON DATABASE :"db" TO p1_app;
SQL

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$P1_DB_NAME" <<'SQL'
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
ALTER SCHEMA public OWNER TO p1_owner;
GRANT USAGE ON SCHEMA public TO p1_app;
ALTER DEFAULT PRIVILEGES FOR ROLE p1_owner IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO p1_app;
ALTER DEFAULT PRIVILEGES FOR ROLE p1_owner IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO p1_app;
SQL
