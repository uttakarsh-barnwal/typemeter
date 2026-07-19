// State Variables
let targetWords = [];
let typedWords = [];
let activeWordIndex = 0;
let startTime = null;
let endTime = null;
let isTesting = false;
let currentDifficulty = "easy";
let wordCountMode = "25";
let customWordCount = 25;
let caretTimeout = null;

// Elements
const wordsContainer = document.getElementById("words-container");
const hiddenInput = document.getElementById("hidden-input");
const arena = document.getElementById("arena");
const focusPrompt = document.getElementById("focus-prompt");
const btnRestart = document.getElementById("btn-restart");
const resultsPanel = document.getElementById("results-panel");
const themeToggle = document.getElementById("theme-toggle");

// Settings Elements
const difficultyOptions = document.getElementById("difficulty-options");
const wordCountOptions = document.getElementById("word-count-options");
const customWordsInput = document.getElementById("custom-words");

// Stats Elements
const resWpm = document.getElementById("res-wpm");
const resAccuracy = document.getElementById("res-accuracy");
const resRawWpm = document.getElementById("res-raw-wpm");
const resTime = document.getElementById("res-time");
const resMistakes = document.getElementById("res-mistakes");

// Init application
document.addEventListener("DOMContentLoaded", () => {
    // Set default github link if needed
    const gitLink = document.getElementById("github-link");
    if (gitLink && gitLink.getAttribute("href") === "https://github.") {
        gitLink.setAttribute("href", window.location.href);
    }

    // Set Theme
    const savedTheme = localStorage.getItem("typemeter-theme") || "dark";
    document.body.setAttribute("data-theme", savedTheme);
    updateThemeIcon(savedTheme);

    // Event Listeners
    themeToggle.addEventListener("click", toggleTheme);
    btnRestart.addEventListener("click", () => resetTest());
    
    // Arena Focus handling
    arena.addEventListener("click", focusInput);
    focusPrompt.addEventListener("click", focusInput);
    
    hiddenInput.addEventListener("blur", () => {
        focusPrompt.classList.add("active");
    });
    
    hiddenInput.addEventListener("focus", () => {
        focusPrompt.classList.remove("active");
    });

    // Listen to settings changes
    difficultyOptions.addEventListener("click", (e) => {
        if (e.target.classList.contains("option-btn")) {
            setSelectedOption(difficultyOptions, e.target);
            currentDifficulty = e.target.dataset.val;
            resetTest();
        }
    });

    wordCountOptions.addEventListener("click", (e) => {
        if (e.target.classList.contains("option-btn")) {
            setSelectedOption(wordCountOptions, e.target);
            wordCountMode = e.target.dataset.val;
            if (wordCountMode === "custom") {
                customWordsInput.style.display = "inline-block";
                customWordsInput.focus();
            } else {
                customWordsInput.style.display = "none";
                resetTest();
            }
        }
    });

    customWordsInput.addEventListener("change", () => {
        let val = parseInt(customWordsInput.value);
        if (isNaN(val) || val < 1) val = 1;
        if (val > 500) val = 500;
        customWordsInput.value = val;
        customWordCount = val;
        resetTest();
    });

    // Keyboard controls
    hiddenInput.addEventListener("input", handleInput);
    hiddenInput.addEventListener("keydown", handleKeydown);
    
    // Global shortcut for Restart (Tab + Enter)
    document.addEventListener("keydown", (e) => {
        // Tab + Enter shortcut
        if (e.key === "Tab") {
            e.preventDefault();
            btnRestart.focus();
        }
    });

    // Initial setup
    resetTest();
});

// Helper for UI option buttons
function setSelectedOption(container, selectedBtn) {
    container.querySelectorAll(".option-btn").forEach(btn => {
        btn.classList.remove("active");
    });
    selectedBtn.classList.add("active");
}

// Theme handling
function toggleTheme() {
    const currentTheme = document.body.getAttribute("data-theme");
    const newTheme = currentTheme === "light" ? "dark" : "light";
    document.body.setAttribute("data-theme", newTheme);
    localStorage.setItem("typemeter-theme", newTheme);
    updateThemeIcon(newTheme);
}

function updateThemeIcon(theme) {
    const icon = themeToggle.querySelector("i");
    if (theme === "light") {
        icon.className = "fa-solid fa-sun";
    } else {
        icon.className = "fa-solid fa-moon";
    }
}

// Focus the hidden input to start capturing keystrokes
function focusInput() {
    hiddenInput.focus();
}

// Helper for mixing words randomly (Fisher-Yates Shuffle)
function shuffleArray(array) {
    for (let i = array.length - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1));
        [array[i], array[j]] = [array[j], array[i]];
    }
    return array;
}

