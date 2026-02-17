let currentJobId = null;
let pollInterval = null;

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

    const resp = await fetch(buildApiUrl("/start"), {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(parsed)
    });

    const data = await resp.json();
    currentJobId = data.job_id;

    document.getElementById("progressSection").style.display = "block";
    document.getElementById("downloadSection").style.display = "none";

    pollInterval = setInterval(pollProgress, 1000);
};

/* ----------------------------------------
   Poll progress
---------------------------------------- */

async function pollProgress() {
    const resp = await fetch(buildApiUrl(`/progress/${currentJobId}`));
    const data = await resp.json();

    const percent = data.total
        ? (data.progress / data.total) * 100
        : 0;

    document.getElementById("progressBar").value = percent;
    document.getElementById("progressText").innerText =
        `Progress: ${data.progress} / ${data.total}`;

    document.getElementById("logOutput").innerText =
        data.logs.join("\n");

    if (data.done) {
        clearInterval(pollInterval);
        await fetchZipIntoMemory();
    }
}

/* ----------------------------------------
   Fetch ZIP and create blob URL
---------------------------------------- */

async function fetchZipIntoMemory() {
    document.getElementById("progressText").innerText =
        "Downloading ZIP into memory...";

    const resp = await fetch(buildApiUrl(`/download/${currentJobId}`));
    if (!resp.ok) {
        alert("Failed to download ZIP");
        return;
    }

    const blob = await resp.blob();

    const blobUrl = URL.createObjectURL(blob);

    const link = document.getElementById("downloadLink");
    link.href = blobUrl;

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
