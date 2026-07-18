// State Variables
let targetWords = [];
let typedText = "";
let startTime = null;
let endTime = null;
let isTesting = false;
let currentDifficulty = "easy";
let wordCountMode = "25";
let customWordCount = 25;

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

// Ported sentence generator from typemeter.py
function generateSentence() {
    let db;
    if (currentDifficulty === "easy") {
        db = [...wordsDatabaseEasy];
    } else if (currentDifficulty === "medium") {
        db = [...wordsDatabaseMedium];
    } else {
        db = [...wordsDatabaseHard];
    }

    // Deduplicate array using Set, just like python does: set1 = set(words_database)
    let words = Array.from(new Set(db));
    
    // Determine target word count
    let count = wordCountMode === "custom" ? customWordCount : parseInt(wordCountMode);
    
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

// Reset typing test state
function resetTest() {
    targetWords = generateSentence();
    typedText = "";
    startTime = null;
    endTime = null;
    isTesting = false;
    hiddenInput.value = "";
    resultsPanel.style.display = "none";
    
    renderWords();
    updateCaretPosition();
    focusInput();
}

// Update the visual floating caret position
function updateCaretPosition() {
    const caret = document.getElementById("caret");
    const container = document.getElementById("words-container");
    const chars = wordsContainer.querySelectorAll(".char");
    
    const currentIndex = typedText.length;
    
    if (currentIndex < chars.length) {
        const activeChar = chars[currentIndex];
        
        // Remove active class from all, add to current
        chars.forEach((c, idx) => {
            if (idx === currentIndex) {
                c.classList.add("active");
            } else {
                c.classList.remove("active");
            }
        });

        // Handle dynamic line scrolling (Monkeytype style)
        const activeWord = activeChar.parentElement;
        if (activeWord) {
            const wordTop = activeWord.offsetTop;
            const wordHeight = activeWord.offsetHeight;
            const style = window.getComputedStyle(activeWord);
            const marginBottom = parseFloat(style.marginBottom) || 0;
            const lineHeight = wordHeight + marginBottom;
            
            // Padding inside the words wrapper is 2.5rem = 40px
            const firstWord = container.querySelector(".word");
            const containerPaddingTop = firstWord ? firstWord.offsetTop : 40;
            
            // If we are on line 3 or below: scroll so that active line is visually the 2nd line
            if (wordTop > containerPaddingTop + lineHeight) {
                container.scrollTop = wordTop - containerPaddingTop - lineHeight;
            } else {
                container.scrollTop = 0;
            }
        }

        const charRect = activeChar.getBoundingClientRect();
        const containerRect = container.getBoundingClientRect();
        
        caret.style.left = `${charRect.left - containerRect.left + container.scrollLeft}px`;
        caret.style.top = `${charRect.top - containerRect.top + container.scrollTop}px`;
        caret.style.height = `${charRect.height}px`;
        caret.style.display = "block";
    } else {
        // We reached the end of the text
        chars.forEach(c => c.classList.remove("active"));
        const lastChar = chars[chars.length - 1];
        if (lastChar) {
            // First ensure we keep scroll at bottom
            const containerPaddingTop = 40;
            const lastWord = lastChar.parentElement;
            if (lastWord) {
                const wordTop = lastWord.offsetTop;
                const wordHeight = lastWord.offsetHeight;
                const style = window.getComputedStyle(lastWord);
                const marginBottom = parseFloat(style.marginBottom) || 0;
                const lineHeight = wordHeight + marginBottom;
                
                if (wordTop > containerPaddingTop + lineHeight) {
                    container.scrollTop = wordTop - containerPaddingTop - lineHeight;
                }
            }

            const charRect = lastChar.getBoundingClientRect();
            const containerRect = container.getBoundingClientRect();
            
            // Caret should go right after the last character
            caret.style.left = `${charRect.right - containerRect.left + container.scrollLeft}px`;
            caret.style.top = `${charRect.top - containerRect.top + container.scrollTop}px`;
            caret.style.height = `${charRect.height}px`;
            caret.style.display = "block";
        }
    }
}

// Handle real-time keystroke input
function handleInput(e) {
    const inputVal = hiddenInput.value;
    
    // Start timer on first keystroke
    if (!isTesting && inputVal.length > 0) {
        isTesting = true;
        startTime = new Date().getTime();
    }
    
    typedText = inputVal;
    
    const chars = wordsContainer.querySelectorAll(".char");
    const targetString = targetWords.join(" "); // Reconstruction of target text with spaces
    
    // Style characters up to the input length
    for (let i = 0; i < chars.length; i++) {
        const charSpan = chars[i];
        
        if (i < typedText.length) {
            // Retrieve exact character representation for target (treating space spans correctly)
            const targetChar = charSpan.classList.contains("space-char") ? " " : charSpan.textContent;
            const typedChar = typedText[i];
            
            if (typedChar === targetChar) {
                charSpan.classList.add("correct");
                charSpan.classList.remove("incorrect");
            } else {
                charSpan.classList.add("incorrect");
                charSpan.classList.remove("correct");
            }
        } else {
            // Reset characters that are ahead of user typing
            charSpan.classList.remove("correct", "incorrect");
        }
    }
    
    updateCaretPosition();
    
    // Check if test is completed
    if (typedText.length >= targetString.length) {
        completeTest();
    }
}

// Complete the typing test and calculate metrics
function completeTest() {
    endTime = new Date().getTime();
    isTesting = false;
    
    const timeTaken = (endTime - startTime) / 1000; // in seconds
    const minutes = timeTaken / 60;
    
    const targetString = targetWords.join(" ");
    
    // Calculate mistakes and accuracy EXACTLY mirroring typemeter.py's comparison logic:
    // mistake = 0
    // i = 0
    // while(i<len(example)):
    //     if(i<len(attempt_list)):
    //         if(example[i] != attempt_list[i]):
    //             mistake+=1
    //     else:
    //         break
    //     i+=1
    // if(i<len(attempt_list)):
    //     mistake = mistake + (len(attempt_list)-i)
    // mistake = mistake + (len(example) - i)
    let mistakeCount = 0;
    let i = 0;
    const example = targetString;
    const attempt = typedText;
    
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
    const actualWords = targetString.split(" ");
    const attemptedWords = attempt.trim().split(/\s+/).filter(w => w.length > 0);
    
    const actualWordsCount = actualWords.length;
    const attemptedWordsCount = attemptedWords.length;
    const minLength = Math.min(actualWordsCount, attemptedWordsCount);
    
    let correctWordsCount = 0;
    for (let wIdx = 0; wIdx < minLength; wIdx++) {
        if (actualWords[wIdx] === attemptedWords[wIdx]) {
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
