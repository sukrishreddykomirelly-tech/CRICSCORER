// live.js

let eventSource = null;
let currentStrikerId = null;
let currentNonStrikerId = null;
let currentBowlerId = null;
const shownStats = new Set();

// Tab selectors
const tabBtns = document.querySelectorAll(".tab-btn");
const tabContents = document.querySelectorAll(".tab-content");

document.addEventListener("DOMContentLoaded", () => {
    setupTabSwitching();
    startLiveStream();
});

function setupTabSwitching() {
    tabBtns.forEach(btn => {
        btn.addEventListener("click", () => {
            const target = btn.getAttribute("data-tab");
            
            tabBtns.forEach(b => b.classList.remove("active"));
            tabContents.forEach(c => c.classList.remove("active"));
            
            btn.classList.add("active");
            document.getElementById(`tab-${target}`).classList.add("active");
        });
    });
}

function startLiveStream() {
    if (eventSource) {
        eventSource.close();
    }
    
    // Connect to Flask SSE live stream
    eventSource = new EventSource(`/api/match/${matchId}/live_stream`);
    
    eventSource.onmessage = (event) => {
        const state = JSON.parse(event.data);
        updateLiveUI(state);
    };
    
    eventSource.onerror = (err) => {
        console.error("SSE Connection failed, falling back to REST polling:", err);
        // Fallback polling every 5s if SSE disconnects
        setTimeout(pollMatchState, 5000);
    };
}

function pollMatchState() {
    fetch(`/api/match/${matchId}/state`)
        .then(res => res.json())
        .then(state => {
            updateLiveUI(state);
            // schedule next poll
            if (state.status === "live") {
                setTimeout(pollMatchState, 5000);
            }
        })
        .catch(err => console.error("Polling error:", err));
}