// Ported sentence generator from typemeter.py
function generateSentence() {
    // Determine target word count
    let count = wordCountMode === "custom" ? customWordCount : parseInt(wordCountMode);
    if (isNaN(count) || count < 1) count = 25;

    // Check if the Google common words database is available in the window scope
    if (window.googleWords && Array.isArray(window.googleWords)) {
        try {
            const easyPool = window.googleWords.slice(0, 600);       // Top 600 most common words
            const mediumPool = window.googleWords.slice(600, 1400);   // Ranks 600 - 1400
            const hardPool = window.googleWords.slice(1400);          // Ranks 1400 - 1952 (less common)

            let sentenceList = [];
            
            if (currentDifficulty === "easy") {
                // Easy: strictly most common words
                for (let i = 0; i < count; i++) {
                    const rIdx = Math.floor(Math.random() * easyPool.length);
                    sentenceList.push(easyPool[rIdx]);
                }
            } else if (currentDifficulty === "medium") {
                // Medium: 40% Easy words, 60% Medium words
                const mediumCount = Math.round(count * 0.6);
                const easyCount = count - mediumCount;

                for (let i = 0; i < easyCount; i++) {
                    const rIdx = Math.floor(Math.random() * easyPool.length);
                    sentenceList.push(easyPool[rIdx]);
                }
                for (let i = 0; i < mediumCount; i++) {
                    const rIdx = Math.floor(Math.random() * mediumPool.length);
                    sentenceList.push(mediumPool[rIdx]);
                }
                shuffleArray(sentenceList);
            } else {
                // Hard: 60% Easy/Medium words, 40% Hard academic words
                const hardCount = Math.round(count * 0.4);
                const easyMediumCount = count - hardCount;

                // Easy/Medium pool combined
                const easyMediumPool = [...easyPool, ...mediumPool];
                // Hard pool combined with academic lists
                const combinedHardPool = [...hardPool, ...wordsDatabaseHard];

                for (let i = 0; i < easyMediumCount; i++) {
                    const rIdx = Math.floor(Math.random() * easyMediumPool.length);
                    sentenceList.push(easyMediumPool[rIdx]);
                }
                for (let i = 0; i < hardCount; i++) {
                    const rIdx = Math.floor(Math.random() * combinedHardPool.length);
                    sentenceList.push(combinedHardPool[rIdx]);
                }
                shuffleArray(sentenceList);
            }
            
            return sentenceList;
        } catch (err) {
            console.warn("Google words dynamic generation failed, falling back to local database", err);
        }
    }

    // Fallback to local database (words.js database)
    let db;
    if (currentDifficulty === "easy") {
        db = [...wordsDatabaseEasy];
    } else if (currentDifficulty === "medium") {
        db = [...wordsDatabaseMedium];
    } else {
        db = [...wordsDatabaseHard];
    }

    // Deduplicate array using Set, and filter keeping words >= 3 chars or whitelisted common short words
    const allowedShort = new Set(["a", "i", "of", "to", "in", "it", "is", "on", "by", "or", "be", "at", "as", "an", "we", "us", "if", "my", "do", "no", "he", "up", "so", "am", "me", "go"]);
    let words = Array.from(new Set(db)).filter(w => w.length >= 3 || allowedShort.has(w));
    
    // Make sure we have enough unique words
    if (count > words.length) {
        count = words.length;
    }

    let sentenceList = [];
    for (let i = 0; i < count; i++) {
        let index = Math.floor(Math.random() * words.length);
        sentenceList.push(words[index]);
        words.splice(index, 1); // remove word to avoid duplicates
    }

    return sentenceList;
}

// Render words to DOM
function renderWords() {
    // Clear previous
    const oldCaret = document.getElementById("caret");
    wordsContainer.innerHTML = "";
    wordsContainer.appendChild(oldCaret);

    targetWords.forEach((wordText, wordIdx) => {
        const wordDiv = document.createElement("div");
        wordDiv.className = "word";
        wordDiv.dataset.wordIdx = wordIdx;

        for (let charIdx = 0; charIdx < wordText.length; charIdx++) {
            const charSpan = document.createElement("span");
            charSpan.className = "char";
            charSpan.textContent = wordText[charIdx];
            wordDiv.appendChild(charSpan);
        }

        // Add space span after each word except the last one
        if (wordIdx < targetWords.length - 1) {
            const spaceSpan = document.createElement("span");
            spaceSpan.className = "char space-char";
            spaceSpan.innerHTML = "&nbsp;"; // space char representation
            wordDiv.appendChild(spaceSpan);
        }
            wordsContainer.appendChild(wordDiv);
    });
}

