document.addEventListener('DOMContentLoaded', () => {
    // Check Authentication
    if (!localStorage.getItem('auth_token')) {
        window.location.href = 'login.html';
        return;
    }

    // Helper: Build auth headers for every API call
    window.getAuthHeaders = function() {
        return { 'Authorization': 'Bearer ' + localStorage.getItem('auth_token') };
    };

    // Helper: Handle 401 responses (expired/invalid token)
    window.handleAuthError = function(response) {
        if (response.status === 401) {
            localStorage.removeItem('auth_token');
            window.location.href = 'login.html';
            return true;
        }
        return false;
    };

    initTabs();
    initUploader();
    fetchConfig();
    fetchAlerts();

    // Setup Settings form listener
    document.getElementById('config-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        const targetsInput = document.getElementById('target-objects').value;
        const targets = targetsInput.split(',').map(s => s.trim().toLowerCase());
        const emailEnabled = document.getElementById('email-toggle').checked;
        const receiverEmail = document.getElementById('receiver-email').value;
        
        const liveSource = document.getElementById('live-source-select').value;
        
        const payload = {
            targets: targets,
            threshold: 0.5,
            email_enabled: emailEnabled,
            receiver_email: receiverEmail
        };

        try {
            // First, update source if selected
            if (liveSource) {
                await fetch('/api/source', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
                    body: JSON.stringify({ source: liveSource })
                });
                
                // Refresh the live feed image to break caching and restart stream
                const streamImg = document.getElementById('live-stream-img');
                if (streamImg) {
                    const token = localStorage.getItem('auth_token');
                    streamImg.src = `/api/video_feed?token=${encodeURIComponent(token)}&t=${Date.now()}`;
                }
            }

            const response = await fetch('/api/config', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
                body: JSON.stringify(payload)
            });
            const btn = e.target.querySelector('button');
            const originalText = btn.innerText;
            btn.innerText = 'Saved!';
            btn.style.background = '#22c55e';
            setTimeout(() => { btn.innerText = originalText; btn.style.background = ''; }, 2000);
        } catch (error) { console.error('Failed to save config', error); }
    });

    // Poll for alerts every 3 seconds ONLY if we are viewing the alerts tab or live dashboard
    setInterval(() => {
        fetchAlerts();
    }, 3000);

    // Logout Handler
    document.getElementById('logout-btn')?.addEventListener('click', (e) => {
        e.preventDefault();
        localStorage.removeItem('auth_token');
        window.location.href = 'login.html';
    });
});

/* --- TAB LOGIC --- */
function initTabs() {
    const navLinks = document.querySelectorAll('#sidebar-nav a');
    const panes = document.querySelectorAll('.tab-pane');
    
    // Page metadata
    const titles = {
        'tab-live': { title: 'Live Dashboard', sub: 'Continuous autonomous surveillance monitoring.' },
        'tab-detect': { title: 'Identify & Detect', sub: 'On-demand video processing analysis.' },
        'tab-alerts': { title: 'Alert Records', sub: 'Historical event verification database.' },
        'tab-settings': { title: 'Settings', sub: 'Manage system-wide configuration.' }
    };

    navLinks.forEach(link => {
        link.addEventListener('click', (e) => {
            e.preventDefault();
            const targetId = link.getAttribute('data-target');
            
            // Update UI Active states
            navLinks.forEach(n => n.classList.remove('active'));
            link.classList.add('active');
            
            panes.forEach(p => p.classList.remove('active'));
            document.getElementById(targetId).classList.add('active');
            
            // Update Header
            document.getElementById('page-title').innerText = titles[targetId].title;
            document.getElementById('page-subtitle').innerText = titles[targetId].sub;
        });
    });
}

/* --- UPLOADER LOGIC --- */
let uploadedFilename = null;

