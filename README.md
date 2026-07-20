# TypeMeter 🚀

A modern typing speed trainer featuring a local Web GUI and an interactive terminal CLI. TypeMeter tracks typing speed (WPM, Raw WPM), accuracy, and mistakes, and utilizes an **adaptive, mistake-weighted n-gram machine learning model** to customize practice tests based on your typing errors.

---

## Core Capabilities 🌟

### 💻 Local Web GUI
- **Dynamic Scrolling**: Visually constrained to a 3-line typing viewport; completed lines automatically scroll upward to lock active focus to the second visual line.
- **Neon Caret**: A 3px floating cursor styled with an active neon glow. It pauses blinking (remains solid) during typing and resumes blinking when you pause.
- **WPM Metric (5-Char Standard)**: Speed and Raw speed are calculated using the industry standard (5 characters typed = 1 word) for consistent real-time measurement.
- **Monkeytype Input Flow**:
  - Advancing to the next word is strictly constrained to the **Spacebar**.
  - Letters typed past a word's length are appended as red underlined characters and push remaining text forward.
  - Correcting the last letter of the test terminates it immediately; typing it incorrectly allows backspacing to fix it, terminating only on space.

### 🧠 Adaptive N-Gram Selection Model (Machine Learning)
TypeMeter estimates your typing mistake patterns using a statistical NLP model running locally:
- **N-Gram Modeling**: Captures character error sequences (Unigrams, Bigrams, Trigrams) and stores them in a local SQLite database.
- **Bayesian Prior Smoothing**: Prevents volatile rates on low data by shrinking error rates toward a prior distribution ($\alpha = 2.0, \beta = 18.0$).
- **Linear Interpolation**: Resolves data sparsity using backoff coefficients to interpolate scores across Trigram $\rightarrow$ Bigram $\rightarrow$ Unigram.
- **Softmax Selection & Exploration**: Scores words based on error probabilities and selects them using a temperature-scaled softmax function ($T = 0.2$) mixed with an exploration factor ($\epsilon = 0.3$) for variety.
- **Exponential Time Decay**: Mistake counts are decayed exponentially ($t_{1/2} = 14 \text{ days}$) so that recent mistakes are practiced more than historical errors.
- **Prior-Fitting Job**: An offline Method-of-Moments estimator calculates population-wide prior parameters ($\alpha, \beta$) dynamically.

---

## Installation & Running 🛠️

### 1. Running the Local Web GUI
The GUI is self-contained and runs on standard Python libraries. No external packages are required to serve the app.

Run the launcher script:
```bash
python3 run_gui.py
```
This serves the application on `http://127.0.0.1:8000/index.html` and launches your default browser. An anonymous session tracking cookie (`identity_id`) will automatically be issued to persist your stats across restarts.

### 2. Prior-Fitting Job
To update the global population priors from accumulated database statistics, run the prior-fitting job:
```bash
python3 fit_priors.py
```

### 3. Running the Test Suite
To execute the automated unit and integration test suite:
```bash
python3 -m unittest test_typemeter.py
```

### 4. Running the Terminal CLI
The terminal CLI requires the `keyboard` package.
```bash
pip install -r requirements.txt
sudo python3 typemeter.py
```
*(Note: Terminal global keyboard monitoring on Linux requires execution with root privileges (`sudo`).)*

---

## Technical References & Built-With 📚

The following datasets, algorithms, and modules were used in this project:

- **Google 10,000 Common English Words**: Vocabulary frequency ranking is derived from the [first20hours/google-10000-english](https://github.com/first20hours/google-10000-english) dataset.
- **`random-words` Dictionary**: Base vocabulary of 1,952 high-quality English words is extracted from the npm [`random-words`](https://www.npmjs.com/package/random-words) library.
- **Jelinek-Mercer Interpolation**: Linear interpolation backoff model for n-gram language smoothing.
- **Softmax Policy & Epsilon-Greedy Exploration**: Action selection policies commonly used in Reinforcement Learning models to balance exploitation (practicing mistakes) with exploration.
- **Method of Moments**: Statistical parameter estimation technique used to fit Beta distribution priors ($\alpha, \beta$).
- **SQLite**: Local database storage using Python's built-in `sqlite3` module with Write-Ahead Logging (WAL) enabled.

---

## File Structure 📂

```
typemeter/
├── typemeter_db.py     # SQLite schema, n-gram, and word selection logic
├── run_gui.py          # HTTP API server & static GUI server launcher
├── fit_priors.py       # Method-of-Moments prior estimation script
├── test_typemeter.py   # Test suite (Unit & Integration tests)
├── typemeter.py        # Interactive Terminal CLI program
├── README.md           # Documentation
├── LICENSE             # MIT License
└── gui/                # Static frontend assets
    ├── index.html      # Typing arena interface
    ├── style.css       # Custom styles, caret glow, and dark/light themes
    ├── app.js          # Caret scrolling, keyboard listeners, & API interactions
    ├── google-words.js # Clean sorted word list
    ├── words.js        # fallback offline word arrays
    └── random-words.min.js
```

---

## License 📄
This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.