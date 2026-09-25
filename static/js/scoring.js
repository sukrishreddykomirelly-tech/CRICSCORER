// scoring.js

let matchState = null;
const shownStats = new Set();
let activeExtra = null; // 'wide', 'noball', 'bye', 'legbye' or null

let currentStrikerId = null;
let currentNonStrikerId = null;
let currentBowlerId = null;
let hasBatterLeft = true;

// DOM Elements
const scoreStrikerName = document.getElementById("score-striker-name");
const scoreStrikerRuns = document.getElementById("score-striker-runs");
const scoreStrikerBalls = document.getElementById("score-striker-balls");
const scoreStrikerSr = document.getElementById("score-striker-sr");
const scoreStrikerRow = document.getElementById("score-striker-row");

const scoreNonStrikerName = document.getElementById("score-non-striker-name");
const scoreNonStrikerRuns = document.getElementById("score-non-striker-runs");
const scoreNonStrikerBalls = document.getElementById("score-non-striker-balls");
const scoreNonStrikerSr = document.getElementById("score-non-striker-sr");
const scoreNonStrikerRow = document.getElementById("score-non-striker-row");

const scoreBowlerName = document.getElementById("score-bowler-name");
const scoreBowlerOvers = document.getElementById("score-bowler-overs");
const scoreBowlerMaidens = document.getElementById("score-bowler-maidens");
const scoreBowlerRuns = document.getElementById("score-bowler-runs");
const scoreBowlerWickets = document.getElementById("score-bowler-wickets");
const scoreBowlerEcon = document.getElementById("score-bowler-econ");
const scoreBowlerRow = document.getElementById("score-bowler-row");
const creaseContainer = document.getElementById("crease-container");
const scoringConsoleCard = document.getElementById("scoring-console-card");
const chaseStatusCard = document.getElementById("chase-status-card");
const chaseTargetVal = document.getElementById("chase-target-val");
const chaseRequirementVal = document.getElementById("chase-requirement-val");
const chaseRrrVal = document.getElementById("chase-rrr-val");

const currentScoreText = document.getElementById("current-score");
const currentOversText = document.getElementById("current-overs");
const targetInfoText = document.getElementById("target-info");
const runRatesText = document.getElementById("run-rates");
const overBallsContainer = document.getElementById("over-balls-list");

// Toggles & Keypads
const extraBtns = document.querySelectorAll(".extra-btn");
const runsBtns = document.querySelectorAll(".runs-btn");
const btnWicket = document.getElementById("btn-wicket");
const btnUndo = document.getElementById("btn-undo");

// Modals
const bowlerModal = document.getElementById("bowler-modal");
const bowlerListContainer = document.getElementById("bowler-list-container");
const btnConfirmBowler = document.getElementById("btn-confirm-bowler");
let selectedNewBowlerId = null;

const squadModal = document.getElementById("squad-modal");
const btnManageSquad = document.getElementById("btn-manage-squad");
const btnCloseSquad = document.getElementById("btn-close-squad");
const squadBattingList = document.getElementById("squad-batting-list");
const squadBowlingList = document.getElementById("squad-bowling-list");
const squadBattingTeamTitle = document.getElementById("squad-batting-team-title");
const squadBowlingTeamTitle = document.getElementById("squad-bowling-team-title");

const wicketModal = document.getElementById("wicket-modal");
const wicketTypeSelect = document.getElementById("wicket-type-select");
const playerDismissedSelect = document.getElementById("player-dismissed-select");
const fielderContainer = document.getElementById("fielder-container");
const fielderSelect = document.getElementById("fielder-select");
const runoutRunsContainer = document.getElementById("runout-runs-container");
const runoutRunsSelect = document.getElementById("runout-runs-select");
const newBatterSelect = document.getElementById("new-batter-select");
const nextStrikerSelect = document.getElementById("next-striker-select");
const btnConfirmWicket = document.getElementById("btn-confirm-wicket");
const btnCancelWicket = document.getElementById("btn-cancel-wicket");

const inningsTransitionContainer = document.getElementById("innings-transition-container");
const inn2StrikerSelect = document.getElementById("inn2-striker-select");
const inn2NonStrikerSelect = document.getElementById("inn2-non-striker-select");
const inn2BowlerSelect = document.getElementById("inn2-bowler-select");
const btnStartInnings2 = document.getElementById("btn-start-innings2");

const matchCompletedContainer = document.getElementById("match-completed-container");
const matchResultText = document.getElementById("match-completed-result");

// Scoring Overlay & Submission Lock
const scoringOverlay = document.getElementById("scoring-processing-overlay");
const scoringOverlayTitle = document.getElementById("scoring-overlay-title");
const scoringOverlaySubtitle = document.getElementById("scoring-overlay-subtitle");
let isScoringInProgress = false;

function showScoringOverlay(title = "Scoring ball...", subtitle = "Please wait...") {
    if (isScoringInProgress) return false;
    isScoringInProgress = true;
    
    if (scoringOverlayTitle) scoringOverlayTitle.innerText = title;
    if (scoringOverlaySubtitle) scoringOverlaySubtitle.innerText = subtitle;
    if (scoringOverlay) scoringOverlay.style.display = "flex";
    
    // Disable scoring controls to prevent double submissions
    runsBtns.forEach(btn => { btn.disabled = true; });
    extraBtns.forEach(btn => { btn.disabled = true; });
    if (btnWicket) btnWicket.disabled = true;
    if (btnUndo) btnUndo.disabled = true;
    const btnSwap = document.getElementById("btn-swap-batsmen");
    if (btnSwap) btnSwap.disabled = true;
    if (btnManageSquad) btnManageSquad.disabled = true;
    const btnEnd = document.getElementById("btn-end-match");
    if (btnEnd) btnEnd.disabled = true;
    
    return true;
}

function hideScoringOverlay() {
    isScoringInProgress = false;
    if (scoringOverlay) scoringOverlay.style.display = "none";
    
    // Re-enable scoring controls
    runsBtns.forEach(btn => { btn.disabled = false; });
    extraBtns.forEach(btn => { btn.disabled = false; });
    if (btnWicket) btnWicket.disabled = false;
    if (btnUndo) btnUndo.disabled = false;
    const btnSwap = document.getElementById("btn-swap-batsmen");
    if (btnSwap) btnSwap.disabled = false;
    if (btnManageSquad) btnManageSquad.disabled = false;
    const btnEnd = document.getElementById("btn-end-match");
    if (btnEnd) btnEnd.disabled = false;
}

function showScoringError(message = "Unable to save ball. Please check your connection and try again.") {
    const container = document.getElementById("career-stats-toast-container");
    if (!container) {
        alert(message);
        return;
    }
    
    const toast = document.createElement("div");
    toast.className = "career-toast premium-card";
    toast.style.cssText = "width: 320px; max-width: calc(100vw - 2rem); display: flex; flex-direction: column; gap: 0.5rem; border-left: 4px solid var(--danger-red); animation: slideIn 0.3s ease-out; pointer-events: auto; position: relative; overflow: hidden; background: rgba(15, 23, 42, 0.98); backdrop-filter: blur(10px); padding: 1rem; border-radius: var(--radius-md); box-shadow: 0 10px 30px rgba(0, 0, 0, 0.6);";
    
    toast.innerHTML = `
        <div style="display: flex; gap: 0.75rem; align-items: center;">
            <i class="fa-solid fa-triangle-exclamation" style="color: var(--danger-red); font-size: 1.4rem;"></i>
            <div>
                <h4 style="margin: 0; font-size: 0.95rem; color: #fca5a5; font-weight: 700;">Scoring Error</h4>
                <div style="font-size: 0.82rem; color: var(--text-primary); margin-top: 0.2rem; line-height: 1.3;">${message}</div>
            </div>
        </div>
        <div style="position: absolute; bottom: 0; left: 0; height: 3px; background: var(--danger-red); animation: progressTimer 6s linear forwards; width: 100%;"></div>
    `;
    
    container.appendChild(toast);
    
    setTimeout(() => {
        toast.style.animation = "slideOut 0.3s ease-in forwards";
        setTimeout(() => {
            toast.remove();
        }, 300);
    }, 5700);
}