function initUploader() {
    const dropZone = document.getElementById('drop-zone');
    const fileInput = document.getElementById('video-upload-input');
    const runBtn = document.getElementById('run-detection-btn');
    const statusMsg = document.getElementById('upload-status');
    const statusText = document.getElementById('upload-text');

    dropZone.addEventListener('click', () => fileInput.click());

    // Drag events
    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
        dropZone.addEventListener(eventName, preventDefaults, false);
    });
    
    function preventDefaults (e) {
        e.preventDefault(); e.stopPropagation();
    }

    ['dragenter', 'dragover'].forEach(eventName => {
        dropZone.addEventListener(eventName, () => dropZone.classList.add('dragover'), false);
    });

    ['dragleave', 'drop'].forEach(eventName => {
        dropZone.addEventListener(eventName, () => dropZone.classList.remove('dragover'), false);
    });

    dropZone.addEventListener('drop', (e) => {
        const dt = e.dataTransfer;
        const files = dt.files;
        if(files.length) handleFiles(files[0]);
    });

    fileInput.addEventListener('change', function() {
        if(this.files.length) handleFiles(this.files[0]);
    });

    function handleFiles(file) {
        if(!file.type.startsWith('video/')) {
            alert('Please drop an MP4 or valid video file.');
            return;
        }
        uploadVideo(file);
    }

    async function uploadVideo(file) {
        statusMsg.classList.remove('hidden');
        statusText.innerText = `Uploading ${file.name}...`;
        runBtn.disabled = true;

        const formData = new FormData();
        formData.append("file", file);

        try {
            const res = await fetch('/api/upload', {
                method: 'POST',
                headers: { ...getAuthHeaders() },
                body: formData
            });
            const data = await res.json();
            
            uploadedFilename = data.filename;
            statusText.innerText = "Upload Complete. Ready to process.";
            runBtn.disabled = false;
        } catch (err) {
            console.error(err);
            statusText.innerText = "Upload failed.";
        }
    }

    // Load demo videos list
    loadDemoVideos();

    async function loadDemoVideos() {
        const demoContainer = document.getElementById('demo-videos-list');
        if (!demoContainer) return;

        try {
            const res = await fetch('/api/sources', { headers: getAuthHeaders() });
            if (!res.ok) return;
            const data = await res.json();
            const demoFiles = (data.sources || []).filter(s => s.type === 'file');

            demoContainer.innerHTML = '';
            demoFiles.forEach((file, index) => {
                const item = document.createElement('div');
                item.className = 'demo-item';
                item.innerHTML = `
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <polygon points="5 3 19 12 5 21 5 3"></polygon>
                    </svg>
                    <div class="demo-item-info">
                        <span class="demo-item-title">${file.name}</span>
                        <span class="demo-item-desc">Demo Clip ${index + 1}</span>
                    </div>
                `;

                item.addEventListener('click', async () => {
                    document.querySelectorAll('.demo-item').forEach(el => el.classList.remove('selected'));
                    item.classList.add('selected');
                    await selectDemoVideo(file.id);
                });

                demoContainer.appendChild(item);
            });
        } catch (err) {
            console.error('Failed to load demo videos:', err);
        }
    }

    async function selectDemoVideo(filename) {
        statusMsg.classList.remove('hidden');
        statusText.innerText = `Loading demo ${filename}...`;
        runBtn.disabled = true;

        try {
            const res = await fetch('/api/select_demo', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
                body: JSON.stringify({ filename })
            });
            const data = await res.json();
            if (res.ok) {
                uploadedFilename = data.filename;
                statusText.innerText = `Demo selected: ${data.filename}. Click 'Run Detection' to play.`;
                runBtn.disabled = false;
            } else {
                statusText.innerText = data.message || 'Failed to load demo video.';
            }
        } catch (err) {
            console.error(err);
            statusText.innerText = 'Error selecting demo video.';
        }
    }

    runBtn.addEventListener('click', () => {
        const videoWrapper = document.getElementById('custom-video-wrapper');
        const token = localStorage.getItem('auth_token');
        
        // Show loading spinner first
        videoWrapper.innerHTML = `
            <div id="custom-loading-overlay" class="video-loading-overlay">
                <div class="spinner"></div>
                <span>Initializing custom analyzer stream...</span>
            </div>
            <img src="/api/custom_feed?t=${new Date().getTime()}&token=${encodeURIComponent(token)}" 
                 alt="Processing Interface Offline" 
                 style="width:100%; height:100%; object-fit:contain;"
                 onload="document.getElementById('custom-loading-overlay').style.display='none';"
                 onerror="document.getElementById('custom-loading-overlay').querySelector('span').textContent='Custom stream offline';">
            <div class="overlay-scan"></div>
        `;
        runBtn.innerText = "Processing...";
    });
}


