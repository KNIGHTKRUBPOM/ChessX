"""Offline tests for release isolation, consent, recovery and legitimate redirects."""

from datetime import UTC, datetime, timedelta
import json
from subprocess import CompletedProcess
from unittest import TestCase
from unittest.mock import patch

import release
from smoke_release import check_provider_url


ENV = {
    "APP_ORIGIN": "https://stage.example.test",
    "CHESS_PRODUCTION_ORIGIN": "https://game.example.test",
    "CHESS_STAGING_SUPABASE_REF": "a" * 20,
    "CHESS_PRODUCTION_SUPABASE_REF": "b" * 20,
    "CHESS_STAGING_VERCEL_PROJECT_ID": "prj_STAGE",
    "CHESS_PRODUCTION_VERCEL_PROJECT_ID": "prj_PROD",
    "CHESS_PREVIEW_VERCEL_PROJECT_ID": "prj_PREVIEW",
    "SUPABASE_DB_URL": f"postgresql://postgres.{'a' * 20}:fixture@aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres?sslmode=require",
}


class ReleaseGuards(TestCase):
    def test_staging_and_preview_resolve_to_distinct_apps(self):
        with patch.dict("os.environ", ENV, clear=True):
            ref, project, origin = release.target("staging")
            self.assertEqual((ref, project, origin), ("a" * 20, "prj_STAGE", ENV["APP_ORIGIN"]))
            self.assertEqual(release.target("preview"), (ref, "prj_PREVIEW", None))
            self.assertEqual(release.database_url(ref), ENV["SUPABASE_DB_URL"])

    def test_reused_target_is_rejected(self):
        with patch.dict("os.environ", ENV | {"CHESS_PREVIEW_VERCEL_PROJECT_ID": "prj_PROD"}, clear=True):
            with self.assertRaisesRegex(release.ReleaseError, "own Vercel project"):
                release.target("preview")

    def test_production_connections_are_excluded_from_staging(self):
        with patch.dict("os.environ", ENV | {"SUPABASE_DB_URL": ENV["SUPABASE_DB_URL"].replace("a" * 20, "b" * 20)}, clear=True):
            with self.assertRaisesRegex(release.ReleaseError, "selected project"):
                release.database_url("a" * 20)

    def test_url_options_cannot_change_selected_database(self):
        with patch.dict("os.environ", ENV | {"SUPABASE_DB_URL": ENV["SUPABASE_DB_URL"] + "&dbname=test"}, clear=True):
            with self.assertRaisesRegex(release.ReleaseError, "selected project"):
                release.database_url("a" * 20)

    def test_production_has_required_reviewers(self):
        env = {"GITHUB_REPOSITORY": "example/game", "GH_TOKEN": "fixture"}
        with patch.dict("os.environ", env, clear=True), patch.object(release, "fetch_json", return_value={"protection_rules": []}):
            with self.assertRaisesRegex(release.ReleaseError, "required reviewers"):
                release.require_production_reviewers()

    def test_recovery_window_must_be_current_and_completed(self):
        now = datetime(2026, 11, 16, 0, 0, tzinfo=UTC)
        yesterday = (now - timedelta(hours=24)).isoformat()
        older = (now - timedelta(hours=27)).isoformat()
        self.assertTrue(release.recent_backup({"backups": [{"status": "COMPLETED", "inserted_at": yesterday}]}, now))
        self.assertFalse(release.recent_backup({"backups": [{"status": "COMPLETED", "inserted_at": older}]}, now))
        self.assertFalse(release.recent_backup({"backups": [{"status": "RUNNING", "inserted_at": yesterday}]}, now))
        recovery = (now - timedelta(hours=3)).timestamp()
        self.assertTrue(release.recent_backup({"pitr_enabled": True, "physical_backup_data": {"latest_physical_backup_date_unix": recovery}}, now))

    def test_google_redirect_matches_pinned_environment(self):
        ref = "a" * 20
        origin = ENV["APP_ORIGIN"]
        url = (
            f"https://{ref}.supabase.co/auth/v1/authorize?provider=google"
            f"&code_challenge={'x' * 43}&code_challenge_method=s256"
            "&redirect_to=https%3A%2F%2Fstage.example.test%2Fapi%2Faccount%2Foauth%2Fcallback"
        )
        check_provider_url(url, ref, "google", origin)
        with self.assertRaisesRegex(release.ReleaseError, "redirect"):
            check_provider_url(url, ref, "google", "https://game.example.test")

    def test_staging_accepts_both_vercel_cli_json_formats(self):
        env = ENV | {"VERCEL_SCOPE": "test-team", "VERCEL_TOKEN": "fixture"}
        deployment = {
            "url": "https://release.example.test",
            "productionUrl": ENV["APP_ORIGIN"],
            "readyState": "READY",
        }
        for payload in (deployment, {"status": "ok", "deployment": deployment}):
            with (
                self.subTest(payload=payload),
                patch.dict("os.environ", env, clear=True),
                patch.object(release.subprocess, "run", return_value=CompletedProcess([], 0, json.dumps(payload))),
                patch("builtins.print"),
            ):
                release.deploy("staging")

    def test_preview_rejects_unavailable_deployment_protection_metadata(self):
        env = ENV | {"VERCEL_SCOPE": "test-team", "VERCEL_TOKEN": "fixture"}
        project = {"ssoProtection": {"deploymentType": "all"}}
        deployment = {"url": "https://preview.example.test", "readyState": "READY", "deploymentProtection": None}
        responses = [CompletedProcess([], 0, json.dumps(body)) for body in (project, deployment)]
        with (
            patch.dict("os.environ", env, clear=True),
            patch.object(release.subprocess, "run", side_effect=responses),
            self.assertRaisesRegex(release.ReleaseError, "Enable Vercel Authentication"),
        ):
            release.deploy("preview")
