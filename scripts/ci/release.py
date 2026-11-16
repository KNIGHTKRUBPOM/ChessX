"""Verify release targets and run approved deployment steps without logging credentials."""

from argparse import ArgumentParser
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import re
import subprocess
from tempfile import TemporaryDirectory
from urllib.error import URLError
from urllib.parse import parse_qs, quote, unquote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class ReleaseError(RuntimeError):
    """A message safe to print in a workflow log."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


HTTP = build_opener(NoRedirect())
POSTGRES_IMAGE = "postgres@sha256:b6972e1115a4ff8eba5d7f7d19184926d1e16d7d1136ae1e1a7ebf286da0f015"
MIGRATION_NAME = re.compile(r"\b[0-9]{14}_[A-Za-z0-9_]+\.sql\b")


def required(name, expected=None):
    value = os.environ.get(name, "")
    if not value or (expected and not re.fullmatch(expected, value)):
        raise ReleaseError(f"Set a valid {name} for this release.")
    return value


def origin(value):
    url = urlsplit(value)
    if (
        url.scheme != "https"
        or not url.hostname
        or url.netloc != url.hostname
        or url.path not in ("", "/")
        or url.query
        or url.fragment
    ):
        raise ReleaseError("Use a canonical HTTPS origin with no path, credentials, port or query.")
    return f"https://{url.hostname}"


def target(environment):
    staging = required("CHESS_STAGING_SUPABASE_REF", r"[a-z0-9]{20}")
    production = required("CHESS_PRODUCTION_SUPABASE_REF", r"[a-z0-9]{20}")
    if staging == production:
        raise ReleaseError("Staging and production must use distinct Supabase projects.")

    stage_app = required("CHESS_STAGING_VERCEL_PROJECT_ID", r"prj_[A-Za-z0-9]+")
    prod_app = required("CHESS_PRODUCTION_VERCEL_PROJECT_ID", r"prj_[A-Za-z0-9]+")
    if stage_app == prod_app:
        raise ReleaseError("Staging and production must use distinct Vercel projects.")

    if environment == "preview":
        preview_app = required("CHESS_PREVIEW_VERCEL_PROJECT_ID", r"prj_[A-Za-z0-9]+")
        if preview_app in {stage_app, prod_app}:
            raise ReleaseError("Preview must use its own Vercel project.")
        return staging, preview_app, None

    app_origin = origin(required("APP_ORIGIN"))
    canonical_prod = origin(required("CHESS_PRODUCTION_ORIGIN"))
    if (app_origin == canonical_prod) != (environment == "production"):
        raise ReleaseError("The public origin does not match the selected environment.")
    return (production, prod_app, app_origin) if environment == "production" else (staging, stage_app, app_origin)


def database_url(expected_ref):
    dsn = required("SUPABASE_DB_URL")
    url = urlsplit(dsn)
    direct = url.hostname == f"db.{expected_ref}.supabase.co" and url.username == "postgres"
    pooler = (
        url.hostname is not None
        and re.fullmatch(r"aws-[0-9]+-[a-z0-9-]+\.pooler\.supabase\.com", url.hostname)
        and url.username == f"postgres.{expected_ref}"
    )
    options = parse_qs(url.query, keep_blank_values=True)
    if (
        url.scheme not in {"postgresql", "postgres"}
        or not (direct or pooler)
        or url.port != 5432
        or url.path != "/postgres"
        or not url.password
        or url.fragment
        or set(options) != {"sslmode"}
        or options.get("sslmode") not in (["require"], ["verify-ca"], ["verify-full"])
        or any(re.search(r"[\r\n]", part) for part in (url.username or "", unquote(url.password or "")))
    ):
        raise ReleaseError("The database URL must target the selected project's TLS direct or session pooler.")
    return dsn


def fetch_json(url, headers):
    try:
        with HTTP.open(Request(url, headers=headers), timeout=15) as reply:
            payload = json.loads(reply.read(1_048_577))
        if isinstance(payload, dict):
            return payload
    except (URLError, OSError, ValueError):
        pass
    raise ReleaseError("The provider API could not return the required verified response.")


def require_production_reviewers():
    repo = required("GITHUB_REPOSITORY", r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
    payload = fetch_json(
        f"https://api.github.com/repos/{repo}/environments/production",
        {"Authorization": "Bearer " + required("GH_TOKEN"), "Accept": "application/vnd.github+json"},
    )
    configured = any(
        rule.get("type") == "required_reviewers" and rule.get("reviewers")
        for rule in payload.get("protection_rules", [])
    )
    if not configured:
        raise ReleaseError("Configure required reviewers on the GitHub production environment before deploying.")
    if payload.get("can_admins_bypass") is True:
        raise ReleaseError("Disable administrator bypass for the GitHub production environment.")
    print("The production environment has required reviewers.")


def run_db(environment, dry_run):
    ref, _, _ = target(environment)
    dsn = database_url(ref)
    command = ["supabase", "db", "push", "--remote=" + dsn, "--skip-vault"]
    command.append("--dry-run" if dry_run else "--yes")
    completed = subprocess.run(command, capture_output=True, check=False, text=True, timeout=300)
    if completed.returncode:
        print("Pending migration names:", ", ".join(sorted(set(MIGRATION_NAME.findall(completed.stdout)))) or "(none)")
        raise ReleaseError("Supabase migration command failed. Diagnose from a secure terminal with the same environment.")
    print("Migration plan:" if dry_run else "Migration applied:")
    print(", ".join(sorted(set(MIGRATION_NAME.findall(completed.stdout + completed.stderr)))) or "(no migration names reported)")


def recent_backup(payload, now):
    window = timedelta(hours=26)

    def fresh(timestamp):
        try:
            if type(timestamp) in (int, float):
                point = datetime.fromtimestamp(timestamp, UTC)
            else:
                point = datetime.fromisoformat(timestamp)
            return point.tzinfo is not None and timedelta(0) <= now - point <= window
        except (ValueError, TypeError, OverflowError, OSError):
            return False

    recovery = payload.get("physical_backup_data") or {}
    if payload.get("pitr_enabled") is True and fresh(recovery.get("latest_physical_backup_date_unix")):
        return True
    return any(
        backup.get("status") == "COMPLETED" and fresh(backup.get("inserted_at"))
        for backup in (payload.get("backups") or [])
    )


def logical_backup(dsn, recipient, output):
    url = urlsplit(dsn)
    child_env = {
        **os.environ,
        "PGHOST": url.hostname,
        "PGPORT": "5432",
        "PGDATABASE": "postgres",
        "PGUSER": unquote(url.username),
        "PGPASSWORD": unquote(url.password),
        "PGSSLMODE": parse_qs(url.query)["sslmode"][0],
        "PGCONNECT_TIMEOUT": "12",
    }
    for name in ("PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE", "PGPASSFILE", "PGOPTIONS"):
        child_env.pop(name, None)
    forwarded = ["PGHOST", "PGPORT", "PGDATABASE", "PGUSER", "PGPASSWORD", "PGSSLMODE", "PGCONNECT_TIMEOUT"]
    docker_env = [argument for name in forwarded for argument in ("-e", name)]
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory() as temp:
        dump = Path(temp) / "backup.dump"
        with dump.open("wb") as stream:
            dumped = subprocess.run(
                ["docker", "run", "--rm", *docker_env, POSTGRES_IMAGE, "pg_dump", "--format=custom",
                 "--schema=public", "--schema=auth", "--schema=chessmess_private", "--schema=supabase_migrations"],
                env=child_env,
                stdout=stream,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=300,
            )
        if dumped.returncode or not dump.stat().st_size:
            raise ReleaseError("The encrypted backup could not read the release database.")
        with dump.open("rb") as stream:
            inspected = subprocess.run(
                ["docker", "run", "--rm", "-i", POSTGRES_IMAGE, "pg_restore", "--list"],
                stdin=stream,
                capture_output=True,
                check=False,
                timeout=120,
            )
        if inspected.returncode or b"SCHEMA" not in inspected.stdout:
            raise ReleaseError("The backup archive did not pass its integrity check.")
        encrypted = subprocess.run(
            ["age", "-r", recipient, "-o", str(output), str(dump)],
            capture_output=True,
            check=False,
            timeout=120,
        )
        if encrypted.returncode or not output.is_file() or not output.stat().st_size:
            raise ReleaseError("Encrypting the database backup failed.")
    print("Verified and encrypted the logical backup of data, schema and migration history.")


def guard_backup():
    ref, _, _ = target("production")
    dsn = database_url(ref)
    token = os.environ.get("SUPABASE_BACKUP_TOKEN")
    if token:
        try:
            payload = fetch_json(
                f"https://api.supabase.com/v1/projects/{quote(ref)}/database/backups",
                {"Authorization": "Bearer " + token},
            )
            if recent_backup(payload, datetime.now(UTC)):
                print("Verified recovery coverage or a completed backup within the last 26 hours.")
                return
        except ReleaseError:
            pass
    recipient = required("CHESS_BACKUP_AGE_RECIPIENT", r"age1[0-9a-z]{58}")
    temp = Path(required("RUNNER_TEMP"))
    logical_backup(dsn, recipient, temp / "chessx-backup" / "production.dump.age")


def deploy(environment):
    ref, project, app_origin = target(environment)
    scope = required("VERCEL_SCOPE", r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}")
    token = required("VERCEL_TOKEN")
    auth_enabled = os.environ.get("CHESS_ACCOUNT_ENABLED") or "0"
    if auth_enabled not in ("0", "1"):
        raise ReleaseError("CHESS_ACCOUNT_ENABLED must be 0 or 1.")
    command = [
        "vercel", "deploy", "--project", project, "--scope", scope, "--token", token, "--yes", "--json",
        "--env", f"SUPABASE_URL=https://{ref}.supabase.co",
    ]
    if environment == "preview":
        protected = subprocess.run(
            ["vercel", "api", f"/v9/projects/{project}", "--scope", scope, "--token", token],
            capture_output=True, check=False, text=True, timeout=60,
        )
        try:
            protection = (json.loads(protected.stdout).get("ssoProtection") or {}).get("deploymentType")
        except (ValueError, AttributeError):
            protection = None
        if protected.returncode or protection not in {"all", "preview", "prod_deployment_urls_and_all_previews"}:
            raise ReleaseError("Enable Vercel Authentication on the dedicated Preview project before deploying.")
        command += ["--env", "CHESS_ACCOUNT_ENABLED=0"]
    else:
        command += ["--prod", "--env", f"APP_ORIGIN={app_origin}", "--env", f"CHESS_ACCOUNT_ENABLED={auth_enabled}"]
    completed = subprocess.run(command, capture_output=True, check=False, text=True, timeout=600)
    if completed.returncode:
        raise ReleaseError("Vercel did not complete deployment. Check the project build diagnostic privately.")
    try:
        result = json.loads(completed.stdout)
        deployed = result.get("deployment", result)
        deployment_url = origin(deployed["url"])
    except (AttributeError, KeyError, ValueError, TypeError):
        raise ReleaseError("Vercel CLI did not return verified deployment metadata.") from None
    if deployed.get("readyState") != "READY" or (app_origin and deployed.get("productionUrl") != app_origin):
        raise ReleaseError("Vercel deployment is not ready on the expected domain.")
    protection = deployed.get("deploymentProtection")
    if environment == "preview" and (not isinstance(protection, list) or "vercel_authentication" not in protection):
        raise ReleaseError("Enable Vercel Authentication on the Preview project.")
    print(f"Deployment ready on {app_origin or deployment_url}")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a", encoding="utf-8") as summary:
            print(f"### Vercel {environment}\n\n[{app_origin or deployment_url}]({app_origin or deployment_url})", file=summary)


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["reviewers", "target", "plan", "apply", "backup", "deploy"])
    parser.add_argument("environment", choices=["preview", "staging", "production"])
    args = parser.parse_args()
    try:
        if args.operation == "reviewers":
            require_production_reviewers()
        elif args.operation == "target":
            ref, _, _ = target(args.environment)
            if args.environment != "preview":
                database_url(ref)
            print(f"Verified isolated {args.environment} targets.")
        elif args.operation == "backup":
            if args.environment != "production":
                raise ReleaseError("The release backup only applies to production.")
            guard_backup()
        elif args.operation == "deploy":
            deploy(args.environment)
        else:
            if args.environment == "preview":
                raise ReleaseError("Preview must use the staging schema already deployed.")
            run_db(args.environment, dry_run=args.operation == "plan")
    except (OSError, ReleaseError, ValueError, subprocess.TimeoutExpired) as error:
        # System exceptions may include process arguments or connection credentials.
        message = str(error) if isinstance(error, ReleaseError) else type(error).__name__
        parser.exit(1, f"Release preflight failed: {message}\n")


if __name__ == "__main__":
    main()