// // Reset typing test state
function resetTest() {
    targetWords = generateSentence();
    typedWords = Array(targetWords.length).fill("");
    activeWordIndex = 0;
    startTime = null;
    endTime = null;
    isTesting = false;
    hiddenInput.value = "";
    resultsPanel.style.display = "none";
    
    renderWords();
    updateTypingDisplay();
    updateCaretPosition();
    focusInput();
}

// Update the visual floating caret position
function updateCaretPosition() {
    const caret = document.getElementById("caret");
    const container = document.getElementById("words-container");
    const wordElements = container.querySelectorAll(".word");
    
    const activeWordDiv = wordElements[activeWordIndex];
    if (!activeWordDiv) return;
    
    // Remove active class from all chars in container
    container.querySelectorAll(".char").forEach(c => c.classList.remove("active"));
    
    const typedLen = typedWords[activeWordIndex].length;
    const charSpans = activeWordDiv.querySelectorAll(".char:not(.space-char)");
    
    let targetSpan = null;
    let placeAfter = false;
    
    if (typedLen < charSpans.length) {
        targetSpan = charSpans[typedLen];
        if (targetSpan) {
            targetSpan.classList.add("active");
        }
    } else {
        targetSpan = charSpans[charSpans.length - 1];
        placeAfter = true;
    }
    
    // Handle dynamic line scrolling (Monkeytype style)
    const wordTop = activeWordDiv.offsetTop;
    const wordHeight = activeWordDiv.offsetHeight;
    const style = window.getComputedStyle(activeWordDiv);
    const marginBottom = parseFloat(style.marginBottom) || 0;
    const lineHeight = wordHeight + marginBottom;
    
    const firstWord = container.querySelector(".word");
    const containerPaddingTop = firstWord ? firstWord.offsetTop : 40;
    
    if (wordTop > containerPaddingTop + lineHeight) {
        container.scrollTop = wordTop - containerPaddingTop - lineHeight;
    } else {
        container.scrollTop = 0;
    }
    
    if (targetSpan) {
        const charRect = targetSpan.getBoundingClientRect();
        const containerRect = container.getBoundingClientRect();
        
        if (placeAfter) {
            caret.style.left = `${charRect.right - containerRect.left + container.scrollLeft}px`;
        } else {
            caret.style.left = `${charRect.left - containerRect.left + container.scrollLeft}px`;
        }
        caret.style.top = `${charRect.top - containerRect.top + container.scrollTop}px`;
        caret.style.height = `${charRect.height}px`;
        caret.style.display = "block";
    }
}

// Render dynamic visual feedback for typed words, handling extra characters Monkeytype-style
function updateTypingDisplay() {
    const wordElements = wordsContainer.querySelectorAll(".word");
    
    targetWords.forEach((targetWord, wIdx) => {
        const wordDiv = wordElements[wIdx];
        if (!wordDiv) return;
        
        const typedWord = typedWords[wIdx] || "";
        const charSpans = wordDiv.querySelectorAll(".char:not(.extra):not(.space-char)");
        
        // 1. Update target characters
        for (let cIdx = 0; cIdx < targetWord.length; cIdx++) {
            const charSpan = charSpans[cIdx];
            if (!charSpan) continue;
            
            if (cIdx < typedWord.length) {
                if (typedWord[cIdx] === targetWord[cIdx]) {
                    charSpan.className = "char correct";
                } else {
                    charSpan.className = "char incorrect";
                }
            } else {
                if (wIdx < activeWordIndex) {
                    charSpan.className = "char incorrect untyped";
                } else {
                    charSpan.className = "char";
                }
            }
        }
        
        // 2. Handle extra characters
        // First remove all existing extra character spans in this word
        const existingExtras = wordDiv.querySelectorAll(".char.extra");
        existingExtras.forEach(el => el.remove());
        
        // If typed word length is greater than target word length, append extra character spans
        if (typedWord.length > targetWord.length) {
            const spaceSpan = wordDiv.querySelector(".space-char");
            
            for (let eIdx = targetWord.length; eIdx < typedWord.length; eIdx++) {
                const extraSpan = document.createElement("span");
                extraSpan.className = "char incorrect extra";
                extraSpan.textContent = typedWord[eIdx];
                
                if (spaceSpan) {
                    wordDiv.insertBefore(extraSpan, spaceSpan);
                } else {
                    wordDiv.appendChild(extraSpan);
                }
            }
        }
    });
}