function updateLiveUI(state) {
    if (!state) return;

    // 1. Update Match Header Info
    document.getElementById("view-match-format").innerText = state.match_format;
    document.getElementById("view-match-ground").innerText = state.ground || "Unknown Ground";
    document.getElementById("view-match-date").innerText = `${state.match_date} @ ${state.match_time}`;
    
    // Status Badge
    const badge = document.getElementById("view-match-status");
    badge.innerText = state.status.replace('_', ' ').toUpperCase();
    badge.className = "match-card-badge"; // reset
    if (state.status === "live") {
        badge.classList.add("badge-live");
    } else if (state.status === "completed") {
        badge.classList.add("badge-completed");
    } else {
        badge.classList.add("badge-completed"); // e.g. toss_done, scheduled
    }

    // Toss Details
    const tossText = document.getElementById("view-toss-details");
    if (state.toss_winner_id) {
        const tossWinnerName = state.toss_winner_id === state.team1_id ? state.team1_name : state.team2_name;
        tossText.innerHTML = `Toss: <span class="bold highlight">${tossWinnerName}</span> won and elected to <span class="bold highlight">${state.toss_decision}</span> first.`;
    } else {
        tossText.innerText = "Toss yet to be conducted.";
    }

    // Result Text
    const resultText = document.getElementById("view-match-result");
    if (state.status === "completed" && state.result_margin) {
        resultText.style.display = "block";
        resultText.innerText = state.result_margin.toUpperCase();
    } else {
        resultText.style.display = "none";
    }

    // Active Innings details
    const inn = state.current_innings_idx !== -1 ? state.innings[state.current_innings_idx] : null;
    
    // Hide/Show Active crease panel
    const livePanel = document.getElementById("view-live-panel");
    if (inn && state.status === "live") {
        livePanel.style.display = "block";
        
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
        // 1. Striker: show when they are facing their first ball
        if (inn.striker && !shownStats.has(inn.striker.id + "_batsman")) {
            const strikerScore = inn.batting_scorecard.find(b => Number(b.id) === Number(inn.striker.id));
            const strikerBalls = strikerScore ? strikerScore.balls : 0;
            if (strikerBalls === 0) {
                showCareerStatsPopup(inn.striker.id, "batsman");
                shownStats.add(inn.striker.id + "_batsman");
            }
        }

        // 2. Non-Striker: show immediately when they join after a wicket (meaning inn.balls_bowled > 0 and they are new to the crease)
        if (inn.non_striker && !shownStats.has(inn.non_striker.id + "_batsman")) {
            const nsScore = inn.batting_scorecard.find(b => Number(b.id) === Number(inn.non_striker.id));
            const nsBalls = nsScore ? nsScore.balls : 0;
            if (nsBalls === 0 && inn.balls_bowled > 0 && !prevBatsmen.includes(inn.non_striker.id)) {
                showCareerStatsPopup(inn.non_striker.id, "batsman");
                shownStats.add(inn.non_striker.id + "_batsman");
            }
        }

        // 3. Bowler: show when they are about to bowl their very first ball of the match
        if (inn.bowler && !shownStats.has(inn.bowler.id + "_bowler")) {
            const bowlerScore = inn.bowling_scorecard.find(b => Number(b.id) === Number(inn.bowler.id));
            const bowlerBalls = bowlerScore ? bowlerScore.balls : 0;
            if (bowlerBalls === 0) {
                showCareerStatsPopup(inn.bowler.id, "bowler");
                shownStats.add(inn.bowler.id + "_bowler");
            }
        }
        
        // Render Active Score
        document.getElementById("view-live-team").innerText = inn.batting_team_name;
        document.getElementById("view-live-score").innerText = `${inn.total_runs}/${inn.total_wickets}`;
        document.getElementById("view-live-overs").innerText = `(${inn.overs} overs)`;
        
        // Target / RRR Info
        const targetRow = document.getElementById("view-target-row");
        const viewChaseStatusCard = document.getElementById("view-chase-status-card");
        const viewChaseTargetVal = document.getElementById("view-chase-target-val");
        const viewChaseRequirementVal = document.getElementById("view-chase-requirement-val");
        const viewChaseRrrVal = document.getElementById("view-chase-rrr-val");

        if (inn.innings_number === 2 && inn.target) {
            targetRow.style.display = "none";
            if (viewChaseStatusCard) {
                viewChaseStatusCard.style.display = "block";
                if (viewChaseTargetVal) viewChaseTargetVal.innerText = inn.target;
                
                const runs_needed = inn.target - inn.total_runs;
                if (state.overs_limit > 0) {
                    const balls_left = Math.max(0, (state.overs_limit * 6) - inn.balls_bowled);
                    const rrr = balls_left > 0 ? ((runs_needed * 6) / balls_left).toFixed(2) : "0.00";
                    
                    if (viewChaseRequirementVal) viewChaseRequirementVal.innerText = `Need ${runs_needed} runs off ${balls_left} balls`;
                    if (viewChaseRrrVal) viewChaseRrrVal.innerText = rrr;
                } else {
                    if (viewChaseRequirementVal) viewChaseRequirementVal.innerText = `Need ${runs_needed} runs`;
                    if (viewChaseRrrVal) viewChaseRrrVal.innerText = "-";
                }
            }
        } else {
            targetRow.style.display = "none";
            if (viewChaseStatusCard) viewChaseStatusCard.style.display = "none";
        }
        
        // CRR Info
        const crr = inn.balls_bowled > 0 ? ((inn.total_runs * 6) / inn.balls_bowled).toFixed(2) : "0.00";
        document.getElementById("view-live-crr").innerText = `CRR: ${crr}`;

        // Render Crease Batters
        if (inn.striker) {
            document.getElementById("view-striker-row").classList.add("highlight");
            document.getElementById("view-striker-name").innerHTML = `${inn.striker.name} <span class="crease-active-indicator">*</span>`;
            document.getElementById("view-striker-runs").innerText = inn.striker.runs;
            document.getElementById("view-striker-balls").innerText = inn.striker.balls;
            document.getElementById("view-striker-fours").innerText = inn.striker.fours;
            document.getElementById("view-striker-sixes").innerText = inn.striker.sixes;
            document.getElementById("view-striker-sr").innerText = inn.striker.sr;
        } else {
            document.getElementById("view-striker-row").classList.remove("highlight");
            document.getElementById("view-striker-name").innerText = "-";
            document.getElementById("view-striker-runs").innerText = "0";
            document.getElementById("view-striker-balls").innerText = "0";
            document.getElementById("view-striker-fours").innerText = "0";
            document.getElementById("view-striker-sixes").innerText = "0";
            document.getElementById("view-striker-sr").innerText = "0.0";
        }

        if (inn.non_striker) {
            document.getElementById("view-nonstriker-name").innerText = inn.non_striker.name;
            document.getElementById("view-nonstriker-runs").innerText = inn.non_striker.runs;
            document.getElementById("view-nonstriker-balls").innerText = inn.non_striker.balls;
            document.getElementById("view-nonstriker-fours").innerText = inn.non_striker.fours;
            document.getElementById("view-nonstriker-sixes").innerText = inn.non_striker.sixes;
            document.getElementById("view-nonstriker-sr").innerText = inn.non_striker.sr;
        } else {
            document.getElementById("view-nonstriker-name").innerText = "-";
            document.getElementById("view-nonstriker-runs").innerText = "0";
            document.getElementById("view-nonstriker-balls").innerText = "0";
            document.getElementById("view-nonstriker-fours").innerText = "0";
            document.getElementById("view-nonstriker-sixes").innerText = "0";
            document.getElementById("view-nonstriker-sr").innerText = "0.0";
        }

        // Render Crease Bowler
        if (inn.bowler) {
            document.getElementById("view-bowler-row").style.display = "flex";
            document.getElementById("view-bowler-name").innerText = inn.bowler.name;
            document.getElementById("view-bowler-overs").innerText = inn.bowler.overs;
            document.getElementById("view-bowler-maidens").innerText = inn.bowler.maidens;
            document.getElementById("view-bowler-runs").innerText = inn.bowler.runs;
            document.getElementById("view-bowler-wickets").innerText = inn.bowler.wickets;
            document.getElementById("view-bowler-econ").innerText = inn.bowler.econ;
        } else {
            document.getElementById("view-bowler-row").style.display = "none";
        }

        // Over Bubbles
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
        document.getElementById("view-over-balls").innerHTML = bubblesHtml || `<span class="muted">Starting over...</span>`;
    } else {
        livePanel.style.display = "none";
    }

    // 2. Render Scorecard Tab
    renderScorecardTab(state);

    // 3. Render Commentary Tab
    renderCommentaryTab(state);

    // 4. Render Partnerships Tab
    renderPartnershipsTab(state);

    // 5. Render Analytics Tab (Worm & Manhattan)
    renderAnalyticsTab(state);

    // 6. Render Awards & Impact Tab
    renderAwardsTab(state);
}