// Initialize Scoring Page
document.addEventListener("DOMContentLoaded", () => {
    loadMatchState();
    setupEventListeners();
});

function loadMatchState() {
    return fetch(`/api/match/${matchId}/state`)
        .then(res => {
            if (!res.ok) throw new Error(`HTTP error ${res.status}`);
            return res.json();
        })
        .then(data => {
            matchState = data;
            renderUI();
            return data;
        })
        .catch(err => {
            console.error("Error loading match state:", err);
            throw err;
        });
}

function setupEventListeners() {
    // Extras Toggles
    extraBtns.forEach(btn => {
        btn.addEventListener("click", () => {
            if (isScoringInProgress) return;
            const extra = btn.getAttribute("data-extra");
            if (activeExtra === extra) {
                activeExtra = null;
                btn.classList.remove("selected");
            } else {
                activeExtra = extra;
                extraBtns.forEach(b => b.classList.remove("selected"));
                btn.classList.add("selected");
            }
        });
    });

    // Runs Keypad
    runsBtns.forEach(btn => {
        btn.addEventListener("click", () => {
            if (isScoringInProgress) return;
            const runs = parseInt(btn.getAttribute("data-runs"));
            handleRunEntry(runs);
        });
    });

    // Undo Delivery Button
    btnUndo.addEventListener("click", () => {
        if (isScoringInProgress) return;
        if (!confirm("Are you sure you want to undo the last delivery?")) return;
        
        const inn = getActiveInnings();
        if (!inn) return;
        
        if (!showScoringOverlay("Undoing delivery...", "Please wait...")) return;
        
        fetch(`/api/match/${matchId}/undo`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ innings_id: inn.innings_id })
        })
        .then(res => {
            if (!res.ok) throw new Error(`Server returned status ${res.status}`);
            return res.json();
        })
        .then(data => {
            if (data && data.error) throw new Error(data.error);
            activeExtra = null;
            extraBtns.forEach(b => b.classList.remove("selected"));
            return loadMatchState();
        })
        .then(() => {
            hideScoringOverlay();
        })
        .catch(err => {
            console.error("Error undoing delivery:", err);
            hideScoringOverlay();
            showScoringError("Unable to undo delivery. Please check your connection.");
        });
    });

    // Wicket Button -> Trigger Wicket Modal
    btnWicket.addEventListener("click", () => {
        if (isScoringInProgress) return;
        openWicketModal();
    });

    btnCancelWicket.addEventListener("click", () => {
        closeWicketModal();
    });

    wicketTypeSelect.addEventListener("change", (e) => {
        const type = e.target.value;
        // Caught/Stumped/Run Out require fielder selector
        if (["caught", "stumped", "run_out"].includes(type)) {
            fielderContainer.style.display = "block";
        } else {
            fielderContainer.style.display = "none";
        }
        
        // Run out allows entering runs run before wicket
        if (type === "run_out") {
            runoutRunsContainer.style.display = "block";
            playerDismissedSelect.disabled = false;
        } else {
            runoutRunsContainer.style.display = "none";
            playerDismissedSelect.value = "striker"; // default
            playerDismissedSelect.disabled = true;
        }
    });

    btnConfirmWicket.addEventListener("click", () => {
        if (isScoringInProgress) return;
        submitWicket();
    });

    // Confirm Bowler Change
    btnConfirmBowler.addEventListener("click", () => {
        if (isScoringInProgress) return;
        if (!selectedNewBowlerId) return;
        const inn = getActiveInnings();
        
        showScoringOverlay("Selecting bowler...", "Please wait...");
        fetch(`/api/match/${matchId}/change_bowler`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                innings_id: inn.innings_id,
                bowler_id: selectedNewBowlerId
            })
        })
        .then(res => {
            if (!res.ok) throw new Error(`Server returned status ${res.status}`);
            return res.json();
        })
        .then(() => {
            closeBowlerModal();
            return loadMatchState();
        })
        .then(() => {
            hideScoringOverlay();
        })
        .catch(err => {
            console.error(err);
            hideScoringOverlay();
            showScoringError("Unable to change bowler. Please try again.");
        });
    });

    // Start Innings 2 Button
    btnStartInnings2.addEventListener("click", () => {
        if (isScoringInProgress) return;
        const striker = parseInt(inn2StrikerSelect.value);
        const nonStriker = parseInt(inn2NonStrikerSelect.value);
        const bowler = parseInt(inn2BowlerSelect.value);
        
        if (!striker || !nonStriker || !bowler) {
            alert("Please select opening batters and bowler.");
            return;
        }
        
        if (striker === nonStriker) {
            alert("Striker and Non-Striker must be different players.");
            return;
        }
        
        showScoringOverlay("Starting Innings 2...", "Please wait...");
        fetch(`/api/match/${matchId}/start_second_innings`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                striker_id: striker,
                non_striker_id: nonStriker,
                bowler_id: bowler
            })
        })
        .then(res => {
            if (!res.ok) throw new Error(`Server returned status ${res.status}`);
            return res.json();
        })
        .then(() => {
            inningsTransitionContainer.style.display = "none";
            return loadMatchState();
        })
        .then(() => {
            hideScoringOverlay();
        })
        .catch(err => {
            console.error(err);
            hideScoringOverlay();
            showScoringError("Unable to start second innings. Please try again.");
        });
    });
}

function getActiveInnings() {
    if (!matchState || matchState.current_innings_idx === -1) return null;
    return matchState.innings[matchState.current_innings_idx];
}

function handleRunEntry(runs) {
    if (isScoringInProgress) return;
    
    const inn = getActiveInnings();
    if (!inn) return;

    let runs_batter = 0;
    let runs_extras = 0;
    let extra_type = activeExtra;
    let is_legal = 1;

    if (extra_type === "wide") {
        is_legal = 0;
        runs_extras = runs; // runs represents additional runs run off wide
    } else if (extra_type === "noball") {
        is_legal = 0;
        // Prompt to check if runs are off the bat or byes
        const isOffBat = confirm("Were these runs scored off the bat?\n(OK = Runs to batter, Cancel = Runs as Byes)");
        if (isOffBat) {
            runs_batter = runs;
        } else {
            runs_extras = runs;
        }
    } else if (extra_type === "bye" || extra_type === "legbye") {
        runs_extras = runs;
    } else {
        runs_batter = runs;
    }

    if (!showScoringOverlay("Scoring ball...", "Please wait...")) return;

    // Determine current over count logic
    const over_number = Math.floor(inn.balls_bowled / 6) + 1;
    const ball_of_over = (inn.balls_bowled % 6) + 1;
    const delivery_count = inn.over_balls_log.length + 1;

    const reqData = {
        innings_id: inn.innings_id,
        over_number: over_number,
        ball_of_over: ball_of_over,
        delivery_count: delivery_count,
        striker_id: inn.striker ? inn.striker.id : null,
        non_striker_id: inn.non_striker ? inn.non_striker.id : null,
        bowler_id: inn.bowler ? inn.bowler.id : null,
        runs_batter: runs_batter,
        runs_extras: runs_extras,
        extra_type: extra_type,
        is_legal: is_legal,
        is_wicket: 0,
        wicket_type: null,
        player_dismissed_id: null,
        fielder_id: null,
        is_bowler_wicket: 0,
        commentary: generateCommentaryText(runs_batter, runs_extras, extra_type, false, null, inn.striker ? inn.striker.name : "", inn.bowler ? inn.bowler.name : "")
    };

    fetch(`/api/match/${matchId}/delivery`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(reqData)
    })
    .then(res => {
        if (!res.ok) throw new Error(`Server returned status ${res.status}`);
        return res.json();
    })
    .then(data => {
        if (data && data.error) throw new Error(data.error);
        // Reset extra toggles
        activeExtra = null;
        extraBtns.forEach(b => b.classList.remove("selected"));
        return loadMatchState();
    })
    .then(() => {
        hideScoringOverlay();
    })
    .catch(err => {
        console.error("Error submitting ball:", err);
        hideScoringOverlay();
        showScoringError("Unable to save ball. Please check your connection and try again.");
    });
}