// Intercept specific keydowns for word transitions (Spacebar / empty Backspace)
function handleKeydown(e) {
    if (e.key === " ") {
        e.preventDefault();
        
        // Save current input
        typedWords[activeWordIndex] = hiddenInput.value;
        
        if (activeWordIndex < targetWords.length - 1) {
            // Move to next word
            activeWordIndex++;
            hiddenInput.value = "";
            typedWords[activeWordIndex] = "";
            updateTypingDisplay();
            updateCaretPosition();
        } else {
            // Space pressed on last word -> complete test!
            completeTest();
        }
    } else if (e.key === "Backspace") {
        if (hiddenInput.value === "" && activeWordIndex > 0) {
            e.preventDefault();
            
            // Move to previous word
            activeWordIndex--;
            hiddenInput.value = typedWords[activeWordIndex];
            updateTypingDisplay();
            updateCaretPosition();
        }
    }
}

// Handle real-time keystroke input
function handleInput(e) {
    const inputVal = hiddenInput.value;
    
    // Temporarily pause caret blinking animation while typing
    const caret = document.getElementById("caret");
    if (caret) {
        caret.classList.add("typing");
        clearTimeout(caretTimeout);
        caretTimeout = setTimeout(() => {
            caret.classList.remove("typing");
        }, 500);
    }
    
    // Start timer on first keystroke
    if (!isTesting && inputVal.length > 0) {
        isTesting = true;
        startTime = new Date().getTime();
    }
    
    // Mobile auto-space conversion: some mobile keyboards insert a space on word autocomplete
    if (inputVal.endsWith(" ")) {
        const trimmed = inputVal.slice(0, -1);
        hiddenInput.value = trimmed;
        typedWords[activeWordIndex] = trimmed;
        
        if (activeWordIndex < targetWords.length - 1) {
            activeWordIndex++;
            hiddenInput.value = "";
            typedWords[activeWordIndex] = "";
            updateTypingDisplay();
            updateCaretPosition();
        } else {
            // Space pressed on last word -> complete test!
            completeTest();
        }
        return;
    }
    
    // Save typed characters for active word
    typedWords[activeWordIndex] = inputVal;
    
    // Check if we are on the last word
    if (activeWordIndex === targetWords.length - 1) {
        // If the user types the last letter of the last word correctly, end immediately
        if (typedWords[activeWordIndex] === targetWords[activeWordIndex]) {
            completeTest();
            return;
        }
    }
    
    updateTypingDisplay();
    updateCaretPosition();
}

// Complete the typing test and calculate metrics
function completeTest() {
    endTime = new Date().getTime();
    isTesting = false;
    
    const timeTaken = (endTime - startTime) / 1000; // in seconds
    const minutes = timeTaken / 60;
    
    const targetString = targetWords.join(" ");
    const attemptString = typedWords.join(" ");
    
    // Calculate mistakes and accuracy character-by-character matching typemeter.py's comparison logic
    let mistakeCount = 0;
    let i = 0;
    const example = targetString;
    const attempt = attemptString;
    
    while (i < example.length) {
        if (i < attempt.length) {
            if (example[i] !== attempt[i]) {
                mistakeCount++;
            }
        } else {
            break;
        }
        i++;
    }
    if (i < attempt.length) {
        mistakeCount += (attempt.length - i);
    }
    mistakeCount += (example.length - i);
    
    // Accuracy calculation:
    // accuracy = ((len(example) - mistake)/len(example))*100
    // if(accuracy<0): accuracy = -accuracy
    let accuracy = ((example.length - mistakeCount) / example.length) * 100;
    if (accuracy < 0) {
        accuracy = Math.abs(accuracy);
    }
    
    // WPM and Raw WPM calculation:
    // raw_wpm = attempted_words_count/minute
    // wpm = correct_count/minute
    // where correct_count is word level matching
    const actualWords = targetWords;
    const attemptedWords = typedWords.map(w => w.trim()).filter(w => w.length > 0);
    
    const actualWordsCount = actualWords.length;
    const attemptedWordsCount = attemptedWords.length;
    const minLength = Math.min(actualWordsCount, attemptedWordsCount);
    
    let correctWordsCount = 0;
    for (let wIdx = 0; wIdx < minLength; wIdx++) {
        if (actualWords[wIdx] === typedWords[wIdx]) {
            correctWordsCount++;
        }
    }
    
    const rawWpm = minutes > 0 ? (attemptedWordsCount / minutes) : 0;
    const wpm = minutes > 0 ? (correctWordsCount / minutes) : 0;
    
    // Render Results
    resWpm.textContent = Math.round(wpm);
    resAccuracy.textContent = `${accuracy.toFixed(1)}%`;
    resRawWpm.textContent = Math.round(rawWpm);
    resTime.textContent = `${timeTaken.toFixed(2)}s`;
    resMistakes.textContent = mistakeCount;
    
    resultsPanel.style.display = "flex";
    
    // Blur input
    hiddenInput.blur();
}
