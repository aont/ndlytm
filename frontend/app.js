let currentJobId = null;
let progressEventSource = null;

function debugLog(...args) {
    console.debug("[ndl-webui]", ...args);
}

const BACKEND_STORAGE_KEY = "ndlytmBackendBaseUri";
const ACTIVE_JOB_STORAGE_KEY = "ndlytmActiveJobId";


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

function saveActiveJobId(jobId) {
    if (!jobId) {
        localStorage.removeItem(ACTIVE_JOB_STORAGE_KEY);
        return;
    }

    localStorage.setItem(ACTIVE_JOB_STORAGE_KEY, jobId);
}

function restoreActiveJobId() {
    return localStorage.getItem(ACTIVE_JOB_STORAGE_KEY);
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
    currentJobId = data.job_id;
    saveActiveJobId(currentJobId);

    document.getElementById("progressSection").style.display = "block";
    document.getElementById("progressText").innerText = "Job started";

    subscribeProgressStream();
};

/* ----------------------------------------
   Progress stream (SSE)
---------------------------------------- */

function subscribeProgressStream() {
    if (!currentJobId) {
        return;
    }

    if (progressEventSource) {
        progressEventSource.close();
    }

    const progressStreamUrl = buildApiUrl(`/progress-stream/${currentJobId}`);
    debugLog("Subscribing progress stream", { progressStreamUrl, currentJobId });

    progressEventSource = new EventSource(progressStreamUrl);

    progressEventSource.addEventListener("progress", (event) => {
        const data = JSON.parse(event.data);
        debugLog("Progress stream event", data);
        updateProgressUI(data);
    });

    progressEventSource.onerror = (error) => {
        debugLog("Progress stream error", error);
    };
}

function updateProgressUI(data) {
    const percent = data.total
        ? (data.progress / data.total) * 100
        : 0;

    document.getElementById("progressBar").value = percent;

    document.getElementById("progressText").innerText =
        `Progress: ${data.progress} / ${data.total} (uploaded: ${data.uploaded || 0})`;

    renderCurrentJobLogs(data.logs || []);

    if (data.error) {
        if (progressEventSource) {
            progressEventSource.close();
            progressEventSource = null;
        }
        document.getElementById("progressText").innerText = `Job failed: ${data.error}`;
        debugLog("Job failed", { data });
        saveActiveJobId(null);
        return;
    }

    if (data.done) {
        if (progressEventSource) {
            progressEventSource.close();
            progressEventSource = null;
        }

        document.getElementById("progressText").innerText =
            `Upload completed: ${data.uploaded || 0} tracks uploaded to YouTube Music`;
        saveActiveJobId(null);
    }
}

function renderCurrentJobLogs(logs) {
    document.getElementById("logOutput").innerText = logs.join("\n");
}

async function hydrateJobFromServer(jobId) {
    const progressUrl = buildApiUrl(`/progress/${jobId}`);
    const resp = await fetch(progressUrl);

    if (!resp.ok) {
        throw new Error(`Unable to fetch job progress (${resp.status})`);
    }

    return resp.json();
}

async function resumeLatestJob() {
    const savedJobId = restoreActiveJobId();
    if (savedJobId) {
        currentJobId = savedJobId;
        document.getElementById("progressSection").style.display = "block";

        try {
            const data = await hydrateJobFromServer(savedJobId);
            updateProgressUI(data);
            if (!data.done && !data.error) {
                subscribeProgressStream();
            }
            return;
        } catch (error) {
            debugLog("Failed to restore saved job", error);
            saveActiveJobId(null);
        }
    }
}

/* ----------------------------------------
   Initialize
---------------------------------------- */

window.addEventListener("DOMContentLoaded", async () => {
    restoreBackendBaseUri();

    document.getElementById("backendBaseUri").addEventListener("change", saveBackendBaseUri);

    prefillFromHash();
    await resumeLatestJob();
});
