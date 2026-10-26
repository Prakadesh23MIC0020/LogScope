let errors = [];

let stats = {};

let environments = [];
let pendingSourceName = "";
let githubFiles = [];
let selectedGithubPaths = new Set();

let severityPlot = null;

let typePlot = null;


const $ = id =>
    document.getElementById(id);


/* ================================================= */
/* TABS */
/* ================================================= */

document
    .querySelectorAll(".tab")
    .forEach(button => {

        button.addEventListener(
            "click",
            () => {

                const name =
                    button.dataset.tab;


                document
                    .querySelectorAll(".tab")
                    .forEach(tab => {

                        tab.classList.toggle(
                            "active",
                            tab.dataset.tab === name
                        );

                    });


                document
                    .querySelectorAll(".tab-page")
                    .forEach(page => {

                        page.classList.toggle(
                            "active",
                            page.id === name
                        );

                    });


                if (name === "history") {

                    loadHistory();

                    loadKnowledge();

                }

                if (name === "github" && githubFiles.length === 0) {
                    const repo = $("githubRepoUrl").value.trim();
                    if (repo) loadGithubFiles();
                }

            }
        );

    });


/* ================================================= */
/* ESCAPE */
/* ================================================= */

function escapeHtml(value) {

    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");

}


/* ================================================= */
/* FILE UPLOAD */
/* ================================================= */

$("fileInput")
    .addEventListener(
        "change",
        async event => {

            const file =
                event.target.files[0];


            if (!file) {

                return;

            }


            $("fileName")
                .textContent =
                file.name;


            try {

                $("logInput").value =
                    await file.text();

            }

            catch (error) {

                $("fileName")
                    .textContent =
                    "Could not read file";

            }

        }
    );


/* ================================================= */
/* PUBLIC GITHUB LOG LIBRARY */
/* ================================================= */

$("loadGithubFiles").addEventListener("click", loadGithubFiles);
$("githubRepoUrl").addEventListener("keydown", event => {
    if (event.key === "Enter") {
        event.preventDefault();
        loadGithubFiles();
    }
});
$("githubSearch").addEventListener("input", renderGithubFiles);
$("selectVisibleGithub").addEventListener("click", () => {
    visibleGithubFiles().forEach(file => selectedGithubPaths.add(file.path));
    renderGithubFiles();
});
$("clearGithubSelection").addEventListener("click", () => {
    selectedGithubPaths.clear();
    renderGithubFiles();
});
$("analyzeGithubButton").addEventListener("click", analyzeSelectedGithubFiles);

function setGithubMessage(message, error = false) {
    $("githubMessage").innerHTML = message
        ? `<div class="message ${error ? "error" : ""}">${escapeHtml(message)}</div>`
        : "";
}

async function loadGithubFiles() {
    const repo = $("githubRepoUrl").value.trim();
    if (!repo) {
        setGithubMessage("Enter a public GitHub repository URL first.", true);
        $("githubRepoUrl").focus();
        return;
    }

    const button = $("loadGithubFiles");
    button.disabled = true;
    button.textContent = "Loading...";
    $("githubStatus").textContent = "Loading public repository tree...";
    setGithubMessage("");
    try {
        const response = await fetch(`/api/github/files?repo=${encodeURIComponent(repo)}`);
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "Could not load files from this repository.");
        githubFiles = data.files || [];
        selectedGithubPaths.clear();
        $("githubRepoUrl").value = `https://github.com/${data.repository}`;
        $("githubStatus").textContent = `${data.repository} · branch ${data.branch} · ${data.count} supported file${data.count === 1 ? "" : "s"}`;
        renderGithubFiles();
        if (data.tree_truncated) {
            setGithubMessage("GitHub returned a truncated repository tree. The displayed file list may not include every file.");
        } else if (!githubFiles.length) {
            setGithubMessage("No supported log files were found. Try a repository with .log, .txt, .out, .err, .json, .csv, .xml, .yaml or .syslog files. Large files are skipped.", true);
        }
    } catch (error) {
        githubFiles = [];
        selectedGithubPaths.clear();
        renderGithubFiles();
        $("githubStatus").textContent = "Could not load repository";
        setGithubMessage(error.message, true);
    } finally {
        button.disabled = false;
        button.textContent = "Load files";
    }
}