function renderScorecardTab(state) {
    const container = document.getElementById("tab-scorecard");
    let html = "";
    
    if (state.innings.length === 0) {
        container.innerHTML = `<p class="muted" style="text-align:center; padding: 2rem;">No scorecards available yet.</p>`;
        return;
    }
    
    state.innings.forEach(inn => {
        html += `
            <div class="premium-card" style="margin-bottom: 2rem;">
                <h3 class="card-title" style="display:flex; justify-content:space-between;">
                    <span>${inn.batting_team_name} Innings</span>
                    <span>${inn.total_runs}/${inn.total_wickets} (${inn.overs} Ov)</span>
                </h3>
                
                <div class="table-responsive">
                    <table class="scorecard-table">
                        <thead>
                            <tr>
                                <th>Batter</th>
                                <th>Dismissal</th>
                                <th class="num">R</th>
                                <th class="num">B</th>
                                <th class="num">4s</th>
                                <th class="num">6s</th>
                                <th class="num">SR</th>
                            </tr>
                        </thead>
                        <tbody>
        `;
        
        inn.batting_scorecard.forEach(b => {
            html += `
                <tr>
                    <td class="bold">${b.name}</td>
                    <td class="muted">${b.dismissal}</td>
                    <td class="num bold">${b.runs}</td>
                    <td class="num">${b.balls}</td>
                    <td class="num">${b.fours}</td>
                    <td class="num">${b.sixes}</td>
                    <td class="num">${b.sr}</td>
                </tr>
            `;
        });
        
        // Extras
        const ext_str = `Wd: ${inn.wides}, Nb: ${inn.noballs}, B: ${inn.byes}, Lb: ${inn.legbyes}`;
        const total_extras = inn.wides + inn.noballs + inn.byes + inn.legbyes;
        html += `
            <tr class="extras-row">
                <td colspan="2">Extras</td>
                <td class="num bold">${total_extras}</td>
                <td colspan="4" class="muted" style="text-align:left; font-size: 0.8rem; padding-left: 1rem;">(${ext_str})</td>
            </tr>
            <tr class="total-row">
                <td colspan="2">Total</td>
                <td class="num bold highlight">${inn.total_runs}</td>
                <td colspan="4" class="muted" style="text-align:left; padding-left: 1rem;">(${inn.total_wickets} Wickets, ${inn.overs} Overs)</td>
            </tr>
        `;
        
        html += `
                        </tbody>
                    </table>
                </div>
                
                <h4 style="margin: 1.5rem 0 0.5rem 0; font-size: 1rem; color: var(--text-secondary);">Bowling</h4>
                <div class="table-responsive">
                    <table class="scorecard-table">
                        <thead>
                            <tr>
                                <th>Bowler</th>
                                <th class="num">O</th>
                                <th class="num">M</th>
                                <th class="num">R</th>
                                <th class="num">W</th>
                                <th class="num">Econ</th>
                                <th class="num">Wd/Nb</th>
                            </tr>
                        </thead>
                        <tbody>
        `;
        
        inn.bowling_scorecard.forEach(bowler => {
            html += `
                <tr>
                    <td class="bold">${bowler.name}</td>
                    <td class="num bold">${bowler.overs}</td>
                    <td class="num">${bowler.maidens}</td>
                    <td class="num">${bowler.runs}</td>
                    <td class="num bold highlight">${bowler.wickets}</td>
                    <td class="num">${bowler.econ}</td>
                    <td class="num">${bowler.wides}/${bowler.noballs}</td>
                </tr>
            `;
        });
        
        html += `
                        </tbody>
                    </table>
                </div>
        `;
        
        // Fall of Wickets
        if (inn.fall_of_wickets && inn.fall_of_wickets.length > 0) {
            html += `
                <h4 style="margin: 1.5rem 0 0.5rem 0; font-size: 1rem; color: var(--text-secondary);">Fall of Wickets</h4>
                <p class="muted" style="font-size: 0.88rem; line-height: 1.6;">
            `;
            const fows = inn.fall_of_wickets.map(f => {
                const b_name = state.team1_squad.find(p => p.id == f.batsman_id)?.name || state.team2_squad.find(p => p.id == f.batsman_id)?.name || `Player ${f.batsman_id}`;
                return `<span class="bold">${f.score}/${f.wicket_num}</span> (${b_name}, ${f.overs} Ov)`;
            });
            html += fows.join(", ");
            html += `</p>`;
        }
        
        html += `</div>`;
    });
    
    container.innerHTML = html;
}

