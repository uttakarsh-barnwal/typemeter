import sqlite3
import os
import re
import ast
import math
import random
import datetime

# --- Configuration Constants ---
HALF_LIFE_DAYS = 14.0
INTERP_K = 10.0
SELECTION_TEMPERATURE = 0.2
SELECTION_EPSILON = 0.3
FALLBACK_ALPHA = 2.0
FALLBACK_BETA = 18.0
USE_FITTED_PRIORS = False

ALLOWED_SHORT = {"a", "i", "of", "to", "in", "it", "is", "on", "by", "or", "be", "at", "as", "an", "we", "us", "if", "my", "do", "no", "he", "up", "so", "am", "me", "go"}

# --- SQLite Setup ---
def get_db(db_path="typemeter.db"):
    """Connects to the database and initializes tables if they do not exist."""
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

def final_rate(conn, identity_id, prev2_chars, char):
    """Calculates interpolated error rate for a character under a given context."""
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

def word_score(conn, identity_id, word):
    """Scores a word's difficulty as the mean n-gram error probability of its letters."""
    if not word:
        return 0.0
    total_rate = 0.0
    for i in range(len(word)):
        context = word[max(0, i - 2):i]
        char = word[i]
        total_rate += final_rate(conn, identity_id, context, char)
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
        scores = [word_score(conn, identity_id, w) for w in easy_pool]
        probs_soft = softmax(scores, SELECTION_TEMPERATURE)
        probs = [(1.0 - SELECTION_EPSILON) * p + SELECTION_EPSILON * (1.0 / len(easy_pool)) for p in probs_soft]
        sentence_list = weighted_sample_without_replacement(easy_pool, probs, count)
        
    elif difficulty == "medium":
        # Medium: 40% Easy words, 60% Medium words
        medium_count = int(round(count * 0.6))
        easy_count = count - medium_count
        
        # Easy selection
        scores_e = [word_score(conn, identity_id, w) for w in easy_pool]
        probs_e_soft = softmax(scores_e, SELECTION_TEMPERATURE)
        probs_e = [(1.0 - SELECTION_EPSILON) * p + SELECTION_EPSILON * (1.0 / len(easy_pool)) for p in probs_e_soft]
        selected_easy = weighted_sample_without_replacement(easy_pool, probs_e, easy_count)
        
        # Medium selection
        scores_m = [word_score(conn, identity_id, w) for w in medium_pool]
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
        scores_em = [word_score(conn, identity_id, w) for w in easy_medium_pool]
        probs_em_soft = softmax(scores_em, SELECTION_TEMPERATURE)
        probs_em = [(1.0 - SELECTION_EPSILON) * p + SELECTION_EPSILON * (1.0 / len(easy_medium_pool)) for p in probs_em_soft]
        selected_em = weighted_sample_without_replacement(easy_medium_pool, probs_em, easy_medium_count)
        
        # Hard selection
        scores_h = [word_score(conn, identity_id, w) for w in combined_hard_pool]
        probs_h_soft = softmax(scores_h, SELECTION_TEMPERATURE)
        probs_h = [(1.0 - SELECTION_EPSILON) * p + SELECTION_EPSILON * (1.0 / len(combined_hard_pool)) for p in probs_h_soft]
        selected_h = weighted_sample_without_replacement(combined_hard_pool, probs_h, hard_count)
        
        sentence_list = selected_em + selected_h
        random.shuffle(sentence_list)
        
    return sentence_list
