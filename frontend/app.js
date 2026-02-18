let currentJobs = new Map();
let progressEventSources = new Map();

function debugLog(...args) {
    console.debug("[ndl-webui]", ...args);
}

const BACKEND_STORAGE_KEY = "ndlytmBackendBaseUri";
const ACTIVE_JOBS_STORAGE_KEY = "ndlytmActiveJobIds";

function normalizeBackendBaseUri(uri) {
    return uri.replace(/\/$/, "");
}

function getBackendBaseUri() {
    const inputValue = document.getElementById("backendBaseUri").value.trim();
    if (!inputValue) {
        return "";
    }
    return normalizeBackendBaseUri(inputValue);
}

function buildApiUrl(path) {
    const backendBaseUri = getBackendBaseUri();
    if (!backendBaseUri) {
        return path;
    }
    return `${backendBaseUri}${path}`;
}

function restoreBackendBaseUri() {
    const saved = localStorage.getItem(BACKEND_STORAGE_KEY);
    if (!saved) return;
    document.getElementById("backendBaseUri").value = saved;
}

function saveBackendBaseUri() {
    const value = getBackendBaseUri();
    if (!value) {
        localStorage.removeItem(BACKEND_STORAGE_KEY);
        return;
    }
    localStorage.setItem(BACKEND_STORAGE_KEY, value);
}

function saveTrackedJobIds() {
    const unfinishedJobs = Array.from(currentJobs.entries())
        .filter(([, data]) => !data.done && !data.error)
        .map(([jobId]) => jobId);

    if (unfinishedJobs.length === 0) {
        localStorage.removeItem(ACTIVE_JOBS_STORAGE_KEY);
        return;
    }

    localStorage.setItem(ACTIVE_JOBS_STORAGE_KEY, JSON.stringify(unfinishedJobs));
}

function restoreTrackedJobIds() {
    const raw = localStorage.getItem(ACTIVE_JOBS_STORAGE_KEY);
    if (!raw) {
        return [];
    }

    try {
        const parsed = JSON.parse(raw);
        return Array.isArray(parsed) ? parsed : [];
    } catch (error) {
        debugLog("Failed to parse saved job IDs", error);
        return [];
    }
}

/* ----------------------------------------
   Prefill from URL fragment
---------------------------------------- */

function prefillFromHash() {
    if (!window.location.hash) return;

    const fragment = window.location.hash.substring(1);
    if (!fragment.startsWith("?")) return;

    const params = new URLSearchParams(fragment.substring(1));
    const jsonInputParam = params.get("jsonInput");

    if (!jsonInputParam) return;

    const clearHashPrefillParams = () => {
        const cleanUrl = `${window.location.pathname}${window.location.search}`;
        window.history.pushState({}, document.title, cleanUrl);
    };

    try {
        const decoded = decodeURIComponent(jsonInputParam);
        document.getElementById("jsonInput").value = decoded;
        clearHashPrefillParams();
    } catch (e) {
        console.error("Failed to decode jsonInput");
    }
}

function getOrCreateJobElement(jobId) {
    const jobsSection = document.getElementById("jobsSection");
    jobsSection.style.display = "block";

    let card = document.getElementById(`job-${jobId}`);
    if (card) {
        return card;
    }

    card = document.createElement("section");
    card.className = "job-card";
    card.id = `job-${jobId}`;

    card.innerHTML = `
        <h3>Job <code>${jobId}</code></h3>
        <p class="job-status" id="status-${jobId}">Status: queued</p>
        <p class="job-progress" id="progress-${jobId}">Progress: 0 / 0 (uploaded: 0)</p>
        <progress id="bar-${jobId}" value="0" max="100"></progress>
        <pre id="logs-${jobId}" class="job-logs"></pre>
    `;

    jobsSection.prepend(card);
    return card;
}