// Commentary text generator
function generateCommentaryText(runs_batter, runs_extras, extra_type, is_wicket, wicket_type, striker_name, bowler_name, player_dismissed_name) {
    if (is_wicket) {
        const dis_str = player_dismissed_name ? ` (${player_dismissed_name} dismissed)` : "";
        return `${bowler_name} to ${striker_name}, WICKET! ${wicket_type.replace(/_/g, ' ').toUpperCase()}${dis_str}`;
    }
    if (extra_type === "wide") {
        const extra_str = runs_extras > 0 ? `+ ${runs_extras} runs run` : "";
        return `${bowler_name} to ${striker_name}, WIDE! ${extra_str}`;
    }
    if (extra_type === "noball") {
        const type_str = runs_batter > 0 ? `, batter hits ${runs_batter}` : (runs_extras > 0 ? `, run byes: ${runs_extras}` : "");
        return `${bowler_name} to ${striker_name}, NO BALL! ${type_str}`;
    }
    if (extra_type === "bye") {
        return `${bowler_name} to ${striker_name}, BYES! ${runs_extras} runs completed`;
    }
    if (extra_type === "legbye") {
        return `${bowler_name} to ${striker_name}, LEG BYES! ${runs_extras} runs completed`;
    }
    if (runs_batter === 4) {
        return `${bowler_name} to ${striker_name}, FOUR! Nicely timed boundary.`;
    }
    if (runs_batter === 6) {
        return `${bowler_name} to ${striker_name}, SIX! Massive hit over the fence.`;
    }
    if (runs_batter === 0) {
        return `${bowler_name} to ${striker_name}, dot ball.`;
    }
    return `${bowler_name} to ${striker_name}, ${runs_batter} run(s).`;
}

// --- WICKET MODAL LOGIC ---

function openWicketModal() {
    const inn = getActiveInnings();
    if (!inn) return;
    
    // Clear selectors
    let dismissedHtml = "";
    if (inn.striker && inn.striker.id) {
        dismissedHtml += `<option value="${inn.striker.id}">${inn.striker.name} (Striker)</option>`;
    }
    if (inn.non_striker && inn.non_striker.id) {
        dismissedHtml += `<option value="${inn.non_striker.id}">${inn.non_striker.name} (Non-Striker)</option>`;
    }
    playerDismissedSelect.innerHTML = dismissedHtml;
    
    // Fill fielders (squad list of bowling team)
    const bowlSquad = inn.bowling_team_id === matchState.team1_id ? matchState.team1_squad : matchState.team2_squad;
    let fielderHtml = `<option value="">Select Fielder (optional)...</option>`;
    bowlSquad.forEach(f => {
        fielderHtml += `<option value="${f.id}">${f.name}</option>`;
    });
    fielderSelect.innerHTML = fielderHtml;
    
    // Fill new batter options (squad of batting team who haven't batted)
    const batSquad = inn.batting_team_id === matchState.team1_id ? matchState.team1_squad : matchState.team2_squad;
    
    // Get list of batted player IDs from scorecard
    const battedIds = inn.batting_scorecard.map(b => parseInt(b.id));
    // include striker and non-striker as they are currently batting
    if (inn.striker && inn.striker.id) {
        battedIds.push(inn.striker.id);
    }
    if (inn.non_striker && inn.non_striker.id) {
        battedIds.push(inn.non_striker.id);
    }
    
    // A player B cannot bat if they replaced a player A who already batted
    const disabledBatterIds = new Set();
    if (matchState.substitutions) {
        matchState.substitutions.forEach(s => {
            if (battedIds.includes(s.outgoing_id)) {
                disabledBatterIds.add(s.incoming_id);
            }
        });
    }
    
    const yetToBat = batSquad.filter(b => !battedIds.includes(b.id) && !disabledBatterIds.has(b.id));
    hasBatterLeft = yetToBat.length > 0;
    
    let batterHtml = `<option value="">Select incoming batter...</option>`;
    yetToBat.forEach(b => {
        batterHtml += `<option value="${b.id}">${b.name}</option>`;
    });
    newBatterSelect.innerHTML = batterHtml;
    
    // Set up next striker select options
    const populateNextStrikerOptions = () => {
        const in_bat = newBatterSelect.value;
        const dismissed_id = parseInt(playerDismissedSelect.value);
        const striker_id = inn.striker ? inn.striker.id : null;
        const non_striker_id = inn.non_striker ? inn.non_striker.id : null;
        
        const remaining_batter = dismissed_id === striker_id ? non_striker_id : striker_id;
        const remaining_name = dismissed_id === striker_id ? (inn.non_striker ? inn.non_striker.name : "") : (inn.striker ? inn.striker.name : "");
        
        let html = "";
        if (in_bat) {
            const in_name = yetToBat.find(b => b.id == in_bat).name;
            html += `<option value="${in_bat}">${in_name} (Incoming)</option>`;
        }
        if (remaining_batter && remaining_name) {
            html += `<option value="${remaining_batter}">${remaining_name}</option>`;
        }
        nextStrikerSelect.innerHTML = html;
    };
    
    newBatterSelect.addEventListener("change", populateNextStrikerOptions);
    playerDismissedSelect.addEventListener("change", populateNextStrikerOptions);
    
    // Run initial population
    populateNextStrikerOptions();
    
    // Reset modal display toggles
    wicketTypeSelect.value = "bowled";
    fielderContainer.style.display = "none";
    runoutRunsContainer.style.display = "none";
    playerDismissedSelect.disabled = true;
    
    wicketModal.classList.add("show");
}

function closeWicketModal() {
    wicketModal.classList.remove("show");
}

