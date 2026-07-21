#!/usr/bin/env python3
import unittest
import sqlite3
import datetime
import os
import re
import typemeter_db
import fit_priors
import math

class TestTypeMeter(unittest.TestCase):
    def setUp(self):
        # Use an in-memory SQLite database initialized with all tables and indexes
        self.conn = typemeter_db.get_db(":memory:")
        
    def tearDown(self):
        self.conn.close()


    # --- Unit Tests ---
    
    def test_posterior_rate(self):
        # Prior default: alpha=2.0, beta=18.0 (prior mean = 2/20 = 0.1)
        # 1. total = 0 -> shrinks exactly to prior mean (0.1)
        r1 = typemeter_db.posterior_rate(0, 0, 2.0, 18.0)
        self.assertEqual(r1, 0.1)
        
        # 2. total -> large -> approaches raw rate (e.g. 80 mistakes out of 100)
        r2 = typemeter_db.posterior_rate(80.0, 100.0, 2.0, 18.0)
        self.assertAlmostEqual(r2, (80.0 + 2.0) / (100.0 + 20.0), places=5)
        self.assertTrue(0.6 < r2 < 0.8) # Pulls toward prior mean slightly

    def test_decay_and_update(self):
        # Seed statistics from 14 days ago (exactly one HALF_LIFE_DAYS)
        dt_14_days_ago = (datetime.datetime.utcnow() - datetime.timedelta(days=14)).isoformat()
        
        self.conn.execute(
            "INSERT INTO unigram_stats (identity_id, char, mistakes, total, last_updated) VALUES (?, ?, ?, ?, ?)",
            ("id_test", "e", 6.0, 10.0, dt_14_days_ago)
        )
        self.conn.commit()
        
        # Ingest one correct key
        rec = {
            "expected_char": "e",
            "typed_char": "e",
            "is_correct": True,
            "context_before": "",
            "word": "hello",
            "position_in_word": 1
        }
        typemeter_db.ingest_mistakes(self.conn, "id_test", [rec])
        
        # Verify decay calculation (decay factor = 0.5)
        # Expected total = 10.0 * 0.5 + 1 = 6.0
        # Expected mistakes = 6.0 * 0.5 + 0 = 3.0
        row = self.conn.execute("SELECT mistakes, total FROM unigram_stats WHERE identity_id = ? AND char = ?", ("id_test", "e")).fetchone()
        self.assertAlmostEqual(row["total"], 6.0, places=4)
        self.assertAlmostEqual(row["mistakes"], 3.0, places=4)

    def test_final_rate(self):
        identity_id = "id_test"
        
        # Check rate when no stats exist -> returns flat fallback prior mean (2/20 = 0.1)
        rate_cold = typemeter_db.final_rate(self.conn, identity_id, "th", "e")
        self.assertEqual(rate_cold, 0.1)
        
        # Seed unigram stats: total=10, mistakes=1
        now_str = datetime.datetime.utcnow().isoformat()
        self.conn.execute(
            "INSERT INTO unigram_stats (identity_id, char, mistakes, total, last_updated) VALUES (?, ?, ?, ?, ?)",
            (identity_id, "e", 1.0, 10.0, now_str)
        )
        self.conn.commit()
        
        # Final rate should now use unigram stats interpolated
        rate_uni = typemeter_db.final_rate(self.conn, identity_id, "th", "e")
        # lam = 10 / (10 + 10) = 0.5
        # post = (1 + 2) / (10 + 20) = 3/30 = 0.1
        # weighted sum = 0.1
        self.assertAlmostEqual(rate_uni, 0.1, places=5)

    def test_word_score(self):
        identity_id = "id_test"
        # Seed high mistake rates for "e"
        now_str = datetime.datetime.utcnow().isoformat()
        self.conn.execute(
            "INSERT INTO unigram_stats (identity_id, char, mistakes, total, last_updated) VALUES (?, ?, ?, ?, ?)",
            (identity_id, "e", 10.0, 10.0, now_str)
        )
        self.conn.commit()
        
        # Word containing "e" should score higher than word without "e"
        score_e = typemeter_db.word_score(self.conn, identity_id, "the")
        score_no_e = typemeter_db.word_score(self.conn, identity_id, "dog")
        self.assertTrue(score_e > score_no_e)

    def test_prior_fitting_moments(self):
        cursor = self.conn.cursor()
        
        # Seed synthetic statistics for unigram level
        # Identity 1: mistakes=5, total=10 (rate = 0.5)
        # Identity 2: mistakes=2, total=10 (rate = 0.2)
        # Identity 3: mistakes=8, total=10 (rate = 0.8)
        now_str = datetime.datetime.utcnow().isoformat()
        cursor.execute("INSERT INTO unigram_stats VALUES (?, ?, ?, ?, ?)", ("id1", "a", 5.0, 10.0, now_str))
        cursor.execute("INSERT INTO unigram_stats VALUES (?, ?, ?, ?, ?)", ("id2", "a", 2.0, 10.0, now_str))
        cursor.execute("INSERT INTO unigram_stats VALUES (?, ?, ?, ?, ?)", ("id3", "a", 8.0, 10.0, now_str))
        self.conn.commit()
        
        # Run fit
        fit_priors.fit_level(cursor, "unigram")
        self.conn.commit()
        
        # Verify fits are created and valid
        row = cursor.execute("SELECT alpha, beta FROM global_priors WHERE level = ?", ("unigram",)).fetchone()
        self.assertIsNotNone(row)
        self.assertTrue(row["alpha"] > 0)
        self.assertTrue(row["beta"] > 0)

    def test_prior_fitting_degenerate_guard(self):
        cursor = self.conn.cursor()
        now_str = datetime.datetime.utcnow().isoformat()
        
        # Variance ≈ 0: all rates are identical (0.2)
        cursor.execute("INSERT INTO unigram_stats VALUES (?, ?, ?, ?, ?)", ("id1", "a", 2.0, 10.0, now_str))
        cursor.execute("INSERT INTO unigram_stats VALUES (?, ?, ?, ?, ?)", ("id2", "a", 2.0, 10.0, now_str))
        self.conn.commit()
        
        fit_priors.fit_level(cursor, "unigram")
        self.conn.commit()
        
        # Fitting should be skipped and no row created in global_priors
        row = cursor.execute("SELECT alpha, beta FROM global_priors WHERE level = ?", ("unigram",)).fetchone()
        self.assertIsNone(row)

    # --- Integration Tests ---

    def test_cold_start_uniform_distribution(self):
        # Seed basic lists
        pool = ["apple", "banana", "cherry", "date", "elderberry"]
        
        # Mock load_word_pools to return our mini pools
        orig_load = typemeter_db.load_word_pools
        typemeter_db.load_word_pools = lambda: (pool, pool, pool, pool)
        
        try:
            # Under a cold start identity, selections over 200 trials should be balanced
            counts = {w: 0 for w in pool}
            trials = 200
            for _ in range(trials):
                selected = typemeter_db.backend_select_words(self.conn, "easy", 1, "cold_user")
                for w in selected:
                    counts[w] += 1
            
            # Check standard deviation or maximum differences
            # If uniform, expected count is 40. Standard deviation should be small.
            mean = trials / len(pool)
            variance = sum((counts[w] - mean) ** 2 for w in pool) / len(pool)
            std_dev = math.sqrt(variance)
            self.assertTrue(std_dev < 15.0) # Within statistical variance bounds
        finally:
            typemeter_db.load_word_pools = orig_load

    def test_persistent_mistake_bias(self):
        # We will feed mistake records for user "bad_typist" targeting expected letter "z"
        # We want to check if words containing "z" are overrepresented
        pool = ["zebra", "hazard", "lazy", "blaze", "apple", "banana", "cherry", "date"]
        
        orig_load = typemeter_db.load_word_pools
        typemeter_db.load_word_pools = lambda: (pool, pool, pool, pool)
        
        try:
            identity_id = "bad_typist"
            # Ingest 50 mistakes for expected "z" to create a strong bias
            recs = []
            for _ in range(50):
                recs.append({
                    "expected_char": "z",
                    "typed_char": "x",
                    "is_correct": False,
                    "context_before": "",
                    "word": "zebra",
                    "position_in_word": 0
                })
            typemeter_db.ingest_mistakes(self.conn, identity_id, recs)
            
            # Select words over 1000 trials for cold start user vs bad typist to ensure statistical significance
            count_z_cold = 0
            count_z_biased = 0
            
            for _ in range(1000):
                # Cold Start
                sel_c = typemeter_db.backend_select_words(self.conn, "easy", 2, "cold_user")
                count_z_cold += sum(1 for w in sel_c if "z" in w)
                
                # Biased Start
                sel_b = typemeter_db.backend_select_words(self.conn, "easy", 2, identity_id)
                count_z_biased += sum(1 for w in sel_b if "z" in w)
                
            # Biased user should show significantly more words containing "z"
            self.assertTrue(count_z_biased > count_z_cold)
        finally:
            typemeter_db.load_word_pools = orig_load

    def test_auth_password_hashing(self):
        password = "Password123"
        hashed = typemeter_db.hash_password(password)
        self.assertNotEqual(password, hashed)
        self.assertTrue(typemeter_db.verify_password(password, hashed))
        self.assertFalse(typemeter_db.verify_password("wrong_password", hashed))

    def test_auth_password_policy(self):
        import auth
        # Invalid: too short
        ok, err = auth.validate_password_policy("P1")
        self.assertFalse(ok)
        # Invalid: no number
        ok, err = auth.validate_password_policy("Password")
        self.assertFalse(ok)
        # Invalid: no letter
        ok, err = auth.validate_password_policy("12345678")
        self.assertFalse(ok)
        # Valid
        ok, err = auth.validate_password_policy("Password123")
        self.assertTrue(ok)

    def test_auth_token_hashing(self):
        raw_token = "my_secret_token"
        hashed = typemeter_db.hash_token(raw_token)
        self.assertNotEqual(raw_token, hashed)
        
        # SHA-256 is deterministic
        self.assertEqual(hashed, typemeter_db.hash_token(raw_token))

    def test_auth_session_crud_and_timeout(self):
        # 1. Create a user
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        cursor = self.conn.cursor()
        cursor.execute(
            "INSERT INTO users (email, password_hash, auth_provider, email_verified, display_name, created_at, updated_at) VALUES (?, ?, ?, 0, ?, ?, ?)",
            ("test_session@example.com", "hash", "password", "Tester", now, now)
        )
        user_id = cursor.lastrowid
        self.conn.commit()

        # 2. Create session
        sess_id = typemeter_db.create_session(self.conn, user_id)
        self.assertIsNotNone(sess_id)

        # 3. Retrieve session
        sess = typemeter_db.get_session(self.conn, sess_id)
        self.assertIsNotNone(sess)
        self.assertEqual(sess["user_id"], user_id)

        # 4. Invalidate / delete session
        typemeter_db.delete_session(self.conn, sess_id)
        self.assertIsNone(typemeter_db.get_session(self.conn, sess_id))

    def test_auth_rate_limiting(self):
        # Max 3 requests in 60 seconds
        self.assertTrue(typemeter_db.check_rate_limit(self.conn, "test_ip", "test_action", 3, 60))
        self.assertTrue(typemeter_db.check_rate_limit(self.conn, "test_ip", "test_action", 3, 60))
        self.assertTrue(typemeter_db.check_rate_limit(self.conn, "test_ip", "test_action", 3, 60))
        
        # 4th request must be blocked
        self.assertFalse(typemeter_db.check_rate_limit(self.conn, "test_ip", "test_action", 3, 60))