function renderJobUI(jobId, data) {
    currentJobs.set(jobId, data);
    getOrCreateJobElement(jobId);

    const percent = data.total
        ? (data.progress / data.total) * 100
        : 0;

    document.getElementById(`status-${jobId}`).innerText = `Status: ${data.status || "unknown"}`;
    document.getElementById(`bar-${jobId}`).value = percent;
    document.getElementById(`progress-${jobId}`).innerText =
        `Progress: ${data.progress} / ${data.total} (uploaded: ${data.uploaded || 0})`;

    const logs = data.logs || [];
    document.getElementById(`logs-${jobId}`).innerText = logs.join("\n");

    if (data.error) {
        document.getElementById(`status-${jobId}`).innerText = `Status: failed (${data.error})`;
        closeProgressStream(jobId);
    } else if (data.done) {
        document.getElementById(`status-${jobId}`).innerText =
            `Status: completed (uploaded: ${data.uploaded || 0})`;
        closeProgressStream(jobId);
    }

    saveTrackedJobIds();
}

function closeProgressStream(jobId) {
    const source = progressEventSources.get(jobId);
    if (!source) {
        return;
    }

    source.close();
    progressEventSources.delete(jobId);
}

function subscribeProgressStream(jobId) {
    if (!jobId) {
        return;
    }

    closeProgressStream(jobId);

    const progressStreamUrl = buildApiUrl(`/progress-stream/${jobId}`);
    debugLog("Subscribing progress stream", { progressStreamUrl, jobId });

    const eventSource = new EventSource(progressStreamUrl);
    progressEventSources.set(jobId, eventSource);

    eventSource.addEventListener("progress", (event) => {
        const data = JSON.parse(event.data);
        debugLog("Progress stream event", { jobId, data });
        renderJobUI(jobId, data);
    });

    eventSource.onerror = (error) => {
        debugLog("Progress stream error", { jobId, error });
    };
}

/* ----------------------------------------
   Start job
---------------------------------------- */

document.getElementById("startBtn").onclick = async () => {
    const raw = document.getElementById("jsonInput").value;

    let parsed;
    try {
        parsed = JSON.parse(raw);
    } catch (e) {
        alert("Invalid JSON");
        return;
    }

    saveBackendBaseUri();

    const startUrl = buildApiUrl("/start");
    debugLog("Starting job request", { startUrl, payload: parsed });

    const resp = await fetch(startUrl, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(parsed)
    });

    if (!resp.ok) {
        alert(`Start request failed: ${resp.status}`);
        return;
    }

    const data = await resp.json();
    debugLog("Start response", { status: resp.status, data });

    const initialState = {
        progress: 0,
        total: 0,
        done: false,
        error: null,
        uploaded: 0,
        status: data.status || "queued",
        logs: [`Queued job ${data.job_id}`]
    };

    renderJobUI(data.job_id, initialState);
    subscribeProgressStream(data.job_id);
};

async function hydrateJobFromServer(jobId) {
    const progressUrl = buildApiUrl(`/progress/${jobId}`);
    const resp = await fetch(progressUrl);

    if (!resp.ok) {
        throw new Error(`Unable to fetch job progress (${resp.status})`);
    }

    return resp.json();
}

async function resumeTrackedJobs() {
    const savedJobIds = restoreTrackedJobIds();
    for (const jobId of savedJobIds) {
        getOrCreateJobElement(jobId);

        try {
            const data = await hydrateJobFromServer(jobId);
            renderJobUI(jobId, data);
            if (!data.done && !data.error) {
                subscribeProgressStream(jobId);
            }
        } catch (error) {
            debugLog("Failed to restore saved job", { jobId, error });
        }
    }

    saveTrackedJobIds();
}

/* ----------------------------------------
   Initialize
---------------------------------------- */

window.addEventListener("DOMContentLoaded", async () => {
    restoreBackendBaseUri();

    document.getElementById("backendBaseUri").addEventListener("change", saveBackendBaseUri);

    prefillFromHash();
    await resumeTrackedJobs();
});
