#!/usr/bin/env python3
import unittest
import sqlite3
import datetime
import typemeter_db
import fit_priors
import math

class TestTypeMeter(unittest.TestCase):
    def setUp(self):
        # Use an in-memory SQLite database for fast isolated testing
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        
        # Initialize tables
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS unigram_stats (
                identity_id TEXT,
                char TEXT,
                mistakes REAL,
                total REAL,
                last_updated TEXT,
                PRIMARY KEY (identity_id, char)
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS bigram_stats (
                identity_id TEXT,
                prev_char TEXT,
                char TEXT,
                mistakes REAL,
                total REAL,
                last_updated TEXT,
                PRIMARY KEY (identity_id, prev_char, char)
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS trigram_stats (
                identity_id TEXT,
                prev2_chars TEXT,
                char TEXT,
                mistakes REAL,
                total REAL,
                last_updated TEXT,
                PRIMARY KEY (identity_id, prev2_chars, char)
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS global_priors (
                level TEXT,
                alpha REAL,
                beta REAL,
                fitted_at TEXT,
                sample_size INTEGER,
                PRIMARY KEY (level)
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS mistake_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                identity_id TEXT,
                context_before TEXT,
                expected_char TEXT,
                typed_char TEXT,
                word TEXT,
                position_in_word INTEGER,
                created_at TEXT
            )
        """)
        self.conn.commit()
        
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
            # Ingest 10 mistakes for expected "z"
            recs = []
            for _ in range(10):
                recs.append({
                    "expected_char": "z",
                    "typed_char": "x",
                    "is_correct": False,
                    "context_before": "",
                    "word": "zebra",
                    "position_in_word": 0
                })
            typemeter_db.ingest_mistakes(self.conn, identity_id, recs)
            
            # Select words over 100 trials for cold start user vs bad typist
            count_z_cold = 0
            count_z_biased = 0
            
            for _ in range(100):
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

if __name__ == "__main__":
    unittest.main()
