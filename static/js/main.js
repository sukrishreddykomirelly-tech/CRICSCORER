// main.js

document.addEventListener("DOMContentLoaded", () => {
    // Check if match creation form exists
    const matchForm = document.getElementById("match-creation-form");
    if (matchForm) {
        setupMatchCreationRosters();
    }
});

/**
 * Dynamically fetches and updates team squad lists in the match creation page
 */
function setupMatchCreationRosters() {
    const team1Select = document.getElementById("team1-select");
    const team2Select = document.getElementById("team2-select");
    const team1SquadContainer = document.getElementById("team1-squad-container");
    const team2SquadContainer = document.getElementById("team2-squad-container");
    
    if (!team1Select || !team2Select) return;
    
    const fetchAndRenderRoster = (teamId, container, teamKey) => {
        if (!teamId) {
            container.innerHTML = `<p class="muted">Select a team to load players...</p>`;
            return;
        }
        
        container.innerHTML = `<p class="muted">Loading players...</p>`;
        
        fetch(`/api/team/${teamId}/players`)
            .then(res => res.json())
            .then(players => {
                if (players.length === 0) {
                    container.innerHTML = `
                        <p class="muted">No players in this team roster.</p>
                        <a href="/team/${teamId}" target="_blank" class="btn btn-outline" style="padding: 0.25rem 0.5rem; font-size: 0.8rem; margin-top: 0.5rem;">
                            Add Players
                        </a>
                    `;
                    return;
                }
                
                let html = "";
                players.forEach(p => {
                    html += `
                        <label class="squad-checkbox-item">
                            <input type="checkbox" name="${teamKey}_xi" value="${p.id}" checked>
                            <span>${p.name}</span>
                        </label>
                    `;
                });
                container.innerHTML = html;
            })
            .catch(err => {
                console.error("Error loading squad:", err);
                container.innerHTML = `<p class="text-danger">Failed to load squad.</p>`;
            });
    };
    
    // Set up change listeners
    team1Select.addEventListener("change", (e) => {
        fetchAndRenderRoster(e.target.value, team1SquadContainer, "team1");
    });
    
    team2Select.addEventListener("change", (e) => {
        fetchAndRenderRoster(e.target.value, team2SquadContainer, "team2");
    });
    
    // Trigger initial loads if pre-selected
    if (team1Select.value) {
        fetchAndRenderRoster(team1Select.value, team1SquadContainer, "team1");
    }
    if (team2Select.value) {
        fetchAndRenderRoster(team2Select.value, team2SquadContainer, "team2");
    }
}

/**
 * Helper to show alert notifications
 */
function showAlert(message, type = "info") {
    alert(message); // Standard alert, can style further if needed
}