function visibleGithubFiles() {
    const query = $("githubSearch").value.trim().toLowerCase();
    return githubFiles.filter(file => !query || `${file.name} ${file.display_path}`.toLowerCase().includes(query));
}

function renderGithubFiles() {
    const files = visibleGithubFiles();
    const list = $("githubFileList");
    if (!files.length) {
        list.innerHTML = `<div class="info-box">${githubFiles.length ? "No files match your search." : "Load a public repository to view supported files."}</div>`;
    } else {
        list.innerHTML = files.map(file => `
            <label class="repo-file-row">
                <input class="github-file-checkbox repo-file-checkbox" type="checkbox" data-path="${escapeHtml(file.path)}" ${selectedGithubPaths.has(file.path) ? "checked" : ""}>
                <span class="repo-file-icon">${escapeHtml(file.name.split(".").pop().toUpperCase().slice(0, 4))}</span>
                <span class="repo-file-details">
                    <span class="repo-file-name">${escapeHtml(file.name)}</span>
                    <span class="repo-file-path">${escapeHtml(file.display_path)}</span>
                </span>
                <span class="repo-file-size">${formatFileSize(file.size)}</span>
            </label>
        `).join("");
        list.querySelectorAll(".github-file-checkbox").forEach(input => {
            input.addEventListener("change", () => {
                if (input.checked) selectedGithubPaths.add(input.dataset.path);
                else selectedGithubPaths.delete(input.dataset.path);
                updateGithubSelectionCount();
            });
        });
    }
    updateGithubSelectionCount();
}

function updateGithubSelectionCount() {
    const count = selectedGithubPaths.size;
    $("githubSelectedCount").textContent = `${count} selected`;
    $("analyzeGithubButton").disabled = count === 0;
    $("analyzeGithubButton").textContent = count ? `Fetch & Analyze ${count} file${count === 1 ? "" : "s"}` : "Fetch & Analyze selected";
}

async function analyzeSelectedGithubFiles() {
    const paths = [...selectedGithubPaths];
    const repo = $("githubRepoUrl").value.trim();
    if (!paths.length || !repo) return;
    const button = $("analyzeGithubButton");
    button.disabled = true;
    button.textContent = "Fetching files...";
    setGithubMessage(`Fetching ${paths.length} selected file${paths.length === 1 ? "" : "s"} from GitHub...`);
    try {
        const response = await fetch("/api/github/fetch", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ repo, paths })
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "Could not fetch selected GitHub files.");
        $("logInput").value = data.text || "";
        $("fileName").textContent = `${data.count} GitHub file${data.count === 1 ? "" : "s"} ready for analysis`;
        pendingSourceName = `GitHub ${data.repository} (${(data.files || []).map(file => file.name).join(", ")})`;
        setGithubMessage(`Retrieved ${data.count} file${data.count === 1 ? "" : "s"} from ${data.repository}. Starting LogScope analysis...`);
        await analyzeLog();
        document.querySelector('.tab[data-tab="results"]').click();
    } catch (error) {
        setGithubMessage(error.message, true);
    } finally {
        updateGithubSelectionCount();
    }
}

function formatFileSize(bytes) {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}


/* ================================================= */
/* ANALYZE */
/* ================================================= */

$("analyzeButton")
    .addEventListener(
        "click",
        analyzeLog
    );


async function analyzeLog() {

    const text =
        $("logInput")
            .value
            .trim();


    if (!text) {

        showMessage(
            "Please upload or paste a log.",
            true
        );

        return;

    }


    $("analyzeButton")
        .disabled =
        true;


    $("analyzeButton")
        .textContent =
        "Analyzing...";


    showMessage(
        "Analyzing log...",
        false
    );


    try {

        const response =
            await fetch(
                "/api/analyze",
                {

                    method: "POST",

                    headers: {
                        "Content-Type":
                            "application/json"
                    },

                    body:
                        JSON.stringify({

                            text: text,

                            source_name:
                                pendingSourceName
                                || $("fileInput").files[0]?.name
                                || "Pasted Log"

                        })

                }
            );


        const data =
            await response.json();


        if (!response.ok) {

            throw new Error(
                data.error ||
                "Analysis failed"
            );

        }


        pendingSourceName = "";

        errors =
            data.errors || [];


        stats =
            data.stats || {};


        environments =
            data.environments ||
            ["General"];


        renderResults();


        showMessage(
            "Analysis completed. Open the Results tab to view the diagnosis.",
            false
        );


        document
            .querySelector(
                '[data-tab="results"]'
            )
            .click();


        loadKnowledge();

    }

    catch (error) {

        showMessage(
            error.message,
            true
        );

    }

    finally {

        $("analyzeButton")
            .disabled =
            false;


        $("analyzeButton")
            .textContent =
            "Analyze Log";

    }

}


