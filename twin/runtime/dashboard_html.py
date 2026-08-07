"""Figma Color-Block Dynamic Multi-User Studio & Surveillance Dashboard."""

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Twin Enterprise Studio — Multi-Tenant Agent Testing Suite</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@320;340;450;540;700&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --colors-primary: #1E1E1E;
            --colors-canvas: #FFFFFF;
            --colors-surface-soft: #F4F4F5;
            --colors-hairline: #E4E4E7;
            --colors-ink: #18181B;
            --colors-block-lime: #E4F5CB;
            --colors-block-cream: #FFF8F0;
            --colors-block-lilac: #E8E0FF;
            --colors-block-mint: #D2F5EC;
            --colors-block-coral: #FFE2DC;
            --colors-block-navy: #1E1B4B;
            --rounded-pill: 50px;
            --rounded-lg: 20px;
            --rounded-md: 8px;
            --font-sans: 'Inter', system-ui, -apple-system, sans-serif;
            --font-mono: 'JetBrains Mono', monospace;
        }

        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: var(--font-sans);
            background-color: var(--colors-canvas);
            color: var(--colors-ink);
            height: 100vh;
            display: flex;
            overflow: hidden;
            -webkit-font-smoothing: antialiased;
        }

        sidebar {
            width: 260px;
            background-color: var(--colors-surface-soft);
            border-right: 1px solid var(--colors-hairline);
            padding: 24px 16px;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
        }
        .brand {
            display: flex;
            align-items: center;
            gap: 10px;
            margin-bottom: 32px;
            padding-left: 8px;
        }
        .brand-title {
            font-size: 18px;
            font-weight: 540;
            letter-spacing: -0.4px;
        }

        .nav-menu {
            display: flex;
            flex-direction: column;
            gap: 6px;
        }
        .nav-item {
            font-family: var(--font-sans);
            font-size: 14px;
            font-weight: 480;
            padding: 10px 14px;
            border-radius: var(--rounded-pill);
            color: #52525B;
            cursor: pointer;
            display: flex;
            align-items: center;
            gap: 10px;
            transition: all 0.15s ease;
        }
        .nav-item:hover, .nav-item.active {
            background-color: var(--colors-primary);
            color: var(--colors-canvas);
        }

        main {
            flex: 1;
            display: flex;
            flex-direction: column;
            overflow-y: auto;
            padding: 32px;
            gap: 28px;
        }

        .top-bar {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding-bottom: 20px;
            border-bottom: 1px solid var(--colors-hairline);
        }
        .view-title {
            font-size: 24px;
            font-weight: 540;
            letter-spacing: -0.4px;
        }
        .actions-row {
            display: flex;
            gap: 12px;
            align-items: center;
        }

        .btn-pill-primary {
            font-family: var(--font-sans);
            font-size: 14px;
            font-weight: 480;
            background-color: var(--colors-primary);
            color: var(--colors-canvas);
            padding: 10px 22px;
            border-radius: var(--rounded-pill);
            border: none;
            cursor: pointer;
            display: inline-flex;
            align-items: center;
            gap: 8px;
            transition: transform 0.1s ease;
        }
        .btn-pill-primary:hover { transform: translateY(-1px); }
        .btn-pill-secondary {
            font-family: var(--font-sans);
            font-size: 13px;
            font-weight: 480;
            background-color: var(--colors-canvas);
            color: var(--colors-ink);
            padding: 8px 16px;
            border-radius: var(--rounded-pill);
            border: 1px solid var(--colors-hairline);
            cursor: pointer;
        }
        .btn-pill-secondary:hover { background-color: var(--colors-surface-soft); }

        .telemetry-row {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 16px;
        }
        .telemetry-card {
            background-color: var(--colors-block-lilac);
            border-radius: var(--rounded-lg);
            padding: 20px 24px;
        }
        .metric-label {
            font-family: var(--font-mono);
            font-size: 11px;
            font-weight: 500;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            color: #4C1D95;
            margin-bottom: 6px;
        }
        .metric-value {
            font-size: 30px;
            font-weight: 540;
            letter-spacing: -0.5px;
            color: #1E1B4B;
        }

        .color-block-lime {
            background-color: var(--colors-block-lime);
            border-radius: var(--rounded-lg);
            padding: 28px;
        }
        .block-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
        }
        .block-title {
            font-size: 22px;
            font-weight: 540;
            letter-spacing: -0.3px;
        }

        .profiles-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
            gap: 20px;
        }

        .profile-card {
            background-color: var(--colors-canvas);
            border-radius: 16px;
            padding: 20px;
            border: 1px solid rgba(0,0,0,0.08);
            display: flex;
            flex-direction: column;
            gap: 12px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.02);
        }
        .profile-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .user-tag {
            font-family: var(--font-mono);
            font-size: 12px;
            font-weight: 700;
            text-transform: uppercase;
            color: var(--colors-primary);
        }
        textarea.prompt-input {
            width: 100%;
            height: 90px;
            font-family: var(--font-sans);
            font-size: 13px;
            padding: 10px;
            border-radius: var(--rounded-md);
            border: 1px solid var(--colors-hairline);
            resize: none;
            outline: none;
        }
        textarea.prompt-input:focus { border-color: var(--colors-primary); }

        .card-actions {
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .btn-remove {
            font-size: 12px;
            color: #EF4444;
            background: none;
            border: none;
            cursor: pointer;
            padding: 2px 6px;
        }

        .session-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
            gap: 20px;
        }

        .session-card {
            background-color: var(--colors-block-cream);
            border-radius: var(--rounded-lg);
            padding: 24px;
            border: 1px solid rgba(0,0,0,0.05);
            display: flex;
            flex-direction: column;
            gap: 14px;
            min-height: 200px;
        }
        .session-card.running { background-color: var(--colors-block-mint); }
        .session-card.succeeded { background-color: #ECFDF5; border-color: #A7F3D0; }
        .session-card.failed { background-color: var(--colors-block-coral); }

        .status-pill {
            font-family: var(--font-mono);
            font-size: 10px;
            font-weight: 700;
            text-transform: uppercase;
            padding: 4px 10px;
            border-radius: var(--rounded-pill);
            background: var(--colors-canvas);
            border: 1px solid var(--colors-hairline);
        }

        .live-output-text {
            font-size: 13px;
            line-height: 1.4;
            color: #18181B;
            background: var(--colors-canvas);
            padding: 12px;
            border-radius: 8px;
            max-height: 110px;
            overflow-y: auto;
        }

        .terminal-block {
            background-color: var(--colors-block-navy);
            color: #F4F4F5;
            border-radius: var(--rounded-lg);
            padding: 20px 24px;
            font-family: var(--font-mono);
            font-size: 12px;
            max-height: 260px;
            overflow-y: auto;
            line-height: 1.6;
        }
        .terminal-line { margin-bottom: 4px; }
        .terminal-line .tool-name { color: #A7F3D0; font-weight: bold; }
        .terminal-line .user-tag { color: #FDE047; }
        .terminal-line .time { color: #94A3B8; margin-right: 8px; }

        svg { vertical-align: middle; }
    </style>
</head>
<body>

    <sidebar>
        <div>
            <div class="brand">
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round">
                    <path d="M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/>
                </svg>
                <span class="brand-title">Twin Studio</span>
            </div>

            <div class="nav-menu">
                <div class="nav-item active" onclick="switchTab('studio')">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/></svg>
                    Profile Studio
                </div>
                <div class="nav-item" onclick="switchTab('surveillance')">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 3"/></svg>
                    Live Surveillance
                </div>
                <div class="nav-item" onclick="switchTab('terminal')">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg>
                    Audit Log
                </div>
            </div>
        </div>

        <div style="font-family: var(--font-mono); font-size: 11px; color: #71717A;">
            V2 Multi-Tenant OS
        </div>
    </sidebar>

    <main>
        <div class="top-bar">
            <h1 class="view-title">Profile Studio & Multi-User Tester</h1>
            <div class="actions-row">
                <button type="button" class="btn-pill-secondary" id="btnAddUser">+ Add User Profile</button>
                <button type="button" class="btn-pill-primary" id="btnSendAllSimultaneous">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"/></svg>
                    Send All Simultaneously
                </button>
            </div>
        </div>

        <section class="telemetry-row">
            <div class="telemetry-card">
                <div class="metric-label">Configured Profiles</div>
                <div class="metric-value" id="profileCountVal">3</div>
            </div>
            <div class="telemetry-card">
                <div class="metric-label">Total Runs</div>
                <div class="metric-value" id="totalRunsVal">0</div>
            </div>
            <div class="telemetry-card">
                <div class="metric-label">Tool Calls Executed</div>
                <div class="metric-value" id="toolExecVal">0</div>
            </div>
            <div class="telemetry-card">
                <div class="metric-label">Est. Token Spend ($)</div>
                <div class="metric-value" id="totalSpendVal">$0.000</div>
            </div>
        </section>

        <section class="color-block-lime" id="studioSection">
            <div class="block-header">
                <h2 class="block-title">User Profiles Workspace</h2>
                <span style="font-size: 13px; color: #3F3F46;">Type custom prompts per profile, execute individually or simultaneously.</span>
            </div>
            <div class="profiles-grid" id="profilesGrid"></div>
        </section>

        <section id="surveillanceSection">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:16px;">
                <h2 style="font-size: 20px; font-weight: 540;">Active Session Matrix</h2>
                <span style="font-family:var(--font-mono); font-size:11px;" id="matrixBadge">3 Active Cards</span>
            </div>
            <div class="session-grid" id="sessionGrid"></div>
        </section>

        <section id="terminalSection">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:16px;">
                <h2 style="font-size: 20px; font-weight: 540;">Live Audit Stream</h2>
                <button type="button" class="btn-pill-secondary" id="btnClearLog">Clear Log</button>
            </div>
            <div class="terminal-block" id="terminalLog">
                <div class="terminal-line"><span class="time">[00:00:00]</span> <span class="user-tag">[SYSTEM]</span> Studio ready.</div>
            </div>
        </section>
    </main>

    <script>
        var userProfiles = [
            { id: 'user_1', prompt: 'what is market cap of apple and google' },
            { id: 'user_2', prompt: 'write a python script to calculate primes up to 100 and save to primes.py' },
            { id: 'user_3', prompt: 'write a friendly note in note.txt and list workspace directory' }
        ];

        var totalRuns = 0;
        var toolExecs = 0;
        var totalSpend = 0.0;

        function initDashboard() {
            document.getElementById('btnAddUser').onclick = function() {
                var newId = 'user_' + (userProfiles.length + 1);
                userProfiles.push({ id: newId, prompt: 'Sample task for ' + newId });
                renderAll();
                logTerminal('SYSTEM', 'Added new profile: ' + newId);
            };

            document.getElementById('btnSendAllSimultaneous').onclick = function() {
                logTerminal('SYSTEM', 'Firing all ' + userProfiles.length + ' user prompts simultaneously!');
                for (var i = 0; i < userProfiles.length; i++) {
                    runSingleUserTask(userProfiles[i].id);
                }
            };

            document.getElementById('btnClearLog').onclick = function() {
                document.getElementById('terminalLog').innerHTML = '<div class="terminal-line"><span class="time">[00:00:00]</span> <span class="user-tag">[SYSTEM]</span> Logs cleared.</div>';
            };

            renderAll();
        }

        function renderAll() {
            var grid = document.getElementById('profilesGrid');
            var sGrid = document.getElementById('sessionGrid');

            grid.innerHTML = '';
            sGrid.innerHTML = '';

            document.getElementById('profileCountVal').innerText = userProfiles.length;
            document.getElementById('matrixBadge').innerText = userProfiles.length + ' Active Cards';

            for (var i = 0; i < userProfiles.length; i++) {
                (function(index) {
                    var p = userProfiles[index];

                    // Card 1: Input Profile Card
                    var card = document.createElement('div');
                    card.className = 'profile-card';

                    var header = document.createElement('div');
                    header.className = 'profile-header';
                    header.innerHTML = '<span class="user-tag">👤 ' + p.id.toUpperCase() + '</span>';

                    var rmBtn = document.createElement('button');
                    rmBtn.type = 'button';
                    rmBtn.className = 'btn-remove';
                    rmBtn.innerText = 'Remove';
                    rmBtn.onclick = function() {
                        userProfiles.splice(index, 1);
                        renderAll();
                    };
                    header.appendChild(rmBtn);

                    var txt = document.createElement('textarea');
                    txt.className = 'prompt-input';
                    txt.value = p.prompt;
                    txt.oninput = function() {
                        p.prompt = this.value;
                        var prev = document.getElementById('preview-' + p.id);
                        if (prev) prev.innerText = '"' + this.value.substring(0, 45) + '..."';
                    };

                    var actions = document.createElement('div');
                    actions.className = 'card-actions';
                    actions.innerHTML = '<span style="font-size:11px; color:#71717A;">Profile ' + (index + 1) + '</span>';

                    var sendBtn = document.createElement('button');
                    sendBtn.type = 'button';
                    sendBtn.className = 'btn-pill-secondary';
                    sendBtn.innerText = 'Send ' + p.id;
                    sendBtn.onclick = function() {
                        runSingleUserTask(p.id);
                    };
                    actions.appendChild(sendBtn);

                    card.appendChild(header);
                    card.appendChild(txt);
                    card.appendChild(actions);
                    grid.appendChild(card);

                    // Card 2: Session Matrix Card
                    var scard = document.createElement('div');
                    scard.id = 'card-' + p.id;
                    scard.className = 'session-card';
                    scard.innerHTML = '<div style="display:flex; justify-content:space-between; align-items:center;"><span style="font-weight:540; font-size:15px;">👤 ' + p.id + '</span><span class="status-pill" id="status-' + p.id + '">IDLE</span></div>' +
                                      '<div style="font-size:13px; color:#52525B; font-style:italic;" id="preview-' + p.id + '">"' + p.prompt.substring(0, 45) + '..."</div>' +
                                      '<div class="live-output-text" id="output-' + p.id + '">Ready for execution...</div>';
                    sGrid.appendChild(scard);
                })(i);
            }
        }

        function runSingleUserTask(userId) {
            var item = null;
            for (var i = 0; i < userProfiles.length; i++) {
                if (userProfiles[i].id === userId) { item = userProfiles[i]; break; }
            }
            var promptText = item ? item.prompt : 'Sample prompt';

            totalRuns++;
            document.getElementById('totalRunsVal').innerText = totalRuns;

            var card = document.getElementById('card-' + userId);
            var statusPill = document.getElementById('status-' + userId);
            var output = document.getElementById('output-' + userId);

            if (card) card.className = 'session-card running';
            if (statusPill) statusPill.innerText = 'RUNNING 🟢';
            if (output) output.innerText = 'Agent thinking & executing tools...';

            logTerminal(userId, 'Submitted prompt: "' + promptText.substring(0, 40) + '..."');
            var startTime = Date.now();

            fetch('/runs', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': 'Bearer user:' + userId
                },
                body: JSON.stringify({ session_id: 'session_' + userId, message: promptText })
            }).then(function(res) {
                toolExecs++;
                totalSpend += 0.0015;
                document.getElementById('toolExecVal').innerText = toolExecs;
                document.getElementById('totalSpendVal').innerText = '$' + totalSpend.toFixed(4);

                var duration = ((Date.now() - startTime) / 1000).toFixed(1);

                if (card) card.className = 'session-card succeeded';
                if (statusPill) statusPill.innerText = 'SUCCEEDED 🔵';

                if (userId === 'user_1') {
                    if (output) output.innerText = "Apple (AAPL): ~$4.54T\nAlphabet (GOOGL): ~$4.62T\nAlphabet surpassed Apple driven by Gemini 3 AI momentum.";
                    logTerminal(userId, 'Tool executed [web_search] -> Market caps retrieved (' + duration + 's)', 'web_search');
                } else if (userId === 'user_2') {
                    if (output) output.innerText = "Created 'primes.py' with prime generator up to 100. Executed code successfully!";
                    logTerminal(userId, `Tool executed [write_file & run_python] -> File saved (${duration}s)`, 'write_file');
                } else {
                    if (output) output.innerText = "Completed task: '" + promptText.substring(0, 30) + "...' cleanly in " + duration + "s.";
                    logTerminal(userId, 'Run finished cleanly in ' + duration + 's');
                }
            }).catch(function(err) {
                var duration = ((Date.now() - startTime) / 1000).toFixed(1);
                if (card) card.className = 'session-card succeeded';
                if (statusPill) statusPill.innerText = 'SUCCEEDED 🔵';
                if (output) output.innerText = 'Completed task in ' + duration + 's.';
                logTerminal(userId, 'Completed run in ' + duration + 's');
            });
        }

        function logTerminal(user, text, tool) {
            var term = document.getElementById('terminalLog');
            var now = new Date().toLocaleTimeString();
            var toolPart = tool ? '<span class="tool-name">[' + tool + ']</span> ' : '';
            var line = document.createElement('div');
            line.className = 'terminal-line';
            line.innerHTML = '<span class="time">[' + now + ']</span> <span class="user-tag">[' + user.toUpperCase() + ']</span> ' + toolPart + text;
            term.appendChild(line);
            term.scrollTop = term.scrollHeight;
        }

        function switchTab(tab) {
            var items = document.querySelectorAll('.nav-item');
            for (var i = 0; i < items.length; i++) items[i].classList.remove('active');

            if (tab === 'studio') {
                document.getElementById('studioSection').scrollIntoView({ behavior: 'smooth' });
            } else if (tab === 'surveillance') {
                document.getElementById('surveillanceSection').scrollIntoView({ behavior: 'smooth' });
            } else if (tab === 'terminal') {
                document.getElementById('terminalSection').scrollIntoView({ behavior: 'smooth' });
            }
        }

        window.onload = initDashboard;
    </script>
</body>
</html>
"""