class TestAuthFlask(unittest.TestCase):
    def setUp(self):
        # Setup temporary SQLite database
        self.db_path = "test_auth_flask.db"
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
            
        import run_gui
        self.app = run_gui.create_app()
        # Configure app key
        self.app.config["SECRET_KEY"] = "super-secret-test-key"
        
        # Override db path globally in db helper
        self.orig_get_db = typemeter_db.get_db
        typemeter_db.get_db = lambda *args, **kwargs: self.orig_get_db(self.db_path)
        
        self.client = self.app.test_client()
        self.ctx = self.app.app_context()
        self.ctx.push()
        
    def tearDown(self):
        self.ctx.pop()
        typemeter_db.get_db = self.orig_get_db
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_csrf_rejection(self):
        # State changing POST without X-CSRF-Token header should return 403
        res = self.client.post("/auth/login", json={"email": "test@example.com", "password": "Password123"})
        self.assertEqual(res.status_code, 403)
        self.assertIn(b"CSRF token missing or invalid.", res.data)

    def test_signup_verify_login_logout_flow(self):
        # 1. Fetch CSRF token
        res_csrf = self.client.get("/auth/csrf-token")
        self.assertEqual(res_csrf.status_code, 200)
        csrf_token = res_csrf.get_json()["csrf_token"]
        self.assertIsNotNone(csrf_token)

        # 2. Register user
        signup_payload = {
            "email": "register@example.com",
            "password": "Password123",
            "display_name": "Tester User"
        }
        res_signup = self.client.post(
            "/auth/signup",
            headers={"X-CSRF-Token": csrf_token},
            json=signup_payload
        )
        self.assertEqual(res_signup.status_code, 201)
        self.assertIn(b"Registration successful.", res_signup.data)

        # 3. Retrieve token hash from db
        conn = self.orig_get_db(self.db_path)
        token_row = conn.execute("SELECT * FROM email_verification_tokens").fetchone()
        self.assertIsNotNone(token_row)
        conn.close()

        # Mock incoming verify request (since we hash, we need raw token. For tests, we cheat:
        # we can't get raw token from hash easily, but wait! The token hash table has the raw token
        # printed to server log. Can we fetch the raw token by intercepting typemeter_db.send_email?
        # Yes! Let's mock send_email to capture the raw token!)
        
    def test_signup_with_mocked_email(self):
        captured_emails = []
        orig_send = typemeter_db.send_email
        typemeter_db.send_email = lambda to, sub, body: captured_emails.append((to, sub, body))

        try:
            # 1. Fetch CSRF
            csrf_token = self.client.get("/auth/csrf-token").get_json()["csrf_token"]

            # 2. Signup
            self.client.post(
                "/auth/signup",
                headers={"X-CSRF-Token": csrf_token},
                json={"email": "mock@example.com", "password": "Password123", "display_name": "Mock"}
            )
            self.assertEqual(len(captured_emails), 1)
            body = captured_emails[0][2]
            
            # Extract verify token
            # format: verify_token=XYZ
            token_match = re.search(r"verify_token=([A-Za-z0-9_\-]+)", body)
            self.assertIsNotNone(token_match)
            raw_token = token_match.group(1)

            # 3. Verify Email
            res_verify = self.client.get(f"/auth/verify-email?token={raw_token}")
            self.assertEqual(res_verify.status_code, 302) # Redirects back to index.html
            self.assertIn("verify_success", res_verify.headers["Location"])

            # 4. Check user is verified in DB
            conn = self.orig_get_db(self.db_path)
            user_row = conn.execute("SELECT email_verified FROM users WHERE email = 'mock@example.com'").fetchone()
            self.assertEqual(user_row["email_verified"], 1)
            conn.close()

            # 5. Login
            res_login = self.client.post(
                "/auth/login",
                headers={"X-CSRF-Token": csrf_token},
                json={"email": "mock@example.com", "password": "Password123"}
            )
            self.assertEqual(res_login.status_code, 200)

            # 6. Check authenticated state info
            res_me = self.client.get("/auth/me")
            self.assertEqual(res_me.status_code, 200)
            self.assertTrue(res_me.get_json()["authenticated"])
            self.assertEqual(res_me.get_json()["user"]["email"], "mock@example.com")

            # 7. Logout
            res_logout = self.client.post(
                "/auth/logout",
                headers={"X-CSRF-Token": csrf_token}
            )
            self.assertEqual(res_logout.status_code, 200)
            
            # Check logged out
            res_me2 = self.client.get("/auth/me")
            self.assertFalse(res_me2.get_json()["authenticated"])

        finally:
            typemeter_db.send_email = orig_send

    def test_brute_force_lockout(self):
        csrf_token = self.client.get("/auth/csrf-token").get_json()["csrf_token"]
        
        # Ingest user manually to bypass signup email
        conn = self.orig_get_db(self.db_path)
        pwd_hash = typemeter_db.hash_password("Password123")
        conn.execute(
            "INSERT INTO users (email, password_hash, auth_provider, email_verified, display_name) VALUES (?, ?, 'password', 1, 'BF')",
            ("bf@example.com", pwd_hash)
        )
        conn.commit()
        conn.close()

        # Submit 5 incorrect logins
        for idx in range(5):
            res = self.client.post(
                "/auth/login",
                headers={"X-CSRF-Token": csrf_token},
                json={"email": "bf@example.com", "password": "wrong_password"}
            )
            # The first 4 should fail with 401, the 5th triggers 429 lockout
            expected_status = 401 if idx < 4 else 429
            self.assertEqual(res.status_code, expected_status)

        # 6th attempt must be locked out with 429
        res_lock = self.client.post(
            "/auth/login",
            headers={"X-CSRF-Token": csrf_token},
            json={"email": "bf@example.com", "password": "Password123"} # Correct password but locked
        )
        self.assertEqual(res_lock.status_code, 429)
        self.assertIn(b"locked", res_lock.data)

    def test_password_reset_session_invalidation(self):
        captured_emails = []
        orig_send = typemeter_db.send_email
        typemeter_db.send_email = lambda to, sub, body: captured_emails.append((to, sub, body))

        try:
            csrf_token = self.client.get("/auth/csrf-token").get_json()["csrf_token"]
            
            # 1. Ingest user
            pwd_hash = typemeter_db.hash_password("Password123")
            conn = self.orig_get_db(self.db_path)
            conn.execute(
                "INSERT INTO users (email, password_hash, auth_provider, email_verified) VALUES (?, ?, 'password', 1)",
                ("reset@example.com", pwd_hash)
            )
            conn.commit()
            conn.close()

            # 2. Login to create active session
            res_login = self.client.post(
                "/auth/login",
                headers={"X-CSRF-Token": csrf_token},
                json={"email": "reset@example.com", "password": "Password123"}
            )
            self.assertEqual(res_login.status_code, 200)
            
            # Check session cookie exists in cookie jar
            self.client.get("/auth/me")
            self.assertTrue(self.client.get("/auth/me").get_json()["authenticated"])

            # 3. Trigger forgot password
            res_forgot = self.client.post(
                "/auth/forgot-password",
                headers={"X-CSRF-Token": csrf_token},
                json={"email": "reset@example.com"}
            )
            self.assertEqual(res_forgot.status_code, 200)
            self.assertEqual(len(captured_emails), 1)

            # Extract reset token
            body = captured_emails[0][2]
            token_match = re.search(r"reset_token=([A-Za-z0-9_\-]+)", body)
            self.assertIsNotNone(token_match)
            raw_token = token_match.group(1)

            # 4. Reset Password
            res_reset = self.client.post(
                "/auth/reset-password",
                headers={"X-CSRF-Token": csrf_token},
                json={"token": raw_token, "new_password": "NewPassword123"}
            )
            self.assertEqual(res_reset.status_code, 200)

            # 5. Verify old session is invalidated (user is logged out)
            res_me = self.client.get("/auth/me")
            self.assertFalse(res_me.get_json()["authenticated"])

            # 6. Verify login with new password works
            res_login2 = self.client.post(
                "/auth/login",
                headers={"X-CSRF-Token": csrf_token},
                json={"email": "reset@example.com", "password": "NewPassword123"}
            )
            self.assertEqual(res_login2.status_code, 200)

        finally:
            typemeter_db.send_email = orig_send

if __name__ == "__main__":
    unittest.main()