function renderCommentaryTab(state) {
    const container = document.getElementById("tab-commentary");
    
    // Combine commentary from all innings
    let html = `<div class="commentary-list">`;
    let count = 0;
    
    [...state.innings].reverse().forEach(inn => {
        inn.commentary.forEach(item => {
            count++;
            const is_w = item.is_wicket ? "wicket-comment" : "";
            html += `
                <div class="commentary-item ${is_w}">
                    <div class="commentary-over">${item.overs}</div>
                    <div class="commentary-desc">${item.event}</div>
                </div>
            `;
        });
    });
    
    html += `</div>`;
    
    if (count === 0) {
        container.innerHTML = `<p class="muted" style="text-align:center; padding: 2rem;">No commentary available yet.</p>`;
    } else {
        container.innerHTML = html;
    }
}

function renderPartnershipsTab(state) {
    const container = document.getElementById("tab-partnerships");
    let html = "";
    let count = 0;
    
    state.innings.forEach(inn => {
        if (inn.partnerships && inn.partnerships.length > 0) {
            html += `<h3 style="margin-top: 1rem; margin-bottom: 0.75rem; font-size: 1.1rem; border-bottom: 1px solid var(--border-card); padding-bottom: 0.25rem;">${inn.batting_team_name} Partnerships</h3>`;
            html += `<div class="partnership-list">`;
            
            inn.partnerships.forEach(p => {
                count++;
                const b1_name = state.team1_squad.find(p_sq => p_sq.id == p.batter1_id)?.name || state.team2_squad.find(p_sq => p_sq.id == p.batter1_id)?.name || `Player ${p.batter1_id}`;
                const b2_name = state.team1_squad.find(p_sq => p_sq.id == p.batter2_id)?.name || state.team2_squad.find(p_sq => p_sq.id == p.batter2_id)?.name || `Player ${p.batter2_id}`;
                
                html += `
                    <div class="partnership-card">
                        <div class="partnership-players">
                            <span class="bold">${b1_name}</span>
                            <span class="highlight bold">${p.runs} runs (${p.balls} balls)</span>
                            <span class="bold">${b2_name}</span>
                        </div>
                        <div class="partnership-bar-container">
                            <div class="partnership-bar-filled" style="width: 100%;"></div>
                        </div>
                    </div>
                `;
            });
            
            html += `</div>`;
        }
    });
    
    if (count === 0) {
        container.innerHTML = `<p class="muted" style="text-align:center; padding: 2rem;">No partnership data available yet.</p>`;
    } else {
        container.innerHTML = html;
    }
}

