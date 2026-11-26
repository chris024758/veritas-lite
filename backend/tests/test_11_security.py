"""Regression coverage for authentication, account isolation and request limits."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import db
import main
import security
import seed
from auth_test_helpers import TEST_PASSWORD, seed_demo, sign_in
from tools import image_gen

PNG_HEADER = b"\x89PNG\r\n\x1a\n"


class SecurityTests(unittest.TestCase):
    def setUp(self):
        self.directory = self.enterContext(tempfile.TemporaryDirectory())
        folder = Path(self.directory)
        self.enterContext(patch.object(db, "DB_PATH", folder / "security.db"))
        self.enterContext(patch.object(main, "UPLOAD_DIR", folder))
        self.enterContext(patch.object(main, "OUTPUT_DIR", folder))
        self.enterContext(patch.object(image_gen, "OUTPUT_DIR", folder))
        seed_demo()
        with db.connect() as conn:
            password_hash = conn.execute("SELECT password_hash FROM accounts WHERE username = 'demo123'").fetchone()[0]
            conn.execute("INSERT INTO accounts VALUES (?, ?)", ("investigator", password_hash))
            conn.executemany("INSERT INTO cases (id, name, owner) VALUES (?, ?, ?)", [
                ("PRIVATE", "Private case", "investigator"), ("LEGACY", "Unassigned case", None),
            ])
        self.client = self.enterContext(TestClient(main.app))

    def test_authentication_expiry_and_logout(self):
        self.assertEqual(self.client.get("/cases").status_code, 401)
        self.assertEqual(self.client.get("/static/evidence/ring.svg").status_code, 401)
        for username in ("demo123", "unknown"):
            failed = self.client.post("/auth/login", json={"username": username, "password": "wrong"})
            self.assertEqual((failed.status_code, failed.json()), (401, {"detail": "Invalid username or password"}))
        invalid = self.client.post("/auth/login", json={"username": "demo123", "password": "sensitive" * 40})
        self.assertEqual(invalid.status_code, 422)
        self.assertNotIn("sensitive", invalid.text)
        signed_in = sign_in(self.client)
        self.assertIn("HttpOnly", signed_in.headers["Set-Cookie"])
        self.assertIn("SameSite=strict", signed_in.headers["Set-Cookie"])
        self.assertEqual(signed_in.headers["Cache-Control"], "no-store")
        self.assertEqual(signed_in.headers["X-Content-Type-Options"], "nosniff")
        token = self.client.cookies.get(security.COOKIE)
        with db.connect() as conn:
            self.assertNotEqual(conn.execute("SELECT token_hash FROM auth_sessions").fetchone()[0], token)
        sign_in(self.client)
        replay = {security.COOKIE: token}
        with TestClient(main.app, cookies=replay) as old_client:
            self.assertEqual(old_client.get("/cases").status_code, 401)

        self.assertEqual(self.client.get("/auth/session").json(), {"username": "demo123"})
        with db.connect() as conn:
            conn.execute("UPDATE auth_sessions SET expires_at = 0")
        self.assertEqual(self.client.get("/cases").status_code, 401)
        sign_in(self.client)
        replay = {security.COOKIE: self.client.cookies.get(security.COOKIE)}
        self.assertEqual(self.client.post("/auth/logout").status_code, 204)
        with TestClient(main.app, cookies=replay) as old_client:
            self.assertEqual(old_client.get("/cases").status_code, 401)

    def test_ownership_for_cases_sessions_subjects_and_files(self):
        demo_case = f"/cases/{seed.CASE_ID}"
        sign_in(self.client)
        self.assertEqual(len(self.client.get("/cases").json()), 3)
        for case_id in ("PRIVATE", "LEGACY"):
            self.assertEqual(self.client.get(f"/cases/{case_id}").status_code, 404)
        self.assertEqual(self.client.get("/static/evidence/ring.svg").status_code, 200)
        subject_id = self.client.get(demo_case).json()["subjects"][0]["id"]
        started = self.client.post("/sessions/start", json={"case_id": seed.CASE_ID, "subject_id": subject_id})
        session = f"/sessions/{started.json()['session_id']}"
        attachments = f"{session}/attachments"
        bad = self.client.post(attachments, files={"image": ("bad.png", b"<html>", "image/png")})
        self.assertEqual(bad.status_code, 415)
        attachment = self.client.post(attachments, files={"image": ("image.png", PNG_HEADER, "image/png")}).json()
        with patch.dict("os.environ", {"CLOUDFLARE_ACCOUNT_ID": "", "CLOUDFLARE_API_TOKEN": ""}):
            generated = self.client.post("/tools/generate-image", json={"description": "Test image"}).json()["image_url"]
        for path in (attachment["url"], generated):
            self.assertEqual(self.client.get(path).status_code, 200)
            self.assertEqual(self.client.head(path).status_code, 200)
            with TestClient(main.app) as guest:
                self.assertEqual(guest.get(path).status_code, 401)
        with TestClient(main.app) as other:
            sign_in(other, username="investigator")
            self.assertEqual([case["id"] for case in other.get("/cases").json()], ["PRIVATE"])
            for path in (demo_case, f"{demo_case}/timeline", f"{demo_case}/findings", session, f"{session}/report",
                         f"{session}/report.docx", attachment["url"], generated, "/static/evidence/ring.svg"):
                self.assertEqual(other.get(path).status_code, 404, path)
            self.assertEqual(other.patch(f"/subjects/{subject_id}", json={"role": "Witness"}).status_code, 404)
            self.assertEqual(other.post("/sessions/start", json={"case_id": seed.CASE_ID,
                                                                "subject_id": subject_id}).status_code, 404)
            self.assertEqual(other.post(f"{session}/end").status_code, 404)
            extract = f"{attachments}/{attachment['id']}/extract"
            self.assertEqual(other.post(extract).status_code, 404)

    def test_cors_and_cross_origin_writes(self):
        cors = {"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type"}
        allowed = self.client.options("/auth/login", headers=cors)
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(allowed.headers["Access-Control-Allow-Origin"], cors["Origin"])
        self.assertEqual(allowed.headers["Access-Control-Allow-Credentials"], "true")
        cors["Origin"] = "http://localhost:5174"
        denied = self.client.options("/auth/login", headers=cors)
        self.assertEqual(denied.status_code, 400)
        self.assertNotIn("Access-Control-Allow-Origin", denied.headers)
        result = self.client.post("/auth/login", headers={"Origin": cors["Origin"]},
                                  json={"username": "demo123", "password": TEST_PASSWORD})
        self.assertEqual(result.status_code, 403)
        sign_in(self.client)
        self.assertEqual(self.client.post("/auth/logout", headers={"Origin": "null"}).status_code, 403)
        self.assertEqual(self.client.get("/cases").status_code, 200)

    def test_production_requires_https_and_disables_demo_by_default(self):
        with (
            patch.object(security, "PRODUCTION", True),
            patch.object(security, "DEMO_ENABLED", False),
            patch.object(security, "COOKIE", "__Host-veritas_session"),
            TestClient(main.app, base_url="https://api.example.com") as https,
        ):
            self.assertEqual(self.client.get("/cases").status_code, 400)
            demo = https.post("/auth/login", json={"username": "demo123", "password": TEST_PASSWORD})
            self.assertEqual(demo.status_code, 401)
            signed_in = sign_in(https, username="investigator")
            self.assertTrue(signed_in.headers["Set-Cookie"].startswith("__Host-veritas_session="))
            self.assertIn("; Secure", signed_in.headers["Set-Cookie"])
            self.assertEqual(https.get("/cases").headers["Strict-Transport-Security"], "max-age=31536000")

    def test_rate_limits_and_bounded_request_bodies(self):
        with patch.object(security, "LOGIN_LIMIT", 1):
            sign_in(self.client)
            limited = self.client.post("/auth/login", json={"username": "demo123", "password": TEST_PASSWORD})
            self.assertEqual(limited.status_code, 429)
            self.assertGreater(int(limited.headers["Retry-After"]), 0)
        with patch.object(security, "API_LIMIT", 1):
            self.assertEqual(self.client.get("/cases").status_code, 200)
            self.assertEqual(self.client.get("/cases", headers={"X-Forwarded-For": "192.0.2.1"}).status_code, 429)
        body = b"x" * (security.MAX_JSON_BYTES + 1)
        self.assertEqual(self.client.post("/tools/generate-image", content=body).status_code, 413)
        chunks = iter((b'{"description":"', body, b'"}'))
        streamed = self.client.post("/tools/generate-image", content=chunks, headers={"Content-Type": "application/json"})
        self.assertEqual(streamed.status_code, 413)
        with patch.object(security, "TOOL_LIMIT", 2):
            limited = self.client.post("/tools/generate-image", json={"description": "Test"})
            self.assertEqual(limited.status_code, 429)

    def test_seed_migrates_demo_fixtures_without_claiming_private_data(self):
        with db.connect() as conn:
            conn.execute("UPDATE cases SET owner = NULL WHERE owner = 'demo123'")
        seed.seed()
        self.assertEqual(len(db.list_cases("demo123")), 3)
        with db.connect() as conn:
            conn.execute("UPDATE cases SET owner = NULL WHERE id = ?", (seed.CASE_ID,))
        db.create_session(seed.CASE_ID, "Suresh Deshmukh")
        with self.assertRaises(ValueError):
            seed.seed()
        self.assertFalse(db.owns_case(seed.CASE_ID, "demo123"))


if __name__ == "__main__":
    unittest.main()