function showMessage(
    message,
    error
) {

    $("analyzeMessage")
        .innerHTML =
        `
        <div class="message ${error ? "error" : ""}">
            ${escapeHtml(message)}
        </div>
        `;

}


/* ================================================= */
/* RESULTS */
/* ================================================= */

function renderResults() {

    $("noResults")
        .classList
        .add("hidden");


    $("resultsContainer")
        .classList
        .remove("hidden");


    $("environment")
        .textContent =
        environments.join(" · ");


    $("totalLines")
        .textContent =
        stats.total_lines || 0;


    $("totalErrors")
        .textContent =
        stats.total_errors || 0;


    $("criticalErrors")
        .textContent =
        stats.critical || 0;


    $("uniqueErrors")
        .textContent =
        stats.unique_errors || 0;


    renderErrorCards();

    renderErrorTable();

    renderCharts();

}


/* ================================================= */
/* FILTER */
/* ================================================= */

$("searchInput")
    .addEventListener(
        "input",
        () => {

            renderErrorCards();

            renderErrorTable();

        }
    );


$("severityFilter")
    .addEventListener(
        "change",
        () => {

            renderErrorCards();

            renderErrorTable();

        }
    );


function selectedSeverities() {

    return Array
        .from(
            $("severityFilter")
                .selectedOptions
        )
        .map(
            option =>
                option.value
        );

}


function filteredErrors() {

    const query =
        $("searchInput")
            .value
            .toLowerCase()
            .trim();


    const severity =
        selectedSeverities();


    return errors.filter(
        error => {

            if (
                !severity.includes(
                    error.severity
                )
            ) {

                return false;

            }


            if (!query) {

                return true;

            }


            const text =
                [

                    error.type,

                    error.message,

                    error.file

                ]
                    .join(" ")
                    .toLowerCase();


            return text.includes(
                query
            );

        }
    );

}


/* ================================================= */
/* ERROR CARDS */
/* ================================================= */

function renderErrorCards() {

    const filtered =
        filteredErrors();


    if (!filtered.length) {

        $("errorCards")
            .innerHTML =
            `
            <div class="info-box">
                No errors match the current filters.
            </div>
            `;

        return;

    }


    $("errorCards")
        .innerHTML =
        filtered
            .map(
                createErrorCard
            )
            .join("");

}


