import sqlite3
import os
import re
import ast
import math
import random
import datetime
import bcrypt
import hashlib
import secrets
import smtplib
from email.mime.text import MIMEText

# --- Configuration Constants ---
HALF_LIFE_DAYS = 14.0
INTERP_K = 10.0
SELECTION_TEMPERATURE = 0.2
SELECTION_EPSILON = 0.3
FALLBACK_ALPHA = 2.0
FALLBACK_BETA = 18.0
USE_FITTED_PRIORS = False

ALLOWED_SHORT = {"a", "i", "of", "to", "in", "it", "is", "on", "by", "or", "be", "at", "as", "an", "we", "us", "if", "my", "do", "no", "he", "up", "so", "am", "me", "go"}

# --- Database Setup & Pooling Layer ---
_pg_pool = None

POSTGRES_SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS unigram_stats (
        identity_id VARCHAR(255) NOT NULL,
        char VARCHAR(10) NOT NULL,
        mistakes DOUBLE PRECISION DEFAULT 0.0,
        total DOUBLE PRECISION DEFAULT 0.0,
        last_updated VARCHAR(100) NOT NULL,
        PRIMARY KEY (identity_id, char)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS bigram_stats (
        identity_id VARCHAR(255) NOT NULL,
        prev_char VARCHAR(10) NOT NULL,
        char VARCHAR(10) NOT NULL,
        mistakes DOUBLE PRECISION DEFAULT 0.0,
        total DOUBLE PRECISION DEFAULT 0.0,
        last_updated VARCHAR(100) NOT NULL,
        PRIMARY KEY (identity_id, prev_char, char)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS trigram_stats (
        identity_id VARCHAR(255) NOT NULL,
        prev2_chars VARCHAR(10) NOT NULL,
        char VARCHAR(10) NOT NULL,
        mistakes DOUBLE PRECISION DEFAULT 0.0,
        total DOUBLE PRECISION DEFAULT 0.0,
        last_updated VARCHAR(100) NOT NULL,
        PRIMARY KEY (identity_id, prev2_chars, char)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS global_priors (
        level VARCHAR(50) PRIMARY KEY,
        alpha DOUBLE PRECISION NOT NULL,
        beta DOUBLE PRECISION NOT NULL,
        fitted_at VARCHAR(100) NOT NULL,
        sample_size INTEGER DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS mistake_events (
        id SERIAL PRIMARY KEY,
        identity_id VARCHAR(255) NOT NULL,
        context_before VARCHAR(20),
        expected_char VARCHAR(10),
        typed_char VARCHAR(10),
        word VARCHAR(100),
        position_in_word INTEGER DEFAULT 0,
        created_at VARCHAR(100) NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        email VARCHAR(255) UNIQUE NOT NULL,
        password_hash TEXT,
        auth_provider VARCHAR(50) NOT NULL,
        google_id VARCHAR(255) UNIQUE,
        email_verified BOOLEAN DEFAULT FALSE,
        display_name VARCHAR(255),
        failed_login_attempts INTEGER DEFAULT 0,
        lockout_until VARCHAR(100),
        created_at VARCHAR(100) NOT NULL,
        updated_at VARCHAR(100) NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS email_verification_tokens (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        token_hash VARCHAR(255) UNIQUE NOT NULL,
        expires_at VARCHAR(100) NOT NULL,
        used_at VARCHAR(100),
        created_at VARCHAR(100) NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS password_reset_tokens (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        token_hash VARCHAR(255) UNIQUE NOT NULL,
        expires_at VARCHAR(100) NOT NULL,
        used_at VARCHAR(100),
        created_at VARCHAR(100) NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sessions (
        session_id VARCHAR(255) PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        created_at VARCHAR(100) NOT NULL,
        last_seen_at VARCHAR(100) NOT NULL,
        expires_at VARCHAR(100) NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ip_rate_limits (
        key VARCHAR(255) NOT NULL,
        action VARCHAR(100) NOT NULL,
        timestamp VARCHAR(100) NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS typing_sessions (
        id SERIAL PRIMARY KEY,
        identity_id VARCHAR(255) NOT NULL,
        user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
        wpm DOUBLE PRECISION NOT NULL,
        raw_wpm DOUBLE PRECISION NOT NULL,
        accuracy DOUBLE PRECISION NOT NULL,
        mistakes_count INTEGER DEFAULT 0,
        total_chars INTEGER DEFAULT 0,
        time_seconds DOUBLE PRECISION DEFAULT 0.0,
        difficulty VARCHAR(50) NOT NULL DEFAULT 'easy',
        created_at VARCHAR(100) NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)",
    "CREATE INDEX IF NOT EXISTS idx_users_google_id ON users(google_id)",
    "CREATE INDEX IF NOT EXISTS idx_email_tokens_hash ON email_verification_tokens(token_hash)",
    "CREATE INDEX IF NOT EXISTS idx_reset_tokens_hash ON password_reset_tokens(token_hash)",
    "CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_rate_limits_key_timestamp ON ip_rate_limits(key, timestamp)",
    "CREATE INDEX IF NOT EXISTS idx_typing_sessions_user_id ON typing_sessions(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_typing_sessions_identity ON typing_sessions(identity_id)",
]

_pg_pool = None

def get_pg_pool(db_url):
    """Initializes or retrieves the PostgreSQL connection pool."""
    global _pg_pool
    if _pg_pool is None:
        try:
            import psycopg2.pool
            if db_url.startswith("postgres://"):
                db_url = db_url.replace("postgres://", "postgresql://", 1)
            _pg_pool = psycopg2.pool.ThreadedConnectionPool(minconn=1, maxconn=20, dsn=db_url)
            
            # Execute schema initialization once on pool startup
            init_conn = _pg_pool.getconn()
            try:
                init_postgres_schema(init_conn)
            finally:
                _pg_pool.putconn(init_conn)
        except Exception as e:
            raise RuntimeError(f"Failed to initialize PostgreSQL connection pool: {e}")
    return _pg_pool

class PostgresCursorWrapper:
    """Wrapper around psycopg2 RealDictCursor providing sqlite3.Row compatibility."""
    def __init__(self, cursor):
        self._cursor = cursor
        self._lastrowid = None

    def execute(self, sql, params=()):
        if "?" in sql:
            sql = sql.replace("?", "%s")
        if "INSERT INTO" in sql and "RETURNING" not in sql:
            if any(t in sql for t in ["typing_sessions", "mistake_events", "users", "email_verification_tokens", "password_reset_tokens"]):
                sql += " RETURNING id"
                self._cursor.execute(sql, params)
                res = self._cursor.fetchone()
                if res and "id" in res:
                    self._lastrowid = res["id"]
                return self
        self._cursor.execute(sql, params)
        return self

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()

    @property
    def lastrowid(self):
        return self._lastrowid

class PostgresConnectionWrapper:
    """Wrapper for PostgreSQL connections providing sqlite3-compatible interface."""
    def __init__(self, pg_conn, pool=None):
        self._conn = pg_conn
        self._pool = pool
        self.is_postgres = True

    def cursor(self):
        from psycopg2.extras import RealDictCursor
        return PostgresCursorWrapper(self._conn.cursor(cursor_factory=RealDictCursor))

    def execute(self, sql, params=()):
        c = self.cursor()
        c.execute(sql, params)
        return c

    def commit(self):
        return self._conn.commit()

    def rollback(self):
        return self._conn.rollback()

    def close(self):
        if self._pool:
            self._pool.putconn(self._conn)
        else:
            self._conn.close()

def init_postgres_schema(pg_conn):
    """Executes PostgreSQL DDL statements."""
    cursor = pg_conn.cursor()
    for stmt in POSTGRES_SCHEMA:
        cursor.execute(stmt)
    pg_conn.commit()

def get_db(db_path="typemeter.db"):
    """Connects to database: uses DATABASE_URL for Postgres connection pooling if set, or local SQLite fallback if unset."""
    db_url = os.environ.get("DATABASE_URL")
    if db_url:
        pool = get_pg_pool(db_url)
        pg_conn = None
        for _ in range(3):
            try:
                pg_conn = pool.getconn()
                cursor = pg_conn.cursor()
                cursor.execute("SELECT 1")
                cursor.close()
                break
            except Exception:
                if pg_conn:
                    try:
                        pool.putconn(pg_conn, close=True)
                    except Exception:
                        pass
                    pg_conn = None

        if pg_conn is None:
            pg_conn = pool.getconn()

        return PostgresConnectionWrapper(pg_conn, pool=pool)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    
    # Enable foreign keys and WAL mode for reliability
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    
    # Create tables
    conn.execute("""
        CREATE TABLE IF NOT EXISTS unigram_stats (
            identity_id TEXT,
            char TEXT,
            mistakes REAL,
            total REAL,
            last_updated TEXT,
            PRIMARY KEY (identity_id, char)
        )
    """)
    conn.execute("""
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
    conn.execute("""
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
    conn.execute("""
        CREATE TABLE IF NOT EXISTS global_priors (
            level TEXT,
            alpha REAL,
            beta REAL,
            fitted_at TEXT,
            sample_size INTEGER,
            PRIMARY KEY (level)
        )
    """)
    conn.execute("""
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
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT,
            auth_provider TEXT NOT NULL,
            google_id TEXT UNIQUE,
            email_verified BOOLEAN DEFAULT FALSE,
            display_name TEXT,
            failed_login_attempts INTEGER DEFAULT 0,
            lockout_until TEXT,
            created_at TEXT,
            updated_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS email_verification_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            token_hash TEXT UNIQUE NOT NULL,
            expires_at TEXT NOT NULL,
            used_at TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS password_reset_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            token_hash TEXT UNIQUE NOT NULL,
            expires_at TEXT NOT NULL,
            used_at TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ip_rate_limits (
            key TEXT NOT NULL,
            action TEXT NOT NULL,
            timestamp TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS typing_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            identity_id TEXT NOT NULL,
            user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            wpm REAL NOT NULL,
            raw_wpm REAL NOT NULL,
            accuracy REAL NOT NULL,
            mistakes_count INTEGER DEFAULT 0,
            total_chars INTEGER DEFAULT 0,
            time_seconds REAL DEFAULT 0.0,
            difficulty TEXT NOT NULL DEFAULT 'easy',
            created_at TEXT NOT NULL
        )
    """)
    
    # Create indexes
    conn.execute("CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_users_google_id ON users(google_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_email_tokens_hash ON email_verification_tokens(token_hash)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_reset_tokens_hash ON password_reset_tokens(token_hash)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rate_limits_key_timestamp ON ip_rate_limits(key, timestamp)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_typing_sessions_user_id ON typing_sessions(user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_typing_sessions_identity ON typing_sessions(identity_id)")
    
    conn.commit()
    return conn

# --- JS Word Database Loader ---
def parse_js_array(content, var_name):
    """Robust regex-based parsing of JavaScript arrays into Python lists."""
    pattern = rf"{var_name}\s*=\s*(\[.*?\])"
    match = re.search(pattern, content, re.DOTALL)
    if match:
        try:
            return ast.literal_eval(match.group(1))
        except Exception as e:
            print(f"[!] Error parsing array {var_name}: {e}")
    return []

def load_word_pools():
    """Loads all available raw word lists from front-end JS database files."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    google_words = []
    google_path = os.path.join(script_dir, "gui", "google-words.js")
    if os.path.exists(google_path):
        with open(google_path, "r", encoding="utf-8") as f:
            google_words = parse_js_array(f.read(), r"window\.googleWords")
            
    words_easy = []
    words_medium = []
    words_hard = []
    words_path = os.path.join(script_dir, "gui", "words.js")
    if os.path.exists(words_path):
        with open(words_path, "r", encoding="utf-8") as f:
            content = f.read()
            words_easy = parse_js_array(content, r"const\s+wordsDatabaseEasy")
            words_medium = parse_js_array(content, r"const\s+wordsDatabaseMedium")
            words_hard = parse_js_array(content, r"const\s+wordsDatabaseHard")
            
    return google_words, words_easy, words_medium, words_hard

def clean_pool(pool):
    """Filters out any duplicates and non-allowed short words from a pool."""
    seen = set()
    cleaned = []
    for w in pool:
        w_clean = w.strip().lower()
        if w_clean not in seen:
            seen.add(w_clean)
            if len(w_clean) >= 3 or w_clean in ALLOWED_SHORT:
                cleaned.append(w_clean)
    return cleaned

# --- Mathematical Rating Functions ---
def posterior_rate(mistakes, total, alpha, beta):
    """Posterior rate calculation blending empirical rate and prior expectations."""
    return (mistakes + alpha) / (total + alpha + beta)

def get_priors(conn):
    """Retrieves priors for unigram, bigram, and trigram levels."""
    priors = {
        "unigram": (FALLBACK_ALPHA, FALLBACK_BETA),
        "bigram": (FALLBACK_ALPHA, FALLBACK_BETA),
        "trigram": (FALLBACK_ALPHA, FALLBACK_BETA)
    }
    if USE_FITTED_PRIORS:
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT level, alpha, beta FROM global_priors")
            for row in cursor.fetchall():
                priors[row["level"]] = (row["alpha"], row["beta"])
        except Exception:
            pass
    return priors

def load_user_stats_cache(conn, identity_id):
    """Bulk loads all global priors and user n-gram stats into memory for O(1) batch word scoring."""
    priors = get_priors(conn)
    cursor = conn.cursor()
    
    unigrams = {}
    try:
        cursor.execute("SELECT char, mistakes, total FROM unigram_stats WHERE identity_id = ?", (identity_id,))
        for row in cursor.fetchall():
            unigrams[row["char"]] = (row["mistakes"], row["total"])
    except Exception:
        pass
        
    bigrams = {}
    try:
        cursor.execute("SELECT prev_char, char, mistakes, total FROM bigram_stats WHERE identity_id = ?", (identity_id,))
        for row in cursor.fetchall():
            bigrams[(row["prev_char"], row["char"])] = (row["mistakes"], row["total"])
    except Exception:
        pass

    trigrams = {}
    try:
        cursor.execute("SELECT prev2_chars, char, mistakes, total FROM trigram_stats WHERE identity_id = ?", (identity_id,))
        for row in cursor.fetchall():
            trigrams[(row["prev2_chars"], row["char"])] = (row["mistakes"], row["total"])
    except Exception:
        pass

    return {
        "priors": priors,
        "unigrams": unigrams,
        "bigrams": bigrams,
        "trigrams": trigrams
    }

def final_rate(conn, identity_id, prev2_chars, char, cache=None):
    """Calculates interpolated error rate for a character under a given context."""
    if cache is not None:
        priors = cache["priors"]
        levels_data = []
        
        # 1. Unigram
        u_data = cache["unigrams"].get(char)
        if u_data:
            alpha, beta = priors["unigram"]
            levels_data.append(("unigram", u_data[0], u_data[1], alpha, beta))
            
        # 2. Bigram
        if len(prev2_chars) >= 1:
            prev_char = prev2_chars[-1]
            b_data = cache["bigrams"].get((prev_char, char))
            if b_data:
                alpha, beta = priors["bigram"]
                levels_data.append(("bigram", b_data[0], b_data[1], alpha, beta))
                
        # 3. Trigram
        if len(prev2_chars) == 2:
            t_data = cache["trigrams"].get((prev2_chars, char))
            if t_data:
                alpha, beta = priors["trigram"]
                levels_data.append(("trigram", t_data[0], t_data[1], alpha, beta))
    else:
        priors = get_priors(conn)
        levels_data = []
        cursor = conn.cursor()
        
        # 1. Unigram
        cursor.execute("SELECT mistakes, total FROM unigram_stats WHERE identity_id = ? AND char = ?", (identity_id, char))
        row = cursor.fetchone()
        if row:
            alpha, beta = priors["unigram"]
            levels_data.append(("unigram", row["mistakes"], row["total"], alpha, beta))
            
        # 2. Bigram
        if len(prev2_chars) >= 1:
            prev_char = prev2_chars[-1]
            cursor.execute("SELECT mistakes, total FROM bigram_stats WHERE identity_id = ? AND prev_char = ? AND char = ?", (identity_id, prev_char, char))
            row = cursor.fetchone()
            if row:
                alpha, beta = priors["bigram"]
                levels_data.append(("bigram", row["mistakes"], row["total"], alpha, beta))
                
        # 3. Trigram
        if len(prev2_chars) == 2:
            cursor.execute("SELECT mistakes, total FROM trigram_stats WHERE identity_id = ? AND prev2_chars = ? AND char = ?", (identity_id, prev2_chars, char))
            row = cursor.fetchone()
            if row:
                alpha, beta = priors["trigram"]
                levels_data.append(("trigram", row["mistakes"], row["total"], alpha, beta))
            
    if not levels_data:
        alpha, beta = priors["unigram"]
        return alpha / (alpha + beta)
        
    lambdas = []
    posteriors = []
    for level, mistakes, total, alpha, beta in levels_data:
        lambdas.append(total / (total + INTERP_K))
        posteriors.append(posterior_rate(mistakes, total, alpha, beta))
        
    sum_lambdas = sum(lambdas)
    if sum_lambdas == 0:
        weights = [1.0 / len(lambdas)] * len(lambdas)
    else:
        weights = [l / sum_lambdas for l in lambdas]
        
    return sum(w * p for w, p in zip(weights, posteriors))

def word_score(conn, identity_id, word, cache=None):
    """Scores a word's difficulty as the mean n-gram error probability of its letters."""
    if not word:
        return 0.0
    total_rate = 0.0
    for i in range(len(word)):
        context = word[max(0, i - 2):i]
        char = word[i]
        total_rate += final_rate(conn, identity_id, context, char, cache=cache)
    return total_rate / len(word)

# --- Stats Ingestion Logic ---
def parse_dt(dt_str):
    """Helper to parse ISO datetime string."""
    try:
        return datetime.datetime.fromisoformat(dt_str)
    except Exception:
        try:
            return datetime.datetime.strptime(dt_str.split(".")[0], "%Y-%m-%dT%H:%M:%S")
        except Exception:
            return datetime.datetime.utcnow()

def ingest_mistakes(conn, identity_id, records):
    """Processes batch typed characters and updates corresponding n-gram counts with decay."""
    now = datetime.datetime.utcnow()
    now_str = now.isoformat()
    
    cursor = conn.cursor()
    for rec in records:
        expected_char = rec.get("expected_char")
        typed_char = rec.get("typed_char")
        is_correct = bool(rec.get("is_correct"))
        context_before = rec.get("context_before", "")
        word = rec.get("word", "")
        position_in_word = int(rec.get("position_in_word", 0))
        
        # 1. Update Unigram
        cursor.execute("SELECT mistakes, total, last_updated FROM unigram_stats WHERE identity_id = ? AND char = ?", (identity_id, expected_char))
        row = cursor.fetchone()
        if row:
            delta_days = (now - parse_dt(row["last_updated"])).total_seconds() / 86400.0
            decay = 0.5 ** (delta_days / HALF_LIFE_DAYS)
            total = row["total"] * decay + 1.0
            mistakes = row["mistakes"] * decay + (0.0 if is_correct else 1.0)
        else:
            total = 1.0
            mistakes = 0.0 if is_correct else 1.0
        cursor.execute("""
            INSERT INTO unigram_stats (identity_id, char, mistakes, total, last_updated)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(identity_id, char) DO UPDATE SET
                mistakes = excluded.mistakes,
                total = excluded.total,
                last_updated = excluded.last_updated
        """, (identity_id, expected_char, mistakes, total, now_str))
        
        # 2. Update Bigram
        if len(context_before) >= 1:
            prev_char = context_before[-1]
            cursor.execute("SELECT mistakes, total, last_updated FROM bigram_stats WHERE identity_id = ? AND prev_char = ? AND char = ?", (identity_id, prev_char, expected_char))
            row = cursor.fetchone()
            if row:
                delta_days = (now - parse_dt(row["last_updated"])).total_seconds() / 86400.0
                decay = 0.5 ** (delta_days / HALF_LIFE_DAYS)
                total = row["total"] * decay + 1.0
                mistakes = row["mistakes"] * decay + (0.0 if is_correct else 1.0)
            else:
                total = 1.0
                mistakes = 0.0 if is_correct else 1.0
            cursor.execute("""
                INSERT INTO bigram_stats (identity_id, prev_char, char, mistakes, total, last_updated)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(identity_id, prev_char, char) DO UPDATE SET
                    mistakes = excluded.mistakes,
                    total = excluded.total,
                    last_updated = excluded.last_updated
            """, (identity_id, prev_char, expected_char, mistakes, total, now_str))
            
        # 3. Update Trigram
        if len(context_before) == 2:
            cursor.execute("SELECT mistakes, total, last_updated FROM trigram_stats WHERE identity_id = ? AND prev2_chars = ? AND char = ?", (identity_id, context_before, expected_char))
            row = cursor.fetchone()
            if row:
                delta_days = (now - parse_dt(row["last_updated"])).total_seconds() / 86400.0
                decay = 0.5 ** (delta_days / HALF_LIFE_DAYS)
                total = row["total"] * decay + 1.0
                mistakes = row["mistakes"] * decay + (0.0 if is_correct else 1.0)
            else:
                total = 1.0
                mistakes = 0.0 if is_correct else 1.0
            cursor.execute("""
                INSERT INTO trigram_stats (identity_id, prev2_chars, char, mistakes, total, last_updated)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(identity_id, prev2_chars, char) DO UPDATE SET
                    mistakes = excluded.mistakes,
                    total = excluded.total,
                    last_updated = excluded.last_updated
            """, (identity_id, context_before, expected_char, mistakes, total, now_str))
            
        # 4. Insert into raw audit event log if mistake was made
        if not is_correct:
            cursor.execute("""
                INSERT INTO mistake_events (identity_id, context_before, expected_char, typed_char, word, position_in_word, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (identity_id, context_before, expected_char, typed_char, word, position_in_word, now_str))
            
    conn.commit()

# --- Word Selection Math ---
def softmax(scores, temperature):
    """Computes softmax probabilities with stable scale shifting."""
    scaled = [s / temperature for s in scores]
    max_s = max(scaled)
    exp_vals = [math.exp(s - max_s) for s in scaled]
    sum_exp = sum(exp_vals)
    return [e / sum_exp for e in exp_vals]

def weighted_sample_without_replacement(pool, probs, n_needed):
    """Draws unique samples from pool based on weighted probability values."""
    pool_copy = list(pool)
    probs_copy = list(probs)
    selected = []
    
    for _ in range(min(n_needed, len(pool))):
        sum_p = sum(probs_copy)
        if sum_p <= 0:
            idx = random.randrange(len(pool_copy))
        else:
            norm_probs = [p / sum_p for p in probs_copy]
            r = random.random()
            cum = 0.0
            idx = len(pool_copy) - 1
            for i, p in enumerate(norm_probs):
                cum += p
                if r <= cum:
                    idx = i
                    break
        selected.append(pool_copy[idx])
        pool_copy.pop(idx)
        probs_copy.pop(idx)
        
    return selected

def backend_select_words(conn, difficulty, count, identity_id):
    """Selects and shuffles a weighted sentence from pools based on mistake rates."""
    google_words, words_easy, words_medium, words_hard = load_word_pools()
    
    # Bulk-load user stats cache once for fast O(1) in-memory word scoring
    cache = load_user_stats_cache(conn, identity_id)
    
    # 1. Set up pools matching app.js divisions
    if google_words:
        easy_pool = clean_pool(google_words[:600])
        medium_pool = clean_pool(google_words[600:1400])
        hard_pool = clean_pool(google_words[1400:])
    else:
        # Fallback to local files
        easy_pool = clean_pool(words_easy)
        medium_pool = clean_pool(words_medium)
        hard_pool = clean_pool(words_hard)
        
    # 2. Allocate counts and select from pools
    sentence_list = []
    if difficulty == "easy":
        # Easy: strictly most common words
        scores = [word_score(conn, identity_id, w, cache=cache) for w in easy_pool]
        probs_soft = softmax(scores, SELECTION_TEMPERATURE)
        probs = [(1.0 - SELECTION_EPSILON) * p + SELECTION_EPSILON * (1.0 / len(easy_pool)) for p in probs_soft]
        sentence_list = weighted_sample_without_replacement(easy_pool, probs, count)
        
    elif difficulty == "medium":
        # Medium: 40% Easy words, 60% Medium words
        medium_count = int(round(count * 0.6))
        easy_count = count - medium_count
        
        # Easy selection
        scores_e = [word_score(conn, identity_id, w, cache=cache) for w in easy_pool]
        probs_e_soft = softmax(scores_e, SELECTION_TEMPERATURE)
        probs_e = [(1.0 - SELECTION_EPSILON) * p + SELECTION_EPSILON * (1.0 / len(easy_pool)) for p in probs_e_soft]
        selected_easy = weighted_sample_without_replacement(easy_pool, probs_e, easy_count)
        
        # Medium selection
        scores_m = [word_score(conn, identity_id, w, cache=cache) for w in medium_pool]
        probs_m_soft = softmax(scores_m, SELECTION_TEMPERATURE)
        probs_m = [(1.0 - SELECTION_EPSILON) * p + SELECTION_EPSILON * (1.0 / len(medium_pool)) for p in probs_m_soft]
        selected_medium = weighted_sample_without_replacement(medium_pool, probs_m, medium_count)
        
        sentence_list = selected_easy + selected_medium
        random.shuffle(sentence_list)
        
    else:
        # Hard: 60% Easy/Medium words, 40% Hard academic words
        hard_count = int(round(count * 0.4))
        easy_medium_count = count - hard_count
        
        # Combine pools
        easy_medium_pool = clean_pool(easy_pool + medium_pool)
        combined_hard_pool = clean_pool(hard_pool + words_hard)
        
        # Easy/Medium selection
        scores_em = [word_score(conn, identity_id, w, cache=cache) for w in easy_medium_pool]
        probs_em_soft = softmax(scores_em, SELECTION_TEMPERATURE)
        probs_em = [(1.0 - SELECTION_EPSILON) * p + SELECTION_EPSILON * (1.0 / len(easy_medium_pool)) for p in probs_em_soft]
        selected_em = weighted_sample_without_replacement(easy_medium_pool, probs_em, easy_medium_count)
        
        # Hard selection
        scores_h = [word_score(conn, identity_id, w, cache=cache) for w in combined_hard_pool]
        probs_h_soft = softmax(scores_h, SELECTION_TEMPERATURE)
        probs_h = [(1.0 - SELECTION_EPSILON) * p + SELECTION_EPSILON * (1.0 / len(combined_hard_pool)) for p in probs_h_soft]
        selected_h = weighted_sample_without_replacement(combined_hard_pool, probs_h, hard_count)
        
        sentence_list = selected_em + selected_h
        random.shuffle(sentence_list)
        
    return sentence_list


# --- Password and Security Helper Functions ---

def hash_password(password, cost=12):
    """Securely hashes a plaintext password using bcrypt and cost factor."""
    salt = bcrypt.gensalt(rounds=cost)
    return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')

def verify_password(password, password_hash):
    """Verifies a plaintext password matches its bcrypt hash."""
    if not password or not password_hash:
        return False
    try:
        return bcrypt.checkpw(password.encode('utf-8'), password_hash.encode('utf-8'))
    except Exception:
        return False

def hash_token(token):
    """Hashes a raw token with SHA-256 to prevent leakage in case of database dumps."""
    return hashlib.sha256(token.encode('utf-8')).hexdigest()

def _extract_count(row, key="cnt"):
    """Safely extracts an aggregate count value from a database row (dict, sqlite3.Row, or tuple)."""
    if not row:
        return 0
    if isinstance(row, dict):
        if key in row:
            return row[key]
        vals = list(row.values())
        return vals[0] if vals else 0
    if hasattr(row, "keys"):
        try:
            keys = row.keys()
            if key in keys:
                return row[key]
        except Exception:
            pass
    try:
        return row[0]
    except (TypeError, KeyError, IndexError):
        if hasattr(row, "values"):
            vals = list(row.values())
            return vals[0] if vals else 0
        return 0

def check_rate_limit(conn, key, action, limit, window_seconds):
    """
    Lightweight, persistent database-backed rate limiter.
    Returns True if allowed, False if blocked.
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    cutoff = (now - datetime.timedelta(seconds=window_seconds)).isoformat()
    cursor = conn.cursor()
    
    # Delete expired rate-limit entries
    cursor.execute("DELETE FROM ip_rate_limits WHERE timestamp < ?", (cutoff,))
    
    # Count requests
    cursor.execute(
        "SELECT COUNT(*) AS cnt FROM ip_rate_limits WHERE key = ? AND action = ? AND timestamp >= ?",
        (key, action, cutoff)
    )
    count_row = cursor.fetchone()
    count = _extract_count(count_row, "cnt")
    
    if count >= limit:
        return False
        
    # Ingest current request timestamp
    cursor.execute(
        "INSERT INTO ip_rate_limits (key, action, timestamp) VALUES (?, ?, ?)",
        (key, action, now.isoformat())
    )
    conn.commit()
    return True

def send_email(to_email, subject, body):
    """
    Sends an email using configured SMTP settings, or fallback to logging in non-production.
    Loads host/port/credentials dynamically.
    """
    host = os.environ.get("SMTP_HOST")
    port_str = os.environ.get("SMTP_PORT", "587")
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASS")
    sender = os.environ.get("SMTP_FROM", "noreply@typemeter.local")
    is_prod = (os.environ.get("ENV") == "production")
    
    if not host or not user or not password:
        if is_prod:
            import logging
            logging.getLogger("typemeter").error(f"SMTP is not configured in production mode. Cannot deliver email '{subject}' to {to_email}.")
            return False
        else:
            print(f"\n==================================================")
            print(f"📧 EMAIL SENT TO: {to_email}")
            print(f"Subject: {subject}")
            print(f"Content:\n{body}")
            print(f"==================================================\n")
            return True
            
    try:
        port = int(port_str)
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = sender
        msg["To"] = to_email
        
        with smtplib.SMTP(host, port) as server:
            server.starttls()
            server.login(user, password)
            server.sendmail(sender, [to_email], msg.as_string())
        return True
    except Exception as e:
        import logging
        logging.getLogger("typemeter").error(f"SMTP email delivery failed to {to_email}: {e}")
        return False

# --- Session Manager Helpers ---

def create_session(conn, user_id):
    """Creates a new session for a user, enforcing session fixation protection."""
    session_id = secrets.token_urlsafe(32)
    now = datetime.datetime.now(datetime.timezone.utc)
    # Absolute expiry is 30 days
    expires_at = (now + datetime.timedelta(days=30)).isoformat()
    
    conn.execute(
        "INSERT INTO sessions (session_id, user_id, created_at, last_seen_at, expires_at) VALUES (?, ?, ?, ?, ?)",
        (session_id, user_id, now.isoformat(), now.isoformat(), expires_at)
    )
    conn.commit()
    return session_id

def get_session(conn, session_id):
    """
    Retrieves the session from database, enforcing idle (7d) and absolute (30d) timeouts.
    Returns session dict/Row if valid, otherwise None.
    """
    if not session_id:
        return None
        
    row = conn.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
    if not row:
        return None
        
    now = datetime.datetime.now(datetime.timezone.utc)
    
    # Check absolute expiry (30 days)
    expires_at = datetime.datetime.fromisoformat(row["expires_at"])
    if now.timestamp() > expires_at.timestamp():
        delete_session(conn, session_id)
        return None
        
    # Check idle timeout (7 days)
    last_seen_at = datetime.datetime.fromisoformat(row["last_seen_at"])
    if now.timestamp() - last_seen_at.timestamp() > 7 * 24 * 3600:
        delete_session(conn, session_id)
        return None
        
    return row

def touch_session(conn, session_id):
    """Touches session to update last_seen_at, throttled to once per 5 minutes."""
    if not session_id:
        return
        
    row = conn.execute("SELECT last_seen_at FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
    if not row:
        return
        
    now = datetime.datetime.now(datetime.timezone.utc)
    last_seen = datetime.datetime.fromisoformat(row["last_seen_at"])
    
    # Only touch if older than 5 minutes to limit DB writes
    if now.timestamp() - last_seen.timestamp() > 300:
        conn.execute(
            "UPDATE sessions SET last_seen_at = ? WHERE session_id = ?",
            (now.isoformat(), session_id)
        )
        conn.commit()

def delete_session(conn, session_id):
    """Permanently invalidates and deletes a session."""
    if session_id:
        conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
        conn.commit()

def invalidate_user_sessions(conn, user_id, keep_session_id=None):
    """Invalidates all sessions for a user (e.g. on password reset/change)."""
    if keep_session_id:
        conn.execute("DELETE FROM sessions WHERE user_id = ? AND session_id != ?", (user_id, keep_session_id))
    else:
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
    conn.commit()

def cleanup_sessions(conn):
    """Periodically sweeps expired session rows."""
    now = datetime.datetime.now(datetime.timezone.utc)
    # Delete absolute expired sessions
    conn.execute("DELETE FROM sessions WHERE expires_at < ?", (now.isoformat(),))
    # Delete idle expired sessions (older than 7 days)
    idle_cutoff = (now - datetime.timedelta(days=7)).isoformat()
    conn.execute("DELETE FROM sessions WHERE last_seen_at < ?", (idle_cutoff,))
    conn.commit()

# --- Session History & Anonymous Migration Helpers ---

def save_typing_session(conn, identity_id, user_id, data):
    """Saves a completed typing session record after validating numeric inputs and ranges."""
    try:
        wpm = float(data.get("wpm", 0.0))
        raw_wpm = float(data.get("raw_wpm", 0.0))
        accuracy = float(data.get("accuracy", 0.0))
        mistakes_count = int(data.get("mistakes_count", 0))
        total_chars = int(data.get("total_chars", 0))
        time_seconds = float(data.get("time_seconds", 0.0))
    except (ValueError, TypeError):
        raise ValueError("Invalid numeric data type in session metrics.")

    difficulty = str(data.get("difficulty", "easy")).strip().lower()
    if difficulty not in ("easy", "medium", "hard"):
        difficulty = "easy"

    if not (0.0 <= wpm <= 500.0 and 0.0 <= raw_wpm <= 500.0 and 0.0 <= accuracy <= 100.0 and time_seconds >= 0.0 and mistakes_count >= 0 and total_chars >= 0):
        raise ValueError("Session metrics out of allowed physical range.")

    created_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO typing_sessions (identity_id, user_id, wpm, raw_wpm, accuracy, mistakes_count, total_chars, time_seconds, difficulty, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (identity_id, user_id, wpm, raw_wpm, accuracy, mistakes_count, total_chars, time_seconds, difficulty, created_at))
    conn.commit()
    return cursor.lastrowid

def get_user_history(conn, user_id, limit=50, offset=0):
    """Retrieves paginated typing session history for a logged-in user."""
    cursor = conn.cursor()
    count_row = cursor.execute("SELECT COUNT(*) AS cnt FROM typing_sessions WHERE user_id = ?", (user_id,)).fetchone()
    total_count = _extract_count(count_row, "cnt")
    
    rows = cursor.execute("""
        SELECT id, wpm, raw_wpm, accuracy, mistakes_count, total_chars, time_seconds, difficulty, created_at
        FROM typing_sessions
        WHERE user_id = ?
        ORDER BY created_at DESC
        LIMIT ? OFFSET ?
    """, (user_id, limit, offset)).fetchall()
    
    sessions = [dict(row) for row in rows]
    return sessions, total_count

def calculate_user_streak(conn, user_id):
    """Calculates the maximum consecutive days with at least one completed typing session."""
    cursor = conn.cursor()
    rows = cursor.execute("""
        SELECT DISTINCT substr(created_at, 1, 10) as session_date
        FROM typing_sessions
        WHERE user_id = ?
        ORDER BY session_date ASC
    """, (user_id,)).fetchall()
    
    if not rows:
        return 0
        
    dates = []
    for r in rows:
        try:
            d = datetime.datetime.strptime(r["session_date"], "%Y-%m-%d").date()
            dates.append(d)
        except Exception:
            continue
            
    if not dates:
        return 0
        
    max_streak = 1
    current_streak = 1
    for i in range(1, len(dates)):
        if (dates[i] - dates[i-1]).days == 1:
            current_streak += 1
            if current_streak > max_streak:
                max_streak = current_streak
        elif (dates[i] - dates[i-1]).days > 1:
            current_streak = 1
            
    return max_streak

def get_user_records(conn, user_id):
    """Computes personal bests, overall statistics, longest streak, and trend records for a logged-in user."""
    cursor = conn.cursor()
    
    stats_row = cursor.execute("""
        SELECT 
            MAX(wpm) as peak_wpm,
            MAX(accuracy) as peak_accuracy,
            COUNT(*) as total_sessions,
            SUM(time_seconds) as total_time_seconds,
            AVG(wpm) as avg_wpm,
            AVG(accuracy) as avg_accuracy,
            SUM(total_chars) as total_chars,
            SUM(mistakes_count) as total_mistakes
        FROM typing_sessions
        WHERE user_id = ?
    """, (user_id,)).fetchone()
    
    trend_rows = cursor.execute("""
        SELECT id, wpm, raw_wpm, accuracy, created_at
        FROM typing_sessions
        WHERE user_id = ?
        ORDER BY created_at DESC
        LIMIT 30
    """, (user_id,)).fetchall()
    
    trends = [dict(r) for r in reversed(trend_rows)]
    streak = calculate_user_streak(conn, user_id)
    
    if not stats_row or not stats_row["total_sessions"]:
        return {
            "peak_wpm": 0.0,
            "peak_accuracy": 0.0,
            "longest_streak": 0,
            "total_sessions": 0,
            "total_time_seconds": 0.0,
            "avg_wpm": 0.0,
            "avg_accuracy": 0.0,
            "total_chars": 0,
            "total_mistakes": 0,
            "trends": []
        }
        
    return {
        "peak_wpm": round(stats_row["peak_wpm"] or 0.0, 1),
        "peak_accuracy": round(stats_row["peak_accuracy"] or 0.0, 1),
        "longest_streak": streak,
        "total_sessions": stats_row["total_sessions"] or 0,
        "total_time_seconds": round(stats_row["total_time_seconds"] or 0.0, 1),
        "avg_wpm": round(stats_row["avg_wpm"] or 0.0, 1),
        "avg_accuracy": round(stats_row["avg_accuracy"] or 0.0, 1),
        "total_chars": stats_row["total_chars"] or 0,
        "total_mistakes": stats_row["total_mistakes"] or 0,
        "trends": trends
    }

def migrate_anonymous_data(conn, anon_identity_id, user_id):
    """
    Attaches any existing anonymous session history and merges n-gram mistake stats 
    from an anonymous identity_id cookie to a newly authenticated user account.
    """
    if not anon_identity_id or not user_id:
        return
        
    target_identity_id = str(user_id)
    if anon_identity_id == target_identity_id:
        return
        
    cursor = conn.cursor()
    
    # 1. Update typing_sessions
    cursor.execute("""
        UPDATE typing_sessions 
        SET user_id = ?, identity_id = ? 
        WHERE identity_id = ?
    """, (user_id, target_identity_id, anon_identity_id))
    
    # 2. Update mistake_events
    cursor.execute("""
        UPDATE mistake_events 
        SET identity_id = ? 
        WHERE identity_id = ?
    """, (target_identity_id, anon_identity_id))
    
    # 3. Merge unigram_stats
    rows = cursor.execute("SELECT char, mistakes, total, last_updated FROM unigram_stats WHERE identity_id = ?", (anon_identity_id,)).fetchall()
    for r in rows:
        cursor.execute("""
            INSERT INTO unigram_stats (identity_id, char, mistakes, total, last_updated)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(identity_id, char) DO UPDATE SET
                mistakes = unigram_stats.mistakes + excluded.mistakes,
                total = unigram_stats.total + excluded.total,
                last_updated = CASE WHEN excluded.last_updated > unigram_stats.last_updated THEN excluded.last_updated ELSE unigram_stats.last_updated END
        """, (target_identity_id, r["char"], r["mistakes"], r["total"], r["last_updated"]))
    cursor.execute("DELETE FROM unigram_stats WHERE identity_id = ?", (anon_identity_id,))
    
    # 4. Merge bigram_stats
    rows = cursor.execute("SELECT prev_char, char, mistakes, total, last_updated FROM bigram_stats WHERE identity_id = ?", (anon_identity_id,)).fetchall()
    for r in rows:
        cursor.execute("""
            INSERT INTO bigram_stats (identity_id, prev_char, char, mistakes, total, last_updated)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(identity_id, prev_char, char) DO UPDATE SET
                mistakes = bigram_stats.mistakes + excluded.mistakes,
                total = bigram_stats.total + excluded.total,
                last_updated = CASE WHEN excluded.last_updated > bigram_stats.last_updated THEN excluded.last_updated ELSE bigram_stats.last_updated END
        """, (target_identity_id, r["prev_char"], r["char"], r["mistakes"], r["total"], r["last_updated"]))
    cursor.execute("DELETE FROM bigram_stats WHERE identity_id = ?", (anon_identity_id,))
    
    # 5. Merge trigram_stats
    rows = cursor.execute("SELECT prev2_chars, char, mistakes, total, last_updated FROM trigram_stats WHERE identity_id = ?", (anon_identity_id,)).fetchall()
    for r in rows:
        cursor.execute("""
            INSERT INTO trigram_stats (identity_id, prev2_chars, char, mistakes, total, last_updated)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(identity_id, prev2_chars, char) DO UPDATE SET
                mistakes = trigram_stats.mistakes + excluded.mistakes,
                total = trigram_stats.total + excluded.total,
                last_updated = CASE WHEN excluded.last_updated > trigram_stats.last_updated THEN excluded.last_updated ELSE trigram_stats.last_updated END
        """, (target_identity_id, r["prev2_chars"], r["char"], r["mistakes"], r["total"], r["last_updated"]))
    cursor.execute("DELETE FROM trigram_stats WHERE identity_id = ?", (anon_identity_id,))
    
    conn.commit()

