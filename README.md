# TypeMeter 🚀

A modern typing speed trainer featuring a local Web GUI and an interactive terminal CLI. TypeMeter tracks typing speed (WPM, Raw WPM), accuracy, and mistakes, and utilizes an **adaptive, mistake-weighted n-gram machine learning model** to customize practice tests based on your typing errors.

---

## Core Capabilities 🌟

### 💻 Web GUI & Practice Arena
- **Dynamic Scrolling**: Visually constrained to a 3-line typing viewport; completed lines automatically scroll upward to lock active focus to the second visual line.
- **Neon Caret**: Floating cursor styled with an active neon glow. Pauses blinking during typing and resumes blinking when paused.
- **WPM Metric (5-Char Standard)**: Speed and Raw speed are calculated using the industry standard (5 characters typed = 1 word) for consistent real-time measurement.
- **Monkeytype Input Flow**: Advancing to the next word is strictly constrained to the Spacebar.
- **User Authentication & Personal History**: Account signup/login, session history tracking, personal bests, consecutive streak days counter, and security controls.

### 🧠 Adaptive N-Gram Selection Model (Machine Learning)
TypeMeter estimates your typing mistake patterns using a statistical NLP model:
- **N-Gram Modeling**: Captures character error sequences (Unigrams, Bigrams, Trigrams) stored in SQLite or PostgreSQL.
- **Bayesian Prior Smoothing**: Prevents volatile rates on low data by shrinking error rates toward a prior distribution ($\alpha = 2.0, \beta = 18.0$).
- **Linear Interpolation**: Resolves data sparsity using backoff coefficients to interpolate scores across Trigram $\rightarrow$ Bigram $\rightarrow$ Unigram.
- **Softmax Selection & Exploration**: Scores words based on error probabilities and selects them using a temperature-scaled softmax function ($T = 0.2$) mixed with an exploration factor ($\epsilon = 0.3$) for variety.
- **Exponential Time Decay**: Mistake counts are decayed exponentially ($t_{1/2} = 14 \text{ days}$) so that recent mistakes are practiced more than historical errors.

---

## Database Architecture & Configuration 🗄️

TypeMeter supports both local development and cloud production databases:

1. **Local SQLite Mode (Default for Development)**:
   - If `DATABASE_URL` is not set, TypeMeter seamlessly uses local SQLite (`typemeter.db`).

2. **Cloud PostgreSQL Mode (Production Ready)**:
   - Provide `DATABASE_URL` in `.env` or system environment:
     ```env
     DATABASE_URL=postgresql://user:password@host:5432/dbname
     ```
   - Uses `psycopg2` connection pooling (`ThreadedConnectionPool`) for high-throughput WSGI servers (Waitress/Gunicorn).

3. **One-Time Data Migration (SQLite $\rightarrow$ Postgres)**:
   - To migrate existing accounts and typing history from local SQLite to cloud PostgreSQL:
     ```bash
     DATABASE_URL=postgresql://user:pass@host:5432/dbname python3 migrate_to_postgres.py
     ```

---

## Installation & Running 🛠️

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Running the Server
Run the application server:
```bash
python3 run_gui.py
```
This serves the application on `http://127.0.0.1:8000/index.html` and opens your default browser.

### 3. Running Health Check
TypeMeter includes a platform readiness endpoint:
```bash
curl http://127.0.0.1:8000/healthz
```

### 4. Running the Test Suite
To execute the automated unit and integration test suite:
```bash
python3 -m unittest test_typemeter.py
```

---

## Technical References & Built-With 📚

- **Google 10,000 Common English Words**: Vocabulary frequency ranking derived from [first20hours/google-10000-english](https://github.com/first20hours/google-10000-english).
- **`random-words` Dictionary**: Base vocabulary of 1,952 English words extracted from npm [`random-words`](https://www.npmjs.com/package/random-words).
- **Jelinek-Mercer Interpolation**: Linear interpolation backoff model for n-gram language smoothing.
- **PostgreSQL & SQLite**: Dual database connection pooling architecture.

---

## License 📄
This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.