function createErrorCard(error) {

    const explanation =
        error.explanation ||
        {};


    const severity =
        error.severity ||
        "Error";


    const errorType =
        error.type ||
        "Unknown Error";


    const file =
        error.file ||
        "Unknown";


    const line =
        error.line ||
        "-";


    const category =
        explanation.category ||
        environments[0] ||
        "General";


    const component =
        explanation.component ||
        "General";


    const confidence =
        Number(
            explanation.confidence ||
            0
        );


    const source =
        explanation.source ||
        "Unknown";


    let codeHtml = "";


    if (explanation.code) {

        codeHtml =
            `
            <div class="section-title">
                ▣ Suggested change
            </div>

            <pre class="code-block">${escapeHtml(
                explanation.code
            )}</pre>
            `;

    }


    let resourcesHtml = "";


    const resources =
        explanation.source_links ||
        [];


    if (
        resources.length > 0 &&
        ["AI Research", "Rule-based + External Research", "External research only"].includes(source) &&
        (confidence >= 0.70 || source === "External research only")
    ) {

        resourcesHtml =
            `
            <div class="section-title">
                ◈ Related resources
            </div>

            ${
                resources
                    .map(
                        item =>
                            `
                            <div class="resource">

                                <a
                                    href="${escapeHtml(
                                        item.url || "#"
                                    )}"
                                    target="_blank"
                                    rel="noopener noreferrer"
                                >
                                    ${escapeHtml(
                                        item.title ||
                                        "Source"
                                    )}
                                </a>

                            </div>
                            `
                    )
                    .join("")
            }
            `;

    }


    return `
        <div class="error-card">

            <div class="error-title">
                ◆ ${escapeHtml(
                    errorType
                )}
            </div>


            <div class="badges">

                <span class="badge">
                    ${escapeHtml(
                        severity.toUpperCase()
                    )}
                </span>

                <span class="badge">
                    ${escapeHtml(category)}
                </span>

                <span class="badge">
                    ${escapeHtml(component)}
                </span>

            </div>


            <div class="error-meta">

                <div class="meta-title">
                    LOCATION
                </div>

                <div>
                    ${escapeHtml(file)}:${escapeHtml(line)}
                </div>


                <div class="meta-title">
                    OCCURRENCES
                </div>

                <div>
                    ${escapeHtml(
                        error.occurrences ||
                        1
                    )}
                </div>


                <div class="meta-title">
                    KNOWLEDGE SOURCE
                </div>

                <div>
                    ${escapeHtml(source)}
                    · Confidence
                    ${Math.round(
                        confidence * 100
                    )}%
                </div>

            </div>


            <div class="section-title">
                ⌁ What happened
            </div>

            <div>
                ${escapeHtml(
                    explanation.description ||
                    "No explanation available."
                )}
            </div>


            <div class="section-title">
                ⌁ Likely cause
            </div>

            <div>
                ${escapeHtml(
                    explanation.cause ||
                    "No sufficiently reliable cause was identified."
                )}
            </div>


            <div class="section-title">
                ▣ Fix
            </div>

            <div>
                ${escapeHtml(
                    explanation.fix ||
                    "Review the stack trace and investigate the affected component."
                )}
            </div>


            ${codeHtml}


            ${resourcesHtml}


            <details class="learning-panel">
                <summary>Teach LogScope · confirm or improve this fix</summary>
                <p class="learning-help">Only save a fix after you have verified it resolved the issue. Your submitted solution becomes reusable knowledge for future analyses.</p>
                <form class="knowledge-feedback-form">
                    <input type="hidden" name="error_type" value="${escapeHtml(errorType)}">
                    <input type="hidden" name="environment" value="${escapeHtml(category)}">
                    <input type="hidden" name="component" value="${escapeHtml(component)}">
                    <label>Generalized error signature
                        <input name="pattern" maxlength="180" required value="${escapeHtml(error.message || errorType)}" placeholder="e.g. connection refused to database">
                    </label>
                    <label>What happened
                        <textarea name="description" maxlength="1000" required>${escapeHtml(explanation.description || "")}</textarea>
                    </label>
                    <label>Root cause
                        <textarea name="cause" maxlength="1500" required>${escapeHtml(explanation.cause || "")}</textarea>
                    </label>
                    <label>Verified fix
                        <textarea name="fix" maxlength="3000" required>${escapeHtml(explanation.fix || "")}</textarea>
                    </label>
                    <label>Example or code (optional)
                        <textarea name="example" maxlength="3000">${escapeHtml(explanation.code || "")}</textarea>
                    </label>
                    <div class="learning-actions">
                        <button class="confirm-fix-button" type="submit">✓ Confirm fix & teach LogScope</button>
                        <button class="not-fixed-button" type="button" data-feedback="not_fixed">This did not fix it</button>
                    </div>
                    <div class="learning-status" aria-live="polite"></div>
                </form>
            </details>

            <details>

                <summary>
                    View raw log
                </summary>

                <pre class="raw-log">${escapeHtml(
                    error.raw || ""
                )}</pre>

            </details>

        </div>
    `;

}


/* ================================================= */
/* USER-CONFIRMED LEARNING */
/* ================================================= */