function submitWicket() {
    if (isScoringInProgress) return;
    
    const inn = getActiveInnings();
    if (!inn) return;

    const w_type = wicketTypeSelect.value;
    const dismissed_id = parseInt(playerDismissedSelect.value);
    const f_id = parseInt(fielderSelect.value) || null;
    const new_bat_id = parseInt(newBatterSelect.value) || null;
    const next_str_id = parseInt(nextStrikerSelect.value) || null;
    const runout_runs = parseInt(runoutRunsSelect.value) || 0;
    
    // Check if new batter selected unless we are all out (no batter left)
    if (!new_bat_id && hasBatterLeft) {
        alert("Please select the incoming batter.");
        return;
    }
    
    let is_legal = 1;
    let extra_type = null;
    let runs_extras = 0;
    let runs_batter = 0;
    
    if (w_type === "run_out") {
        // Run out can happen on wide or no-ball! Let's check extra toggle
        extra_type = activeExtra;
        if (extra_type === "wide") {
            is_legal = 0;
            runs_extras = runout_runs; // runs completed off wide
        } else if (extra_type === "noball") {
            is_legal = 0;
            // assume runs off bat for run out off no ball
            runs_batter = runout_runs;
        } else {
            // standard runout completes batter runs
            runs_batter = runout_runs;
        }
    }

    closeWicketModal();
    if (!showScoringOverlay("Scoring ball...", "Please wait...")) return;

    const over_number = Math.floor(inn.balls_bowled / 6) + 1;
    const ball_of_over = (inn.balls_bowled % 6) + 1;
    const delivery_count = inn.over_balls_log.length + 1;

    // Bowler gets credit for: bowled, caught, lbw, stumped, hit wicket
    const is_bowler_wkt = ["bowled", "caught", "lbw", "stumped", "hit_wicket"].includes(w_type) ? 1 : 0;

    const reqData = {
        innings_id: inn.innings_id,
        over_number: over_number,
        ball_of_over: ball_of_over,
        delivery_count: delivery_count,
        striker_id: inn.striker ? inn.striker.id : null,
        non_striker_id: inn.non_striker ? inn.non_striker.id : null,
        bowler_id: inn.bowler ? inn.bowler.id : null,
        runs_batter: runs_batter,
        runs_extras: runs_extras,
        extra_type: extra_type,
        is_legal: is_legal,
        is_wicket: 1,
        wicket_type: w_type,
        player_dismissed_id: dismissed_id,
        fielder_id: f_id,
        new_batter_id: new_bat_id,
        next_striker_id: next_str_id,
        is_bowler_wicket: is_bowler_wkt,
        commentary: generateCommentaryText(runs_batter, runs_extras, extra_type, true, w_type, inn.striker ? inn.striker.name : "", inn.bowler ? inn.bowler.name : "", dismissed_id === (inn.striker ? inn.striker.id : null) ? (inn.striker ? inn.striker.name : "") : (inn.non_striker ? inn.non_striker.name : ""))
    };

    fetch(`/api/match/${matchId}/delivery`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(reqData)
    })
    .then(res => {
        if (!res.ok) throw new Error(`Server returned status ${res.status}`);
        return res.json();
    })
    .then(data => {
        if (data && data.error) throw new Error(data.error);
        activeExtra = null;
        extraBtns.forEach(b => b.classList.remove("selected"));
        return loadMatchState();
    })
    .then(() => {
        hideScoringOverlay();
    })
    .catch(err => {
        console.error("Error submitting wicket:", err);
        hideScoringOverlay();
        showScoringError("Unable to save wicket. Please check your connection and try again.");
    });
}

// --- BOWLER CHANGE MODAL ---

function openBowlerModal(bowlSquad, lastBowlerId) {
    let html = "";
    
    // Filter out the last bowler who cannot bowl two overs consecutively!
    let availableBowlers = bowlSquad.filter(b => b.id != lastBowlerId);
    if (availableBowlers.length === 0) {
        availableBowlers = bowlSquad; // Fallback if no other bowlers
    }
    
    availableBowlers.forEach(b => {
        html += `
            <label class="squad-checkbox-item" style="display:flex; justify-content:space-between; margin-bottom: 0.5rem;">
                <span>${b.name}</span>
                <input type="radio" name="new_bowler_radio" value="${b.id}">
            </label>
        `;
    });
    
    bowlerListContainer.innerHTML = html;
    
    // Set up radio click triggers
    const radios = document.getElementsByName("new_bowler_radio");
    radios.forEach(r => {
        r.addEventListener("change", () => {
            selectedNewBowlerId = parseInt(r.value);
            btnConfirmBowler.disabled = false;
        });
    });
    
    btnConfirmBowler.disabled = true;
    selectedNewBowlerId = null;
    bowlerModal.classList.add("show");
}

function closeBowlerModal() {
    bowlerModal.classList.remove("show");
}

// --- RENDER UI ---