let wormChartInstance = null;
let manhattanChartInstance = null;

function renderAnalyticsTab(state) {
    if (!state.innings || state.innings.length === 0) {
        return;
    }
    
    // --- 1. WORM CHART DATA GENERATION ---
    const wormDatasets = [];
    
    state.innings.forEach(inn => {
        const points = [{x: 0, y: 0}];
        let cum_runs = 0;
        let legal_balls = 0;
        
        // Commentary is in reverse chronological order, so reverse it to get chronological sequence
        const chronological = [...inn.commentary].reverse();
        
        chronological.forEach(c => {
            cum_runs += c.runs;
            if (c.extra_type !== "wide" && c.extra_type !== "noball") {
                legal_balls++;
            }
            
            const over_val = legal_balls / 6.0;
            points.push({x: over_val, y: cum_runs});
        });
        
        const is_inn1 = inn.innings_number === 1;
        const color = is_inn1 ? '#10b981' : '#6366f1';
        
        wormDatasets.push({
            label: `${inn.batting_team_name} (Inn ${inn.innings_number})`,
            data: points,
            borderColor: color,
            backgroundColor: color + '20', // transparent fill
            borderWidth: 3,
            pointRadius: points.length < 50 ? 3 : 0, 
            pointHoverRadius: 5,
            fill: false,
            tension: 0.1
        });
    });
    
    // Render Worm Chart
    const wormCtx = document.getElementById('wormChart');
    if (wormCtx) {
        if (wormChartInstance) {
            wormChartInstance.destroy();
        }
        
        wormChartInstance = new Chart(wormCtx, {
            type: 'line',
            data: {
                datasets: wormDatasets
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    x: {
                        type: 'linear',
                        title: {
                            display: true,
                            text: 'Overs Bowled',
                            color: '#a0aec0'
                        },
                        ticks: {
                            color: '#a0aec0',
                            callback: function(value) {
                                const completed = Math.floor(value);
                                const fraction = Math.round((value - completed) * 6);
                                if (fraction === 0) return completed.toString();
                                return `${completed}.${fraction}`;
                            }
                        },
                        grid: {
                            color: 'rgba(255, 255, 255, 0.05)'
                        }
                    },
                    y: {
                        title: {
                            display: true,
                            text: 'Cumulative Runs',
                            color: '#a0aec0'
                        },
                        ticks: {
                            color: '#a0aec0'
                        },
                        grid: {
                            color: 'rgba(255, 255, 255, 0.05)'
                        }
                    }
                },
                plugins: {
                    legend: {
                        labels: {
                            color: '#a0aec0'
                        }
                    },
                    tooltip: {
                        callbacks: {
                            label: function(context) {
                                const y = context.parsed.y;
                                const x = context.parsed.x;
                                const completed = Math.floor(x);
                                const fraction = Math.round((x - completed) * 6);
                                const over_str = fraction === 0 ? `${completed}.0` : `${completed}.${fraction}`;
                                return `${context.dataset.label}: ${y} runs (${over_str} ov)`;
                            }
                        }
                    }
                }
            }
        });
    }
    
    // --- 2. MANHATTAN CHART DATA GENERATION ---
    let max_overs = 1;
    state.innings.forEach(inn => {
        const chronological = [...inn.commentary].reverse();
        chronological.forEach(c => {
            const over_idx = parseInt(c.overs.split('.')[0]) + 1;
            if (over_idx > max_overs) {
                max_overs = over_idx;
            }
        });
    });
    
    const labels = [];
    for (let i = 1; i <= max_overs; i++) {
        labels.push(`Over ${i}`);
    }
    
    const manhattanDatasets = [];
    
    state.innings.forEach(inn => {
        const over_runs = Array(max_overs).fill(0);
        const over_wkts = Array(max_overs).fill(0);
        
        const chronological = [...inn.commentary].reverse();
        chronological.forEach(c => {
            const over_idx = parseInt(c.overs.split('.')[0]) + 1;
            if (over_idx <= max_overs) {
                over_runs[over_idx - 1] += c.runs;
                if (c.is_wicket) {
                    over_wkts[over_idx - 1] += 1;
                }
            }
        });
        
        const is_inn1 = inn.innings_number === 1;
        const color = is_inn1 ? '#10b981' : '#6366f1';
        
        manhattanDatasets.push({
            type: 'bar',
            label: `${inn.batting_team_name} Runs`,
            data: over_runs,
            backgroundColor: color,
            borderColor: color,
            borderWidth: 1,
            order: 2
        });
        
        const wkt_points = [];
        for (let i = 0; i < max_overs; i++) {
            if (over_wkts[i] > 0) {
                wkt_points.push({
                    x: i,
                    y: over_runs[i] + 1
                });
            } else {
                wkt_points.push({
                    x: i,
                    y: null
                });
            }
        }
        
        manhattanDatasets.push({
            type: 'scatter',
            label: `${inn.batting_team_name} Wkts`,
            data: wkt_points,
            backgroundColor: '#ef4444',
            borderColor: '#ef4444',
            pointStyle: 'rectRot',
            pointRadius: 6,
            pointHoverRadius: 8,
            order: 1
        });
    });
    
    // Render Manhattan Chart
    const manCtx = document.getElementById('manhattanChart');
    if (manCtx) {
        if (manhattanChartInstance) {
            manhattanChartInstance.destroy();
        }
        
        manhattanChartInstance = new Chart(manCtx, {
            data: {
                labels: labels,
                datasets: manhattanDatasets
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    x: {
                        ticks: {
                            color: '#a0aec0'
                        },
                        grid: {
                            color: 'rgba(255, 255, 255, 0.05)'
                        }
                    },
                    y: {
                        title: {
                            display: true,
                            text: 'Runs in Over',
                            color: '#a0aec0'
                        },
                        ticks: {
                            color: '#a0aec0'
                        },
                        grid: {
                            color: 'rgba(255, 255, 255, 0.05)'
                        }
                    }
                },
                plugins: {
                    legend: {
                        labels: {
                            color: '#a0aec0'
                        }
                    }
                }
            }
        });
    }
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

function renderAwardsTab(state) {
    const container = document.getElementById("view-awards-container");
    if (!container) return;
    
    if (!state.awards) {
        container.innerHTML = `<p class="muted" style="text-align:center; padding: 2rem;">Awards will be calculated here once play begins...</p>`;
        return;
    }
    
    container.innerHTML = renderAwardsHTML(state.awards);
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