$("errorCards").addEventListener("submit", async event => {
    const form = event.target.closest(".knowledge-feedback-form");
    if (!form) return;
    event.preventDefault();
    const status = form.querySelector(".learning-status");
    const submit = form.querySelector(".confirm-fix-button");
    const values = Object.fromEntries(new FormData(form).entries());
    status.textContent = "Saving confirmed solution…";
    status.className = "learning-status is-pending";
    submit.disabled = true;
    try {
        const response = await fetch("/api/knowledge/feedback", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ ...values, confirmed: true, outcome: "fixed" })
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "Could not save feedback.");
        status.textContent = data.message || "Saved. LogScope can reuse this confirmed fix in future analyses.";
        status.className = "learning-status is-success";
        form.classList.add("is-learned");
        loadKnowledge();
    } catch (error) {
        status.textContent = error.message || "Could not save feedback. Check the database connection.";
        status.className = "learning-status is-error";
    } finally {
        submit.disabled = false;
    }
});

$("errorCards").addEventListener("click", async event => {
    const button = event.target.closest('[data-feedback="not_fixed"]');
    if (!button) return;
    const form = button.closest(".knowledge-feedback-form");
    const status = form.querySelector(".learning-status");
    const values = Object.fromEntries(new FormData(form).entries());
    button.disabled = true;
    try {
        const response = await fetch("/api/knowledge/feedback", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ ...values, confirmed: false, outcome: "not_fixed" })
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "Could not submit feedback.");
        status.textContent = data.message || "Feedback received.";
        status.className = "learning-status is-pending";
    } catch (error) {
        status.textContent = error.message || "Could not submit feedback.";
        status.className = "learning-status is-error";
    } finally {
        button.disabled = false;
    }
});

/* ================================================= */
/* TABLE */
/* ================================================= */

function renderErrorTable() {

    const filtered =
        filteredErrors();


    $("errorTable")
        .innerHTML =
        filtered
            .map(
                error =>
                    `
                    <tr>

                        <td>
                            ${escapeHtml(
                                error.type ||
                                "Unknown Error"
                            )}
                        </td>

                        <td>
                            ${escapeHtml(
                                error.severity ||
                                "Error"
                            )}
                        </td>

                        <td>
                            ${escapeHtml(
                                error.file ||
                                "Unknown"
                            )}
                        </td>

                        <td>
                            ${escapeHtml(
                                error.line ||
                                "-"
                            )}
                        </td>

                        <td>
                            ${escapeHtml(
                                error.occurrences ||
                                1
                            )}
                        </td>

                    </tr>
                    `
            )
            .join("");

}


/* ================================================= */
/* PLOTLY CHARTS */
/* ================================================= */

function renderCharts() {

    const severity =
        stats.severity ||
        {};


    const types =
        stats.types ||
        {};


    const layout = {

        paper_bgcolor:
            "rgba(0,0,0,0)",

        plot_bgcolor:
            "rgba(0,0,0,0)",

        font: {
            color: "#ddd"
        },

        margin: {
            l: 55,
            r: 20,
            t: 55,
            b: 55
        },

        title: {
            font: {
                size: 16
            }
        },

        xaxis: {
            gridcolor:
                "rgba(255,255,255,.05)"
        },

        yaxis: {
            gridcolor:
                "rgba(255,255,255,.05)"
        }

    };


    Plotly.newPlot(

        "severityChart",

        [

            {

                x:
                    Object.keys(
                        severity
                    ),

                y:
                    Object.values(
                        severity
                    ),

                type: "bar",

                name: "Count"

            }

        ],

        {

            ...layout,

            title:
                "Severity Distribution"

        },

        {

            displayModeBar:
                false,

            responsive: true

        }

    );


    Plotly.newPlot(

        "typeChart",

        [

            {

                x:
                    Object.keys(
                        types
                    ),

                y:
                    Object.values(
                        types
                    ),

                type: "bar",

                name: "Count"

            }

        ],

        {

            ...layout,

            title:
                "Error Types"

        },

        {

            displayModeBar:
                false,

            responsive: true

        }

    );

}


/* ================================================= */
/* EXPORT CSV */
/* ================================================= */

$("downloadCsv")
    .addEventListener(
        "click",
        () => {

            const rows = [

                [
                    "Type",
                    "Severity",
                    "Message",
                    "File",
                    "Line",
                    "Occurrences"
                ]

            ];


            errors.forEach(
                error => {

                    rows.push(

                        [

                            error.type || "",

                            error.severity || "",

                            error.message || "",

                            error.file || "",

                            error.line || "",

                            error.occurrences || 1

                        ]

                    );

                }
            );


            const csv =
                rows
                    .map(
                        row =>
                            row
                                .map(
                                    value =>
                                        `"${String(
                                            value
                                        ).replaceAll(
                                            '"',
                                            '""'
                                        )}"`
                                )
                                .join(",")
                    )
                    .join("\n");


            download(
                "logscope_results.csv",
                csv,
                "text/csv"
            );

        }
    );