function renderUI() {
    if (!matchState) return;

    // Check Match status completion
    if (matchState.status === "completed") {
        renderMatchCompleted();
        return;
    }

    const inn = getActiveInnings();
    if (!inn) return;

    // Track transitions to show career statistics popup for new batsmen/bowlers
    const prevBatsmen = [];
    if (currentStrikerId) prevBatsmen.push(currentStrikerId);
    if (currentNonStrikerId) prevBatsmen.push(currentNonStrikerId);
    const prevBowler = currentBowlerId;

    // Update active IDs
    currentStrikerId = inn.striker ? inn.striker.id : null;
    currentNonStrikerId = inn.non_striker ? inn.non_striker.id : null;
    currentBowlerId = inn.bowler ? inn.bowler.id : null;

    // Check triggers for career stats popups (broadcasting logic)
    // Keys are scoped per innings: id + "_role_inn" + inn.innings_number
    const innNum = inn.innings_number || 1;

    // 1. Striker: show when they are facing their first ball of this innings
    if (inn.striker && !shownStats.has(`${inn.striker.id}_batsman_inn${innNum}`)) {
        const strikerScore = inn.batting_scorecard.find(b => Number(b.id) === Number(inn.striker.id));
        const strikerBalls = strikerScore ? strikerScore.balls : 0;
        if (strikerBalls === 0) {
            showCareerStatsPopup(inn.striker.id, "batsman");
            shownStats.add(`${inn.striker.id}_batsman_inn${innNum}`);
        }
    }

    // 2. Non-Striker: show at start of innings or when they join the crease after a wicket
    if (inn.non_striker && !shownStats.has(`${inn.non_striker.id}_batsman_inn${innNum}`)) {
        const nsScore = inn.batting_scorecard.find(b => Number(b.id) === Number(inn.non_striker.id));
        const nsBalls = nsScore ? nsScore.balls : 0;
        if (nsBalls === 0) {
            setTimeout(() => {
                showCareerStatsPopup(inn.non_striker.id, "batsman");
            }, 350);
            shownStats.add(`${inn.non_striker.id}_batsman_inn${innNum}`);
        }
    }

    // 3. Bowler: show when they are about to bowl their very first ball of this innings
    if (inn.bowler && !shownStats.has(`${inn.bowler.id}_bowler_inn${innNum}`)) {
        const bowlerScore = inn.bowling_scorecard.find(b => Number(b.id) === Number(inn.bowler.id));
        const bowlerBalls = bowlerScore ? bowlerScore.balls : 0;
        if (bowlerBalls === 0) {
            setTimeout(() => {
                showCareerStatsPopup(inn.bowler.id, "bowler");
            }, 700);
            shownStats.add(`${inn.bowler.id}_bowler_inn${innNum}`);
        }
    }

    // 1. Check if we need to show Innings 1 -> 2 Transition
    // Transition if innings 1 is completed and current innings idx is 0
    if (inn.status === "completed" && matchState.current_innings_idx === 0) {
        renderInningsTransition();
        return;
    }

    // 2. Hide completed/transition blocks
    inningsTransitionContainer.style.display = "none";
    matchCompletedContainer.style.display = "none";
    if (creaseContainer) creaseContainer.style.display = "block";
    if (scoringConsoleCard) scoringConsoleCard.style.display = "block";

    // 3. Render Score Header details
    currentScoreText.innerText = `${inn.batting_team_name} ${inn.total_runs}/${inn.total_wickets}`;
    currentOversText.innerText = `${inn.overs} Overs`;
    
    // CRR / RRR / Target info
    const total_balls = inn.balls_bowled;
    const crr = total_balls > 0 ? ((inn.total_runs * 6) / total_balls).toFixed(2) : "0.00";
    let runRatesHtml = `CRR: <span class="bold highlight">${crr}</span>`;
    
    if (inn.innings_number === 2 && inn.target) {
        targetInfoText.style.display = "none";
        if (chaseStatusCard) {
            chaseStatusCard.style.display = "block";
            if (chaseTargetVal) chaseTargetVal.innerText = inn.target;
            
            const runs_needed = inn.target - inn.total_runs;
            if (matchState.overs_limit > 0) {
                const balls_left = Math.max(0, (matchState.overs_limit * 6) - total_balls);
                const rrr = balls_left > 0 ? ((runs_needed * 6) / balls_left).toFixed(2) : "0.00";
                
                if (chaseRequirementVal) chaseRequirementVal.innerText = `Need ${runs_needed} runs off ${balls_left} balls`;
                if (chaseRrrVal) chaseRrrVal.innerText = rrr;
            } else {
                if (chaseRequirementVal) chaseRequirementVal.innerText = `Need ${runs_needed} runs`;
                if (chaseRrrVal) chaseRrrVal.innerText = "-";
            }
        }
    } else {
        targetInfoText.style.display = "none";
        if (chaseStatusCard) chaseStatusCard.style.display = "none";
    }
    runRatesText.innerHTML = runRatesHtml;

    // 4. Render Crease Batters
    if (inn.striker) {
        scoreStrikerRow.classList.add("highlight");
        scoreStrikerName.innerHTML = `${inn.striker.name} <span class="crease-active-indicator">*</span>`;
        scoreStrikerRuns.innerText = inn.striker.runs;
        scoreStrikerBalls.innerText = inn.striker.balls;
        scoreStrikerSr.innerText = inn.striker.sr;
    } else {
        scoreStrikerRow.classList.remove("highlight");
        scoreStrikerName.innerText = "Selecting...";
        scoreStrikerRuns.innerText = "-";
        scoreStrikerBalls.innerText = "-";
        scoreStrikerSr.innerText = "-";
    }

    if (inn.non_striker) {
        scoreNonStrikerName.innerText = inn.non_striker.name;
        scoreNonStrikerRuns.innerText = inn.non_striker.runs;
        scoreNonStrikerBalls.innerText = inn.non_striker.balls;
        scoreNonStrikerSr.innerText = inn.non_striker.sr;
    } else {
        scoreNonStrikerName.innerText = "Selecting...";
        scoreNonStrikerRuns.innerText = "-";
        scoreNonStrikerBalls.innerText = "-";
        scoreNonStrikerSr.innerText = "-";
    }

    // 5. Render Bowler
    if (inn.bowler) {
        scoreBowlerRow.style.display = "flex";
        scoreBowlerName.innerText = inn.bowler.name;
        scoreBowlerOvers.innerText = inn.bowler.overs;
        scoreBowlerMaidens.innerText = inn.bowler.maidens;
        scoreBowlerRuns.innerText = inn.bowler.runs;
        scoreBowlerWickets.innerText = inn.bowler.wickets;
        scoreBowlerEcon.innerText = inn.bowler.econ;
    } else {
        // Bowler needs to be selected! Trigger Bowler Change Modal.
        scoreBowlerRow.style.display = "none";
        
        // Find squad players of bowling team
        const bowlSquad = inn.bowling_team_id === matchState.team1_id ? matchState.team1_squad : matchState.team2_squad;
        // Determine last bowler to prevent consecutive overs
        let lastBowlerId = inn.last_bowler_id || null;
        openBowlerModal(bowlSquad, lastBowlerId);
    }

    // 6. Over Ball Bubbles Log
    let bubblesHtml = "";
    inn.over_balls_log.forEach(ball => {
        let cls = "runs-123";
        if (ball === "•") cls = "dot";
        else if (ball.includes("Wd") || ball.includes("Nb") || ball.includes("B") || ball.includes("Lb")) cls = "extra";
        else if (ball === "4") cls = "four";
        else if (ball === "6") cls = "six";
        else if (ball === "W") cls = "wicket";
        bubblesHtml += `<span class="ball-bubble ${cls}">${ball}</span>`;
    });
    overBallsContainer.innerHTML = bubblesHtml || `<span class="muted">Starting over...</span>`;
}

function renderInningsTransition() {
    const inn = getActiveInnings(); // this is innings 1
    
    // Hide standard scoring UI elements
    scoreStrikerRow.classList.remove("highlight");
    scoreNonStrikerRow.classList.remove("highlight");
    scoreBowlerRow.style.display = "none";
    if (creaseContainer) creaseContainer.style.display = "none";
    if (scoringConsoleCard) scoringConsoleCard.style.display = "none";
    if (chaseStatusCard) chaseStatusCard.style.display = "none";
    
    currentScoreText.innerText = "Innings Break";
    currentOversText.innerText = `${inn.total_runs}/${inn.total_wickets} (${inn.overs} Ov)`;
    
    const target = inn.total_runs + 1;
    targetInfoText.style.display = "block";
    targetInfoText.innerHTML = `Innings 1 Completed. Target: <span class="bold highlight">${target}</span>`;
    runRatesText.innerText = "Waiting for Innings 2 crease setup...";

    // Show innings transition squad pickers
    inningsTransitionContainer.style.display = "block";
    
    // Fill selects
    // Striker & Non-Striker must be filled with Team 2 roster (since Innings 2 batting team is Innings 1 bowling team)
    const t2_squad = inn.bowling_team_id === matchState.team1_id ? matchState.team1_squad : matchState.team2_squad;
    const t1_squad = inn.batting_team_id === matchState.team1_id ? matchState.team1_squad : matchState.team2_squad;
    
    let batterHtml = `<option value="">Select batter...</option>`;
    t2_squad.forEach(p => {
        batterHtml += `<option value="${p.id}">${p.name}</option>`;
    });
    inn2StrikerSelect.innerHTML = batterHtml;
    inn2NonStrikerSelect.innerHTML = batterHtml;
    
    let bowlerHtml = `<option value="">Select bowler...</option>`;
    t1_squad.forEach(p => {
        bowlerHtml += `<option value="${p.id}">${p.name}</option>`;
    });
    inn2BowlerSelect.innerHTML = bowlerHtml;
}

function renderMatchCompleted() {
    // Hide crease panel, show completed card
    if (creaseContainer) creaseContainer.style.display = "none";
    if (scoringConsoleCard) scoringConsoleCard.style.display = "none";
    if (chaseStatusCard) chaseStatusCard.style.display = "none";
    
    currentScoreText.innerText = "Match Completed";
    currentOversText.innerText = matchState.result_margin;
    targetInfoText.style.display = "none";
    runRatesText.innerText = "";
    
    matchCompletedContainer.style.display = "block";
    matchResultText.innerText = `${matchState.result_margin.toUpperCase()}`;
    
    const awardsContainer = document.getElementById("match-awards-container");
    if (awardsContainer && matchState.awards) {
        awardsContainer.innerHTML = renderAwardsHTML(matchState.awards);
    }
}

// --- SWAP BATSMEN SHORTCUT ---
const btnSwapBatsmen = document.getElementById("btn-swap-batsmen");
if (btnSwapBatsmen) {
    btnSwapBatsmen.addEventListener("click", () => {
        if (isScoringInProgress) return;
        if (!matchState) return;
        const inn = getActiveInnings();
        if (!inn || !inn.striker || !inn.non_striker) return;
        
        showScoringOverlay("Swapping strike...", "Please wait...");
        fetch(`/api/match/${matchId}/change_batsman`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                innings_id: inn.innings_id,
                striker_id: inn.non_striker.id,
                non_striker_id: inn.striker.id
            })
        })
        .then(res => {
            if (!res.ok) throw new Error(`Server returned status ${res.status}`);
            return res.json();
        })
        .then(data => {
            if (data.success) {
                return loadMatchState();
            }
        })
        .then(() => {
            hideScoringOverlay();
        })
        .catch(err => {
            console.error("Error swapping batsmen:", err);
            hideScoringOverlay();
            showScoringError("Unable to swap batsmen. Please try again.");
        });
    });
}