/* --- DATA LOGIC --- */
let lastAlertId = 0;

async function fetchConfig() {
    try {
        const response = await fetch('/api/config', { headers: getAuthHeaders() });
        if (handleAuthError(response)) return;
        const config = await response.json();
        document.getElementById('target-objects').value = config.targets.join(', ');
        document.getElementById('email-toggle').checked = config.email_enabled;
        if(config.receiver_email) document.getElementById('receiver-email').value = config.receiver_email;
        
        // Fetch sources list
        const sourcesResponse = await fetch('/api/sources', { headers: getAuthHeaders() });
        if (sourcesResponse.ok) {
            const data = await sourcesResponse.json();
            const selectEl = document.getElementById('live-source-select');
            if (selectEl) {
                selectEl.innerHTML = '';
                data.sources.forEach(src => {
                    const opt = document.createElement('option');
                    opt.value = src.id;
                    opt.textContent = src.name;
                    if (src.id === data.current || (src.id === "0" && data.current === "Webcam")) {
                        opt.selected = true;
                    }
                    selectEl.appendChild(opt);
                });
            }
        }
    } catch (e) {
        console.error('Failed to init config', e);
    }
}

async function fetchAlerts() {
    try {
        const tbody = document.getElementById('alerts-table-body');
        if (!tbody) return;

        // If it's the very first load and we don't have any rows, display skeletons
        if (tbody.children.length === 0 || (tbody.children.length === 1 && tbody.innerHTML.includes('No alerts'))) {
            tbody.innerHTML = Array(5).fill(0).map(() => `
                <tr>
                    <td><div class="skeleton-line" style="width:60px; height:45px;"></div></td>
                    <td><div class="skeleton-line" style="width:100px;"></div></td>
                    <td><div class="skeleton-line" style="width:60px;"></div></td>
                    <td><div class="skeleton-line" style="width:120px;"></div></td>
                    <td><div class="skeleton-line" style="width:160px;"></div></td>
                </tr>
            `).join('');
        }

        const response = await fetch('/api/alerts?limit=15', { headers: getAuthHeaders() });
        if (handleAuthError(response)) return;
        const data = await response.json();

        if (data.alerts.length === 0) {
            tbody.innerHTML = '<tr><td colspan="5" style="text-align:center; padding: 20px; color: #94a3b8;">No alerts registered in database.</td></tr>';
            return;
        }

        tbody.innerHTML = '';
        let newAlertFound = false;

        data.alerts.forEach(alert => {
            if (alert.id > lastAlertId) {
                newAlertFound = true;
                lastAlertId = data.alerts[0].id; // We use the top (latest) ID for our check base
            }

            const tr = document.createElement('tr');
            const isCritical = alert.confidence > 80;
            const dateStr = new Date(alert.timestamp).toLocaleString();
            
            tr.innerHTML = `
                <td>
                    <img src="${alert.image_url}" class="alert-thumbnail" onerror="this.src='data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIxMDAlIiBoZWlnaHQ9IjEwMCUiPjxyZWN0IHdpZHRoPSIxMDAlIiBoZWlnaHQ9IjEwMCUiIGZpbGw9IiMzMzMiIC8+PC9zdmc+'" />
                </td>
                <td class="${isCritical ? 'critical-text' : ''}">${alert.object_class.toUpperCase()}</td>
                <td>${Math.round(alert.confidence)}%</td>
                <td><span class="badge">${alert.source_video || 'Live Feed'}</span></td>
                <td style="color:var(--text-secondary); font-size:0.85rem;">${dateStr}</td>
            `;
            tbody.appendChild(tr);
        });

        if (newAlertFound) {
            triggerFrontendAlert();
        }
    } catch (error) {
        console.error('Failed to fetch alerts', error);
    }
}

function triggerFrontendAlert() {
    // Only alarm if setting allows it or silently blink
    const audio = document.getElementById('alarm-sound');
    audio.play().catch(e => console.log('Audio disabled by browser.'));
    
    document.body.classList.add('alert-active');
    setTimeout(() => { document.body.classList.remove('alert-active'); }, 1500);
}
