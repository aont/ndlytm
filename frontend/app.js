let currentJobId = null;
let pollInterval = null;

function debugLog(...args) {
    console.debug("[ndl-webui]", ...args);
}

const BACKEND_STORAGE_KEY = "backendBaseUri";


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

    try {
        const decoded = decodeURIComponent(jsonInputParam);
        document.getElementById("jsonInput").value = decoded;
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

    const data = await resp.json();
    debugLog("Start response", { status: resp.status, data });
    currentJobId = data.job_id;

    document.getElementById("progressSection").style.display = "block";
    document.getElementById("downloadSection").style.display = "none";

    pollInterval = setInterval(pollProgress, 1000);
    debugLog("Polling started", { currentJobId });
};

/* ----------------------------------------
   Poll progress
---------------------------------------- */

async function pollProgress() {
    const progressUrl = buildApiUrl(`/progress/${currentJobId}`);
    debugLog("Polling progress", { progressUrl, currentJobId });

    const resp = await fetch(progressUrl);
    const data = await resp.json();
    debugLog("Progress response", { status: resp.status, data });

    const percent = data.total
        ? (data.progress / data.total) * 100
        : 0;

    document.getElementById("progressBar").value = percent;
    document.getElementById("progressText").innerText =
        `Progress: ${data.progress} / ${data.total}`;

    document.getElementById("logOutput").innerText =
        data.logs.join("\n");

    if (data.error) {
        clearInterval(pollInterval);
        document.getElementById("progressText").innerText = `Job failed: ${data.error}`;
        debugLog("Job failed", { data });
        return;
    }

    if (data.done) {
        clearInterval(pollInterval);
        showDownloadLink();
    }
}

/* ----------------------------------------
   Prepare ZIP download link
---------------------------------------- */

function showDownloadLink() {
    const downloadUrl = buildApiUrl(`/download/${currentJobId}`);
    debugLog("Preparing ZIP download link", { downloadUrl, currentJobId });

    const link = document.getElementById("downloadLink");
    link.href = downloadUrl;

    document.getElementById("downloadSection").style.display = "block";

    document.getElementById("progressText").innerText =
        "ZIP ready for download";
}

/* ----------------------------------------
   Initialize
---------------------------------------- */

window.addEventListener("DOMContentLoaded", () => {
    restoreBackendBaseUri();

    document.getElementById("backendBaseUri").addEventListener("change", saveBackendBaseUri);

    prefillFromHash();
});