// --- MANAGE SQUAD & SUBSTITUTIONS ---
if (btnManageSquad) {
    btnManageSquad.addEventListener("click", openSquadModal);
}
if (btnCloseSquad) {
    btnCloseSquad.addEventListener("click", () => {
        squadModal.classList.remove("show");
    });
}

function openSquadModal() {
    if (!matchState) return;
    const inn = getActiveInnings();
    if (!inn) return;

    const battingTeamName = inn.batting_team_id === matchState.team1_id ? matchState.team1_name : matchState.team2_name;
    const bowlingTeamName = inn.bowling_team_id === matchState.team1_id ? matchState.team1_name : matchState.team2_name;
    
    squadBattingTeamTitle.innerText = `${battingTeamName} (Batting)`;
    squadBowlingTeamTitle.innerText = `${bowlingTeamName} (Bowling)`;

    // Fetch team rosters to find eligible bench players
    Promise.all([
        fetch(`/api/team/${inn.batting_team_id}/players`).then(r => r.json()),
        fetch(`/api/team/${inn.bowling_team_id}/players`).then(r => r.json())
    ])
    .then(([batRoster, bowlRoster]) => {
        const batSquad = inn.batting_team_id === matchState.team1_id ? matchState.team1_squad : matchState.team2_squad;
        const bowlSquad = inn.bowling_team_id === matchState.team1_id ? matchState.team1_squad : matchState.team2_squad;

        const batRosterList = Array.isArray(batRoster) ? batRoster : (batRoster.players || []);
        const bowlRosterList = Array.isArray(bowlRoster) ? bowlRoster : (bowlRoster.players || []);
        renderSquadRosterList(squadBattingList, inn.batting_team_id, batSquad, batRosterList);
        renderSquadRosterList(squadBowlingList, inn.bowling_team_id, bowlSquad, bowlRosterList);
        squadModal.classList.add("show");
    })
    .catch(err => console.error("Error loading rosters:", err));
}

function renderSquadRosterList(container, teamId, matchSquad, allRoster) {
    container.innerHTML = "";
    
    const playingIds = matchSquad.map(p => p.id);
    const bench = allRoster.filter(p => !playingIds.includes(p.id));
    
    matchSquad.forEach(player => {
        const row = document.createElement("div");
        row.style.cssText = "display:flex; justify-content:space-between; align-items:center; background:rgba(255,255,255,0.02); border:1px solid var(--border-card); padding:0.5rem; border-radius:4px; margin-bottom: 0.35rem;";
        
        const nameSpan = document.createElement("span");
        nameSpan.className = "bold";
        nameSpan.style.fontSize = "0.9rem";
        nameSpan.innerText = player.name;
        row.appendChild(nameSpan);
        
        const actionDiv = document.createElement("div");
        
        const subBtn = document.createElement("button");
        subBtn.className = "btn btn-outline";
        subBtn.style.cssText = "padding:0.2rem 0.5rem; font-size:0.75rem; cursor:pointer;";
        subBtn.innerHTML = '<i class="fa-solid fa-exchange-alt"></i> Substitute';
        
        subBtn.addEventListener("click", () => {
            actionDiv.innerHTML = "";
            
            if (bench.length === 0) {
                const noBench = document.createElement("span");
                noBench.className = "muted";
                noBench.style.fontSize = "0.75rem";
                noBench.innerText = "No players on bench";
                actionDiv.appendChild(noBench);
                
                const cancelBtn = document.createElement("button");
                cancelBtn.className = "btn btn-outline";
                cancelBtn.style.cssText = "padding:0.15rem 0.4rem; font-size:0.7rem; margin-left:0.5rem; cursor:pointer;";
                cancelBtn.innerText = "Cancel";
                cancelBtn.addEventListener("click", () => {
                    actionDiv.innerHTML = "";
                    actionDiv.appendChild(subBtn);
                });
                actionDiv.appendChild(cancelBtn);
                return;
            }
            
            const select = document.createElement("select");
            select.className = "form-control";
            select.style.cssText = "padding:0.2rem 0.4rem; font-size:0.75rem; display:inline-block; width:auto; vertical-align:middle; background:var(--bg-dark);";
            
            bench.forEach(bp => {
                const opt = document.createElement("option");
                opt.value = bp.id;
                opt.innerText = bp.name;
                select.appendChild(opt);
            });
            actionDiv.appendChild(select);
            
            const confirmBtn = document.createElement("button");
            confirmBtn.className = "btn btn-primary";
            confirmBtn.style.cssText = "padding:0.2rem 0.5rem; font-size:0.75rem; margin-left:0.35rem; cursor:pointer;";
            confirmBtn.innerText = "OK";
            confirmBtn.addEventListener("click", () => {
                const incomingId = parseInt(select.value);
                if (!incomingId) return;
                
                fetch(`/api/match/${matchId}/substitute_player`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        outgoing_id: player.id,
                        incoming_id: incomingId,
                        team_id: teamId
                    })
                })
                .then(res => res.json())
                .then(data => {
                    if (data.success) {
                        loadMatchState();
                        setTimeout(openSquadModal, 200);
                    }
                })
                .catch(err => console.error("Error executing substitution:", err));
            });
            actionDiv.appendChild(confirmBtn);
            
            const cancelBtn = document.createElement("button");
            cancelBtn.className = "btn btn-outline";
            cancelBtn.style.cssText = "padding:0.2rem 0.5rem; font-size:0.75rem; margin-left:0.25rem; cursor:pointer;";
            cancelBtn.innerText = "X";
            cancelBtn.addEventListener("click", () => {
                actionDiv.innerHTML = "";
                actionDiv.appendChild(subBtn);
            });
            actionDiv.appendChild(cancelBtn);
        });
        
        actionDiv.appendChild(subBtn);
        row.appendChild(actionDiv);
        container.appendChild(row);
    });
}

