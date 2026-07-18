# TypeMeter 🚀

A modern, local, and terminal-friendly typing speed and accuracy testing utility. **TypeMeter** helps you measure your words per minute (WPM), raw WPM, accuracy percentage, time taken, and total mistakes.

It comes with a fully-functional interactive CLI utility and a visually stunning **Local Web GUI** (inspired by Monkeytype) that runs offline without any external installations.

---

## Features ✨

### 💻 Local Web GUI
- **Visual Feedback**: Real-time coloring of typed text (green for correct, red/background highlighting for errors).
- **Responsive Caret**: Fluid floating caret that flows letter by letter.
- **Deduplicated Custom Tests**: Generate sentences with 10, 25, 50, 100, or custom word limits.
- **Ported Difficulty Databases**: Same Easy, Medium, and Hard word lists ported directly from the Python core.
- **Glassmorphism Design**: Futuristic, neon-glow dark mode with standard theme switching options.
- **Performance Dashboard**: Interactive cards displaying final calculated results (WPM, Raw WPM, Accuracy, Time, and Mistakes count).
- **Fast Reset**: Instant restart helper by clicking the restart button or pressing `Tab` + `Enter`.
- **Zero-Dependency**: Starts a lightweight HTTP server using Python's built-in libraries.

### 📟 Terminal CLI
- Fast, low-footprint typing speed analysis in your terminal.
- Support for Easy, Medium, and Hard words.
- Keystroke-triggered start timers.

---

## Installation & Running 🛠️

### 1. Running the Local GUI (Recommended)

The Web GUI is self-contained and does not require installing any third-party packages or system dependencies.

#### Run with Python (Starts local server)
Run the launcher script in the root directory:
```bash
python3 run_gui.py
```
This will automatically launch the typing app in your default web browser (usually at `http://127.0.0.1:8000/index.html`).

#### Run directly
Alternatively, you can double-click and open the HTML page directly in any browser:
```
typemeter/gui/index.html
```

---

### 2. Running the Terminal CLI

The CLI uses the Python `keyboard` module to monitor keystrokes. 

#### Setup dependencies
```bash
pip install -r requirements.txt
```
*(Note: You will need to install the `keyboard` package)*

#### Run CLI
Run the main script:
```bash
python3 typemeter.py
```
*Note for Linux users: Because the CLI uses global keyboard hook listeners to detect when you start typing, it might require execution with root privileges (`sudo python3 typemeter.py`). To avoid root requirements, we recommend using the Web GUI.*

---

## File Structure 📂

```
typemeter/
├── README.md          # Documentation
├── LICENSE            # License information
├── typemeter.py       # Core Python CLI application
├── run_gui.py         # Local GUI python server launcher
└── gui/               # Web GUI folder
    ├── index.html     # GUI Interface Markup
    ├── style.css      # Custom styling & themes
    ├── words.js       # Ported word lists
    └── app.js         # GUI execution and performance logic
```

---

## License 📄
This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.