/* ================================================= */
/* EXPORT JSON */
/* ================================================= */

$("downloadJson")
    .addEventListener(
        "click",
        () => {

            download(

                "logscope_results.json",

                JSON.stringify(
                    errors,
                    null,
                    2
                ),

                "application/json"

            );

        }
    );


function download(
    filename,
    content,
    type
) {

    const blob =
        new Blob(
            [content],
            {
                type: type
            }
        );


    const url =
        URL.createObjectURL(
            blob
        );


    const link =
        document.createElement(
            "a"
        );


    link.href = url;

    link.download =
        filename;


    document
        .body
        .appendChild(link);


    link.click();


    link.remove();


    URL.revokeObjectURL(
        url
    );

}


/* ================================================= */
/* HISTORY */
/* ================================================= */

async function loadHistory() {

    try {

        const response =
            await fetch(
                "/api/history"
            );


        const data =
            await response.json();


        if (!response.ok) {

            throw new Error(
                data.error ||
                "Could not load history"
            );

        }


        const history =
            data.history ||
            [];


        if (!history.length) {

            $("historyArea")
                .innerHTML =
                "No previous analyses found.";

            return;

        }


        $("historyArea")
            .innerHTML =
            `
            <div class="table-container">

                <table>

                    <thead>

                        <tr>

                            <th>
                                ID
                            </th>

                            <th>
                                Source
                            </th>

                            <th>
                                Lines
                            </th>

                            <th>
                                Errors
                            </th>

                            <th>
                                Critical
                            </th>

                            <th>
                                Warnings
                            </th>

                            <th>
                                Unique
                            </th>

                            <th>
                                Created
                            </th>

                        </tr>

                    </thead>


                    <tbody>

                        ${
                            history
                                .map(
                                    item =>
                                        `
                                        <tr>

                                            <td>
                                                ${escapeHtml(
                                                    item.id
                                                )}
                                            </td>

                                            <td>
                                                ${escapeHtml(
                                                    item.source_name
                                                )}
                                            </td>

                                            <td>
                                                ${escapeHtml(
                                                    item.total_lines
                                                )}
                                            </td>

                                            <td>
                                                ${escapeHtml(
                                                    item.total_errors
                                                )}
                                            </td>

                                            <td>
                                                ${escapeHtml(
                                                    item.critical
                                                )}
                                            </td>

                                            <td>
                                                ${escapeHtml(
                                                    item.warnings
                                                )}
                                            </td>

                                            <td>
                                                ${escapeHtml(
                                                    item.unique_errors
                                                )}
                                            </td>

                                            <td>
                                                ${escapeHtml(
                                                    item.created_at
                                                )}
                                            </td>

                                        </tr>
                                        `
                                )
                                .join("")
                        }

                    </tbody>

                </table>

            </div>
            `;

    }

    catch (error) {

        $("historyArea")
            .innerHTML =
            `
            <div class="message error">
                ${escapeHtml(
                    error.message
                )}
            </div>
            `;

    }

}


/* ================================================= */
/* KNOWLEDGE BASE */
/* ================================================= */

async function loadKnowledge() {

    try {

        const response =
            await fetch(
                "/api/knowledge"
            );


        const data =
            await response.json();


        if (!response.ok) {

            return;

        }


        const knowledge =
            data.stats ||
            data;


        $("knowledgeTotal")
            .textContent =
            knowledge.total || 0;


        $("knowledgeBuiltIn")
            .textContent =
            knowledge.built_in || 0;


        $("knowledgeLearned")
            .textContent =
            knowledge.learned || 0;


        $("knowledgeConfidence")
            .textContent =
            `${Math.round(
                Number(
                    knowledge.average_confidence ||
                    0
                ) * 100
            )}%`;

    }

    catch {

    }

}


/* ================================================= */
/* INITIAL LOAD */
/* ================================================= */

loadHistory();

loadKnowledge();