function showCareerStatsPopup(playerId, type) {
    if (!playerId) return;
    
    fetch(`/api/player/${playerId}/profile`)
    .then(res => res.json())
    .then(p => {
        if (!p || !p.info) return;
        
        const container = document.getElementById("career-stats-toast-container");
        if (!container) return;
        
        const toast = document.createElement("div");
        toast.className = "career-toast premium-card";
        toast.style.cssText = "width: 320px; display: flex; flex-direction: column; gap: 0.75rem; border-left: 4px solid var(--accent-emerald); animation: slideIn 0.3s ease-out; pointer-events: auto; position: relative; overflow: hidden; background: rgba(15, 23, 42, 0.95); backdrop-filter: blur(10px); padding: 1rem; border-radius: var(--radius-md); margin-top: 0.5rem;";
        
        let color = "var(--accent-emerald)";
        let role = "Batsman";
        let statsHtml = "";
        
        if (type === "batsman") {
            toast.style.borderLeftColor = "var(--accent-emerald)";
            color = "var(--accent-emerald)";
            role = "Batsman";
            statsHtml = `
                <div style="display: grid; grid-template-columns: repeat(3, 1fr); text-align: center; gap: 0.5rem; background: rgba(255,255,255,0.02); padding: 0.5rem; border-radius: 4px; font-size: 0.8rem;">
                    <div>
                        <div style="color: var(--text-secondary); font-size: 0.7rem;">Matches</div>
                        <div class="bold" style="color: var(--text-primary); font-size: 0.9rem; margin-top: 0.15rem;">${p.batting.matches}</div>
                    </div>
                    <div>
                        <div style="color: var(--text-secondary); font-size: 0.7rem;">Runs</div>
                        <div class="bold" style="color: var(--text-primary); font-size: 0.9rem; margin-top: 0.15rem;">${p.batting.runs}</div>
                    </div>
                    <div>
                        <div style="color: var(--text-secondary); font-size: 0.7rem;">Avg</div>
                        <div class="bold" style="color: var(--text-primary); font-size: 0.9rem; margin-top: 0.15rem;">${p.batting.average}</div>
                    </div>
                    <div>
                        <div style="color: var(--text-secondary); font-size: 0.7rem;">SR</div>
                        <div class="bold" style="color: var(--text-primary); font-size: 0.9rem; margin-top: 0.15rem;">${p.batting.strike_rate}</div>
                    </div>
                    <div>
                        <div style="color: var(--text-secondary); font-size: 0.7rem;">HS</div>
                        <div class="bold" style="color: var(--text-primary); font-size: 0.9rem; margin-top: 0.15rem;">${p.batting.high_score}</div>
                    </div>
                    <div>
                        <div style="color: var(--text-secondary); font-size: 0.7rem;">50s/100s</div>
                        <div class="bold" style="color: var(--text-primary); font-size: 0.9rem; margin-top: 0.15rem;">${p.batting.fifties}/${p.batting.hundreds}</div>
                    </div>
                </div>
            `;
        } else {
            toast.style.borderLeftColor = "var(--accent-indigo)";
            color = "var(--accent-indigo)";
            role = "Bowler";
            statsHtml = `
                <div style="display: grid; grid-template-columns: repeat(3, 1fr); text-align: center; gap: 0.5rem; background: rgba(255,255,255,0.02); padding: 0.5rem; border-radius: 4px; font-size: 0.8rem;">
                    <div>
                        <div style="color: var(--text-secondary); font-size: 0.7rem;">Innings</div>
                        <div class="bold" style="color: var(--text-primary); font-size: 0.9rem; margin-top: 0.15rem;">${p.bowling.innings}</div>
                    </div>
                    <div>
                        <div style="color: var(--text-secondary); font-size: 0.7rem;">Wkts</div>
                        <div class="bold" style="color: var(--text-primary); font-size: 0.9rem; margin-top: 0.15rem;">${p.bowling.wickets}</div>
                    </div>
                    <div>
                        <div style="color: var(--text-secondary); font-size: 0.7rem;">Econ</div>
                        <div class="bold" style="color: var(--text-primary); font-size: 0.9rem; margin-top: 0.15rem;">${p.bowling.economy}</div>
                    </div>
                    <div>
                        <div style="color: var(--text-secondary); font-size: 0.7rem;">Avg</div>
                        <div class="bold" style="color: var(--text-primary); font-size: 0.9rem; margin-top: 0.15rem;">${p.bowling.average}</div>
                    </div>
                    <div>
                        <div style="color: var(--text-secondary); font-size: 0.7rem;">Best</div>
                        <div class="bold" style="color: var(--text-primary); font-size: 0.9rem; margin-top: 0.15rem;">${p.bowling.best_bowling}</div>
                    </div>
                    <div>
                        <div style="color: var(--text-secondary); font-size: 0.7rem;">3w/5w</div>
                        <div class="bold" style="color: var(--text-primary); font-size: 0.9rem; margin-top: 0.15rem;">${p.bowling.three_wickets}/${p.bowling.five_wickets}</div>
                    </div>
                </div>
            `;
        }
        
        const avatarUrl = p.info.avatar_url || 'https://cdn-icons-png.flaticon.com/512/21/21104.png';
        toast.innerHTML = `
            <div style="display: flex; gap: 0.75rem; align-items: center;">
                <img src="${avatarUrl}" style="width: 2.25rem; height: 2.25rem; border-radius: 50%; border: 1px solid ${color};" onerror="this.src='https://cdn-icons-png.flaticon.com/512/21/21104.png'">
                <div>
                    <h4 style="margin: 0; font-size: 0.9rem; color: var(--text-primary); font-weight: 700;">${p.info.name}</h4>
                    <span class="muted" style="font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.5px; color: ${color}; font-weight: 600;">${role} Career Stats</span>
                </div>
            </div>
            ${statsHtml}
            <div style="position: absolute; bottom: 0; left: 0; height: 3px; background: ${color}; animation: progressTimer 10s linear forwards; width: 100%;"></div>
        `;
        
        container.appendChild(toast);
        
        setTimeout(() => {
            toast.style.animation = "slideOut 0.3s ease-in forwards";
            setTimeout(() => {
                toast.remove();
            }, 300);
        }, 9700);
    })
    .catch(err => console.error("Error loading career stats popup:", err));
}

