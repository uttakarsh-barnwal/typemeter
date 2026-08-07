document.addEventListener("DOMContentLoaded", async () => {
    let csrfToken = "";
    let currentUser = null;

    // Element references
    const unauthView = document.getElementById("unauth-view");
    const authView = document.getElementById("auth-view");
    const unauthLoginBtn = document.getElementById("unauth-login-btn");

    const authBtn = document.getElementById("auth-btn");
    const authUsername = document.getElementById("auth-username");
    const authModal = document.getElementById("auth-modal");
    const closeModalBtn = document.getElementById("close-modal-btn");
    const themeToggle = document.getElementById("theme-toggle");

    // Modal Forms
    const loginForm = document.getElementById("login-form");
    const signupForm = document.getElementById("signup-form");
    const profileView = document.getElementById("profile-view");
    const goToSignup = document.getElementById("go-to-signup");
    const goToLogin = document.getElementById("go-to-login");
    const modalTitle = document.getElementById("modal-title");
    const authMessage = document.getElementById("auth-message");
    const oauthDivider = document.getElementById("oauth-divider");
    const googleBtn = document.getElementById("google-signin-btn");
    const logoutBtn = document.getElementById("logout-btn");

    // Theme Management
    const savedTheme = localStorage.getItem("typemeter-theme") || "dark";
    if (savedTheme === "light") {
        document.body.classList.add("light-theme");
        themeToggle.querySelector("i").className = "fa-solid fa-sun";
    }

    themeToggle.addEventListener("click", () => {
        const isLight = document.body.classList.toggle("light-theme");
        localStorage.setItem("typemeter-theme", isLight ? "light" : "dark");
        themeToggle.querySelector("i").className = isLight ? "fa-solid fa-sun" : "fa-solid fa-moon";
        if (currentUser) fetchHistoryData();
    });

    // Fetch CSRF Token
    try {
        const res = await fetch("/auth/csrf-token");
        const data = await res.json();
        csrfToken = data.csrf_token || "";
    } catch (e) {
        console.error("Failed to fetch CSRF token:", e);
    }

    // Modal helpers
    function showMessage(msg, isError = false) {
        authMessage.textContent = msg;
        authMessage.className = `auth-message ${isError ? "error" : "success"}`;
        authMessage.style.display = "block";
    }

    function hideMessage() {
        authMessage.style.display = "none";
    }

    function openModal() {
        hideMessage();
        authModal.style.display = "flex";
        if (currentUser) {
            modalTitle.textContent = "User Profile";
            loginForm.style.display = "none";
            signupForm.style.display = "none";
            profileView.style.display = "block";
            oauthDivider.style.display = "none";
            googleBtn.style.display = "none";
            document.getElementById("profile-email").textContent = currentUser.email;
            document.getElementById("profile-display-name").textContent = currentUser.display_name || "N/A";
        } else {
            modalTitle.textContent = "Sign In";
            loginForm.style.display = "block";
            signupForm.style.display = "none";
            profileView.style.display = "none";
            oauthDivider.style.display = "block";
            googleBtn.style.display = "flex";
        }
    }

    function closeModal() {
        authModal.style.display = "none";
    }

    authBtn.addEventListener("click", openModal);
    closeModalBtn.addEventListener("click", closeModal);
    if (unauthLoginBtn) unauthLoginBtn.addEventListener("click", openModal);

    goToSignup.addEventListener("click", (e) => {
        e.preventDefault();
        hideMessage();
        modalTitle.textContent = "Create Account";
        loginForm.style.display = "none";
        signupForm.style.display = "block";
    });

    goToLogin.addEventListener("click", (e) => {
        e.preventDefault();
        hideMessage();
        modalTitle.textContent = "Sign In";
        signupForm.style.display = "none";
        loginForm.style.display = "block";
    });

    // Check Auth State
    async function checkAuthState() {
        try {
            const res = await fetch("/auth/me");
            const data = await res.json();
            if (data.authenticated && data.user) {
                currentUser = data.user;
                authUsername.textContent = currentUser.display_name || currentUser.email.split("@")[0];
                authUsername.style.display = "inline";
                unauthView.style.display = "none";
                authView.style.display = "block";
                fetchHistoryData();
            } else {
                currentUser = null;
                authUsername.style.display = "none";
                authView.style.display = "none";
                unauthView.style.display = "block";
            }
        } catch (e) {
            console.error("Auth status check failed:", e);
            unauthView.style.display = "block";
            authView.style.display = "none";
        }
    }

    // Login Form Submit
    loginForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        hideMessage();
        const email = document.getElementById("login-email").value;
        const password = document.getElementById("login-password").value;

        try {
            const res = await fetch("/auth/login", {
                method: "POST",
                headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken },
                body: JSON.stringify({ email, password })
            });
            const data = await res.json();
            if (!res.ok) {
                showMessage(data.error || "Login failed.", true);
            } else {
                closeModal();
                checkAuthState();
            }
        } catch (err) {
            showMessage("Network error. Please try again.", true);
        }
    });

    // Signup Form Submit
    signupForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        hideMessage();
        const email = document.getElementById("signup-email").value;
        const password = document.getElementById("signup-password").value;
        const display_name = document.getElementById("signup-name").value;

        try {
            const res = await fetch("/auth/signup", {
                method: "POST",
                headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken },
                body: JSON.stringify({ email, password, display_name })
            });
            const data = await res.json();
            if (!res.ok) {
                showMessage(data.error || "Registration failed.", true);
            } else {
                closeModal();
                checkAuthState();
            }
        } catch (err) {
            showMessage("Network error. Please try again.", true);
        }
    });

    // Logout
    logoutBtn.addEventListener("click", async () => {
        try {
            await fetch("/auth/logout", {
                method: "POST",
                headers: { "X-CSRF-Token": csrfToken }
            });
            currentUser = null;
            closeModal();
            checkAuthState();
        } catch (err) {
            console.error("Logout failed:", err);
        }
    });

    googleBtn.addEventListener("click", () => {
        window.location.href = "/auth/google";
    });

    // Fetch and Render Personal History & Records
    async function fetchHistoryData() {
        try {
            const [recRes, histRes] = await Promise.all([
                fetch("/api/records"),
                fetch("/api/history?limit=50")
            ]);

            if (!recRes.ok || !histRes.ok) {
                if (recRes.status === 401 || histRes.status === 401) {
                    currentUser = null;
                    authView.style.display = "none";
                    unauthView.style.display = "block";
                }
                return;
            }

            const records = await recRes.json();
            const history = await histRes.json();

            renderRecords(records);
            renderChart(records.trends || []);
            renderHistoryTable(history.sessions || []);
        } catch (e) {
            console.error("Failed to load history metrics:", e);
        }
    }

    function renderRecords(rec) {
        document.getElementById("rec-peak-wpm").textContent = rec.peak_wpm || 0;
        document.getElementById("rec-peak-acc").textContent = `${rec.peak_accuracy || 0}%`;
        document.getElementById("rec-avg-wpm").textContent = rec.avg_wpm || 0;
        document.getElementById("rec-total-sessions").textContent = rec.total_sessions || 0;
        
        const seconds = rec.total_time_seconds || 0;
        if (seconds >= 3600) {
            document.getElementById("rec-total-time").textContent = `${(seconds / 3600).toFixed(1)}h`;
        } else if (seconds >= 60) {
            document.getElementById("rec-total-time").textContent = `${(seconds / 60).toFixed(1)}m`;
        } else {
            document.getElementById("rec-total-time").textContent = `${Math.round(seconds)}s`;
        }
    }

    function renderChart(trends) {
        const svg = document.getElementById("trend-svg");
        svg.innerHTML = "";

        if (!trends || trends.length < 2) {
            svg.innerHTML = `<text x="50%" y="50%" dominant-baseline="middle" text-anchor="middle" fill="var(--sub-color)" font-size="14">Complete at least 2 sessions to view your trend chart</text>`;
            return;
        }

        const width = svg.clientWidth || 800;
        const height = svg.clientHeight || 260;
        const padding = { top: 20, right: 30, bottom: 30, left: 45 };

        const innerW = width - padding.left - padding.right;
        const innerH = height - padding.top - padding.bottom;

        const maxWpm = Math.max(...trends.map(t => t.wpm), 60);
        const minWpm = Math.min(...trends.map(t => t.wpm), 0);

        const xStep = innerW / (trends.length - 1);
        const getY = (val) => padding.top + innerH - ((val - minWpm) / (maxWpm - minWpm || 1)) * innerH;

        // Render Grid Lines
        let gridHtml = "";
        for (let i = 0; i <= 4; i++) {
            const val = Math.round(minWpm + (maxWpm - minWpm) * (i / 4));
            const y = padding.top + innerH - (innerH * (i / 4));
            gridHtml += `<line x1="${padding.left}" y1="${y}" x2="${width - padding.right}" y2="${y}" stroke="var(--border-color)" stroke-dasharray="4 4" stroke-width="1"/>`;
            gridHtml += `<text x="${padding.left - 8}" y="${y + 4}" text-anchor="end" fill="var(--sub-color)" font-size="11">${val}</text>`;
        }
        svg.innerHTML += gridHtml;

        // Build Line Path
        let points = trends.map((t, idx) => {
            const x = padding.left + idx * xStep;
            const y = getY(t.wpm);
            return `${x},${y}`;
        }).join(" ");

        const mainColor = getComputedStyle(document.documentElement).getPropertyValue('--main-color').trim() || '#e2b714';

        // Draw Line
        const polyline = `<polyline fill="none" stroke="${mainColor}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" points="${points}" />`;
        svg.innerHTML += polyline;

        // Draw Data Points
        trends.forEach((t, idx) => {
            const x = padding.left + idx * xStep;
            const y = getY(t.wpm);
            const circle = `<circle cx="${x}" cy="${y}" r="4" fill="${mainColor}" stroke="var(--bg-color)" stroke-width="2"><title>WPM: ${t.wpm} (${t.accuracy}%)</title></circle>`;
            svg.innerHTML += circle;
        });
    }

    function renderHistoryTable(sessions) {
        const tbody = document.getElementById("history-tbody");
        const noMsg = document.getElementById("no-history-msg");
        tbody.innerHTML = "";

        if (!sessions || sessions.length === 0) {
            noMsg.style.display = "block";
            return;
        }

        noMsg.style.display = "none";
        sessions.forEach(s => {
            const dt = new Date(s.created_at);
            const dateStr = dt.toLocaleDateString() + " " + dt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
            
            const tr = document.createElement("tr");
            tr.style.borderBottom = "1px solid var(--border-color)";
            tr.innerHTML = `
                <td style="padding: 12px; color: var(--sub-color);">${dateStr}</td>
                <td style="padding: 12px; font-weight: 700; color: var(--main-color);">${s.wpm}</td>
                <td style="padding: 12px; color: var(--text-color);">${s.raw_wpm}</td>
                <td style="padding: 12px; color: var(--text-color);">${s.accuracy}%</td>
                <td style="padding: 12px; color: ${s.mistakes_count > 0 ? 'var(--incorrect)' : 'var(--sub-color)'};">${s.mistakes_count}</td>
                <td style="padding: 12px; text-transform: capitalize; color: var(--sub-color);">${s.difficulty}</td>
                <td style="padding: 12px; color: var(--sub-color);">${s.time_seconds}s</td>
            `;
            tbody.appendChild(tr);
        });
    }

    // Initial check
    checkAuthState();
});