function renderAwardsHTML(awards) {
    if (!awards) {
        return `<p class="muted" style="text-align:center;">No awards details available.</p>`;
    }
    
    let html = ``;
    
    // 1. Man of the Match Section
    if (awards.man_of_the_match && awards.man_of_the_match.length > 0) {
        const title = awards.man_of_the_match.length > 1 ? "🏆 JOINT MAN OF THE MATCH" : "🏆 MAN OF THE MATCH";
        html += `
            <div style="background: rgba(212, 175, 55, 0.05); border: 1px solid var(--accent-gold); padding: 1.25rem; border-radius: var(--radius-md); margin-bottom: 1.5rem;">
                <h4 style="margin:0 0 0.5rem 0; font-size:1.1rem; color:var(--accent-gold); font-weight:800; text-transform:uppercase; letter-spacing:0.5px;">${title}</h4>
        `;
        awards.man_of_the_match.forEach(motm => {
            html += `
                <div style="margin-bottom:0.75rem; border-bottom:1px solid rgba(212, 175, 55, 0.1); padding-bottom:0.75rem; last-child { border:none; margin:0; }">
                    <h3 style="margin:0; font-size:1.4rem; font-weight:800; color:var(--text-primary);">${motm.name}</h3>
                    <div style="font-size:0.9rem; color:var(--accent-gold); font-weight:700; margin-top:0.25rem;">Cricket Impact Rating: ${motm.total_impact} Points</div>
                    <div style="font-size:0.85rem; color:var(--text-secondary); margin-top:0.25rem; font-style:italic;">Why: ${motm.why}</div>
                </div>
            `;
        });
        html += `</div>`;
    }
    
    // 2. Specialty Awards Grid
    html += `<div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap:1rem; margin-bottom:1.5rem;">`;
    
    // Best Batter
    if (awards.best_batter) {
        const bb = awards.best_batter;
        html += `
            <div class="premium-card" style="margin:0; padding:1rem; border-color: rgba(255,255,255,0.05);">
                <div style="display:flex; align-items:center; gap:0.5rem; color:var(--accent-emerald); font-weight:700; font-size:0.9rem; text-transform:uppercase; letter-spacing:0.5px; margin-bottom:0.5rem;">
                    🏏 Best Batter
                </div>
                <h4 style="margin:0 0 0.25rem 0; font-size:1.15rem; font-weight:800;">${bb.name}</h4>
                <div style="font-size:0.85rem; line-height:1.5; color:var(--text-secondary);">
                    <div>Runs: <span class="bold text-primary">${bb.batting_runs}</span> (${bb.batting_balls} balls)</div>
                    <div>Boundaries: ${bb.batting_fours}x4, ${bb.batting_sixes}x6</div>
                    <div>Strike Rate: ${bb.batting_balls > 0 ? ((bb.batting_runs*100)/bb.batting_balls).toFixed(1) : '0.0'}</div>
                    <div class="bold" style="color:var(--accent-emerald); margin-top:0.25rem;">Batting Impact: ${bb.batting_impact}</div>
                </div>
            </div>
        `;
    }
    
    // Best Bowler
    if (awards.best_bowler) {
        const bb = awards.best_bowler;
        const oversStr = `${Math.floor(bb.bowling_balls/6)}.${bb.bowling_balls%6}`;
        const econ = bb.bowling_balls > 0 ? (bb.bowling_runs*6.0/bb.bowling_balls).toFixed(2) : '0.00';
        html += `
            <div class="premium-card" style="margin:0; padding:1rem; border-color: rgba(255,255,255,0.05);">
                <div style="display:flex; align-items:center; gap:0.5rem; color:var(--accent-indigo); font-weight:700; font-size:0.9rem; text-transform:uppercase; letter-spacing:0.5px; margin-bottom:0.5rem;">
                    🎯 Best Bowler
                </div>
                <h4 style="margin:0 0 0.25rem 0; font-size:1.15rem; font-weight:800;">${bb.name}</h4>
                <div style="font-size:0.85rem; line-height:1.5; color:var(--text-secondary);">
                    <div>Wickets: <span class="bold text-primary">${bb.bowling_wickets}</span> (${oversStr} overs)</div>
                    <div>Runs Conceded: ${bb.bowling_runs}</div>
                    <div>Economy: ${econ}</div>
                    <div class="bold" style="color:var(--accent-indigo); margin-top:0.25rem;">Bowling Impact: ${bb.bowling_impact}</div>
                </div>
            </div>
        `;
    }
    
    // Best Fielder
    if (awards.best_fielder) {
        const bf = awards.best_fielder;
        html += `
            <div class="premium-card" style="margin:0; padding:1rem; border-color: rgba(255,255,255,0.05);">
                <div style="display:flex; align-items:center; gap:0.5rem; color:var(--accent-gold); font-weight:700; font-size:0.9rem; text-transform:uppercase; letter-spacing:0.5px; margin-bottom:0.5rem;">
                    🧤 Best Fielder
                </div>
                <h4 style="margin:0 0 0.25rem 0; font-size:1.15rem; font-weight:800;">${bf.name}</h4>
                <div style="font-size:0.85rem; line-height:1.5; color:var(--text-secondary);">
                    <div>Catches: <span class="bold text-primary">${bf.fielding_catches}</span></div>
                    <div>Stumpings: ${bf.fielding_stumpings}</div>
                    <div>Run Outs: ${bf.fielding_run_outs}</div>
                    <div class="bold" style="color:var(--accent-gold); margin-top:0.25rem;">Fielding Impact: ${bf.fielding_impact}</div>
                </div>
            </div>
        `;
    }
    
    html += `</div>`;
    
    // 3. Performance ratings table
    if (awards.performance_table && awards.performance_table.length > 0) {
        html += `
            <div class="premium-card" style="margin:0; padding:1rem; border-color: rgba(255,255,255,0.05); overflow-x:auto;">
                <h3 class="card-title" style="font-size: 1rem; border-bottom:none; margin-bottom:0.75rem;"><i class="fa-solid fa-list highlight"></i> Cricket Impact Rating Leaderboard</h3>
                <table class="table" style="width:100%; border-collapse:collapse; text-align:left; font-size:0.85rem;">
                    <thead>
                        <tr style="border-bottom: 1px solid var(--border-card);">
                            <th style="padding:0.5rem;">PLAYER</th>
                            <th style="padding:0.5rem; text-align:center;">BATTING</th>
                            <th style="padding:0.5rem; text-align:center;">BOWLING</th>
                            <th style="padding:0.5rem; text-align:center;">FIELDING</th>
                            <th style="padding:0.5rem; text-align:center;">SITUATION</th>
                            <th style="padding:0.5rem; text-align:center;" class="bold highlight">TOTAL</th>
                        </tr>
                    </thead>
                    <tbody>
        `;
        
        // Render rows
        awards.performance_table.forEach(p => {
            html += `
                <tr style="border-bottom: 1px solid rgba(255,255,255,0.02);">
                    <td style="padding:0.5rem;" class="bold">${p.name}</td>
                    <td style="padding:0.5rem; text-align:center;">${p.batting_impact}</td>
                    <td style="padding:0.5rem; text-align:center;">${p.bowling_impact}</td>
                    <td style="padding:0.5rem; text-align:center;">${p.fielding_impact}</td>
                    <td style="padding:0.5rem; text-align:center;">${p.situation_impact}</td>
                    <td style="padding:0.5rem; text-align:center;" class="bold highlight">${p.total_impact}</td>
                </tr>
            `;
        });
        
        html += `
                    </tbody>
                </table>
            </div>
        `;
    }
    
    return html;
}

// --- END MATCH CONTROLS ---
const btnEndMatch = document.getElementById("btn-end-match");
const endMatchModal = document.getElementById("end-match-modal");
const endMatchStatusSelect = document.getElementById("end-match-status-select");
const endMatchCustomFields = document.getElementById("end-match-custom-fields");
const endMatchWinnerSelect = document.getElementById("end-match-winner-select");
const endMatchMarginInput = document.getElementById("end-match-margin-input");

if (btnEndMatch) {
    btnEndMatch.addEventListener("click", openEndMatchModal);
}

function openEndMatchModal() {
    if (!matchState) return;
    
    // Populate winner dropdown
    if (endMatchWinnerSelect) {
        endMatchWinnerSelect.innerHTML = `
            <option value="${matchState.team1_id}">${matchState.team1_name}</option>
            <option value="${matchState.team2_id}">${matchState.team2_name}</option>
            <option value="none">No Winner (Tie / No Result)</option>
        `;
    }

    if (endMatchStatusSelect) endMatchStatusSelect.value = "completed";
    if (endMatchCustomFields) endMatchCustomFields.style.display = "none";
    if (endMatchMarginInput) endMatchMarginInput.value = "";
    if (endMatchModal) endMatchModal.classList.add("show");
}

function closeEndMatchModal() {
    if (endMatchModal) endMatchModal.classList.remove("show");
}

function toggleEndMatchCustomFields() {
    if (!endMatchStatusSelect) return;
    const val = endMatchStatusSelect.value;
    if (endMatchCustomFields) {
        endMatchCustomFields.style.display = (val === 'custom') ? 'block' : 'none';
    }
}

function submitEndMatch() {
    if (!matchState) return;
    const outcomeType = endMatchStatusSelect ? endMatchStatusSelect.value : 'completed';
    const winnerId = endMatchWinnerSelect ? endMatchWinnerSelect.value : null;
    const margin = endMatchMarginInput ? endMatchMarginInput.value : '';

    showScoringOverlay("Concluding match...", "Finalizing scorecard & awards...");
    closeEndMatchModal();

    fetch(`/api/match/${matchId}/end_match`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            outcome_type: outcomeType,
            winner_id: winnerId,
            result_margin: margin
        })
    })
    .then(r => r.json())
    .then(data => {
        hideScoringOverlay();
        if (data.success) {
            fetchMatchState();
        } else {
            alert(data.error || "Failed to end match.");
        }
    })
    .catch(err => {
        hideScoringOverlay();
        console.error("Error ending match:", err);
        alert("An error occurred while trying to end the match.");
    });
}
