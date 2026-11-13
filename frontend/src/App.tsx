import { useState, type FormEvent } from "react";
import {
  analyzeRepository,
  ApiRequestError,
  inspectGitHubRepository,
  verifyChange,
} from "./api";
import type {
  AnalysisResult,
  CheckResult,
  Decision,
  EvidenceRecord,
  GitHubInspectionResult,
  VerificationResult,
  VerifyRequest,
} from "./types";

type WorkspaceMode = "verify" | "analyze" | "github";
type SourceMode = "source" | "repository";
type ResultState =
  | { kind: "verification"; data: VerificationResult }
  | { kind: "analysis"; data: AnalysisResult }
  | { kind: "github"; data: GitHubInspectionResult };
type RetryRequest =
  | { kind: "verification"; data: VerifyRequest }
  | { kind: "analysis"; data: { repository_path: string; max_files: number } }
  | {
      kind: "github";
      data: { repository_url: string; pull_request_number?: number; max_files: number };
    };

const EXAMPLE_SOURCE = `def normalize_username(value: str) -> str:
    """Return a normalized username for account lookup."""
    return value.strip().lower()
`;

const DECISION_COPY: Record<Decision, { label: string; description: string }> = {
  VERIFIED: {
    label: "Verified",
    description: "Required evidence supports the fix under the recorded conditions.",
  },
  NOT_REPRODUCED: {
    label: "Not reproduced",
    description:
      "A valid pre-patch run did not reproduce the issue under the tested conditions. This does not prove the bug is absent.",
  },
  INSUFFICIENT_EVIDENCE: {
    label: "Insufficient evidence",
    description:
      "The available evidence does not support a stronger conclusion. The current API does not execute source or tests.",
  },
};

function App() {
  const [workspaceMode, setWorkspaceMode] = useState<WorkspaceMode>("verify");
  const [sourceMode, setSourceMode] = useState<SourceMode>("source");
  const [bugDescription, setBugDescription] = useState("");
  const [sourceCode, setSourceCode] = useState("");
  const [repositoryPath, setRepositoryPath] = useState("");
  const [unifiedDiff, setUnifiedDiff] = useState("");
  const [maxFiles, setMaxFiles] = useState("100");
  const [githubMaxFiles, setGithubMaxFiles] = useState("20");
  const [githubUrl, setGithubUrl] = useState("");
  const [pullRequestNumber, setPullRequestNumber] = useState("");
  const [showDiff, setShowDiff] = useState(false);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<ResultState | null>(null);
  const [error, setError] = useState<ApiRequestError | null>(null);
  const [retryRequest, setRetryRequest] = useState<RetryRequest | null>(null);

  async function sendRequest(request: RetryRequest) {
    setLoading(true);
    setError(null);
    setResult(null);
    setRetryRequest(request);
    try {
      if (request.kind === "verification") {
        setResult({ kind: "verification", data: await verifyChange(request.data) });
      } else if (request.kind === "analysis") {
        setResult({ kind: "analysis", data: await analyzeRepository(request.data) });
      } else {
        setResult({ kind: "github", data: await inspectGitHubRepository(request.data) });
      }
      setRetryRequest(null);
    } catch (caught) {
      setError(
        caught instanceof ApiRequestError
          ? caught
          : new ApiRequestError("Something unexpected happened. Please retry."),
      );
    } finally {
      setLoading(false);
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setResult(null);

    if (workspaceMode === "github") {
      const fileLimit = Number(githubMaxFiles);
      const prNumber = pullRequestNumber.trim() ? Number(pullRequestNumber) : undefined;
      if (!githubUrl.trim()) {
        setError(new ApiRequestError("Enter a public GitHub repository URL."));
        return;
      }
      if (!Number.isInteger(fileLimit) || fileLimit < 1 || fileLimit > 20) {
        setError(new ApiRequestError("Maximum files must be a whole number from 1 to 20."));
        return;
      }
      if (prNumber !== undefined && (!Number.isInteger(prNumber) || prNumber < 1)) {
        setError(new ApiRequestError("Pull request number must be a positive whole number."));
        return;
      }
      void sendRequest({
        kind: "github",
        data: {
          repository_url: githubUrl.trim(),
          ...(prNumber !== undefined ? { pull_request_number: prNumber } : {}),
          max_files: fileLimit,
        },
      });
      return;
    }

    if (workspaceMode === "analyze") {
      const fileLimit = Number(maxFiles);
      if (!repositoryPath.trim()) {
        setError(new ApiRequestError("Enter a repository-relative path to analyze."));
        return;
      }
      if (!Number.isInteger(fileLimit) || fileLimit < 1 || fileLimit > 500) {
        setError(new ApiRequestError("Maximum files must be a whole number from 1 to 500."));
        return;
      }
      void sendRequest({
        kind: "analysis",
        data: { repository_path: repositoryPath.trim(), max_files: fileLimit },
      });
      return;
    }

    if (bugDescription.trim().length < 5) {
      setError(new ApiRequestError("Describe the reported behavior in at least 5 characters."));
      return;
    }
    if (sourceMode === "source" && !sourceCode.trim()) {
      setError(new ApiRequestError("Add Python source code to analyze."));
      return;
    }
    if (sourceMode === "repository" && !repositoryPath.trim()) {
      setError(new ApiRequestError("Enter a repository-relative Python file path."));
      return;
    }

    const request: VerifyRequest = {
      bug_description: bugDescription.trim(),
      execution_mode: "analysis_only",
      ...(sourceMode === "source"
        ? { source_code: sourceCode }
        : { repository_path: repositoryPath.trim() }),
      ...(unifiedDiff.trim() ? { unified_diff: unifiedDiff } : {}),
    };
    void sendRequest({ kind: "verification", data: request });
  }

  function resetWorkspace() {
    setBugDescription("");
    setSourceCode("");
    setRepositoryPath("");
    setUnifiedDiff("");
    setMaxFiles("100");
    setGithubMaxFiles("20");
    setGithubUrl("");
    setPullRequestNumber("");
    setShowDiff(false);
    setResult(null);
    setError(null);
    setRetryRequest(null);
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <a className="brand" href="/" aria-label="ProofGate AI home">
          <span className="brand-mark" aria-hidden="true">
            <BrandGlyph />
          </span>
          <span className="brand-copy">
            <strong>proofgate<span>ai</span></strong>
            <small>Evidence-first code review</small>
          </span>
        </a>
        <div className="header-meta">
          <span className="api-indicator"><span /> Analysis API</span>
          <a className="docs-link" href="http://127.0.0.1:8000/docs" target="_blank" rel="noreferrer">
            API docs <ArrowUpRight />
          </a>
        </div>
      </header>

      <main className="main-content">
        <section className="page-intro">
          <div>
            <div className="eyebrow"><span className="eyebrow-line" /> PROOF BEFORE CONFIDENCE</div>
            <h1>Review the evidence.<br /><span>Not just the change.</span></h1>
            <p className="intro-copy">
              Inspect Python source and patch structure with deterministic, read-only analysis.
            </p>
          </div>
          <div className="policy-chip"><span className="status-dot" /> POLICY <b>v1.0.1</b></div>
        </section>

        <section className="safety-banner" aria-label="Execution safety notice">
          <span className="safety-icon"><ShieldIcon /></span>
          <div>
            <strong>Analysis only — submitted code is never run</strong>
            <p>Syntax, diff, and narrow behavioral-pattern findings are not proof of runtime behavior. Reproduction and regression tests are skipped.</p>
          </div>
          <span className="safety-tag">NO EXECUTION</span>
        </section>

        <div className="workspace-tabs" role="tablist" aria-label="Workspace mode">
          <button
            type="button"
            role="tab"
            aria-selected={workspaceMode === "verify"}
            disabled={loading}
            className={workspaceMode === "verify" ? "workspace-tab active" : "workspace-tab"}
            onClick={() => { setWorkspaceMode("verify"); setResult(null); setError(null); }}
          >
            <ScanIcon /> Verify a change
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={workspaceMode === "analyze"}
            disabled={loading}
            className={workspaceMode === "analyze" ? "workspace-tab active" : "workspace-tab"}
            onClick={() => { setWorkspaceMode("analyze"); setResult(null); setError(null); }}
          >
            <FolderIcon /> Analyze repository
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={workspaceMode === "github"}
            disabled={loading}
            className={workspaceMode === "github" ? "workspace-tab active" : "workspace-tab"}
            onClick={() => { setWorkspaceMode("github"); setResult(null); setError(null); }}
          >
            <GithubIcon /> Inspect GitHub
          </button>
        </div>

        <div className="workspace-grid">
          <section className="panel request-panel" aria-labelledby="request-title">
            <div className="panel-heading">
              <div>
                <div className="section-kicker">REQUEST</div>
                <h2 id="request-title">
                  {workspaceMode === "verify"
                    ? "Describe the change"
                    : workspaceMode === "github"
                      ? "Inspect public GitHub content"
                      : "Choose what to inspect"}
                </h2>
              </div>
              <span className="step-label">01 <i>/</i> 02</span>
            </div>

            <form onSubmit={handleSubmit} noValidate>
              <fieldset disabled={loading} className="form-fields">
              {workspaceMode === "verify" && (
                <>
                  <label className="field-label" htmlFor="bug-description">
                    Reported behavior <span className="required">*</span>
                  </label>
                  <textarea
                    id="bug-description"
                    className="text-input bug-input"
                    value={bugDescription}
                    onChange={(event) => setBugDescription(event.target.value)}
                    placeholder="What should happen, and what happens instead?"
                    maxLength={1000}
                    required
                  />
                  <div className="field-meta"><span>Be specific about the expected behavior</span><span>{bugDescription.length}/1000</span></div>
                </>
              )}

              {workspaceMode === "github" && (
                <>
                  <label className="field-label" htmlFor="github-url">Public repository URL</label>
                  <input
                    id="github-url"
                    className="text-input"
                    type="url"
                    value={githubUrl}
                    onChange={(event) => setGithubUrl(event.target.value)}
                    placeholder="https://github.com/owner/repository"
                    maxLength={500}
                    required
                  />
                  <p className="field-hint">Only public github.com repository URLs are accepted. No authentication is used.</p>
                  <label className="field-label" htmlFor="pull-request-number">Pull request number <small>OPTIONAL</small></label>
                  <input
                    id="pull-request-number"
                    className="text-input number-input"
                    type="number"
                    min={1}
                    value={pullRequestNumber}
                    onChange={(event) => setPullRequestNumber(event.target.value)}
                    placeholder="Leave empty to inspect the default branch"
                  />
                  <div className="max-files-field">
                    <label className="field-label" htmlFor="github-max-files">Maximum files to inspect</label>
                    <input
                      id="github-max-files"
                      className="text-input number-input"
                      type="number"
                      min={1}
                      max={20}
                      value={githubMaxFiles}
                      onChange={(event) => setGithubMaxFiles(event.target.value)}
                    />
                  </div>
                  <p className="field-hint">GitHub content is untrusted input. Python syntax and diff structure are inspected only; repository code is never run.</p>
                </>
              )}

              {workspaceMode !== "github" && <div className="field-label source-label">
                {workspaceMode === "verify" ? "Code input" : "Repository path"}
              </div>}
              {workspaceMode === "verify" && (
                <div className="segmented" role="tablist" aria-label="Code input type">
                  <button
                    type="button"
                    role="tab"
                    aria-selected={sourceMode === "source"}
                    className={sourceMode === "source" ? "segment active" : "segment"}
                    onClick={() => setSourceMode("source")}
                  >Paste source</button>
                  <button
                    type="button"
                    role="tab"
                    aria-selected={sourceMode === "repository"}
                    className={sourceMode === "repository" ? "segment active" : "segment"}
                    onClick={() => setSourceMode("repository")}
                  >Repository file</button>
                </div>
              )}

              {workspaceMode !== "github" &&
                (workspaceMode === "analyze" || sourceMode === "repository") && (
                <>
                  <label className="sr-only" htmlFor="repository-path">Repository-relative Python path</label>
                  <div className="path-input-wrap">
                    <span className="path-prefix">./</span>
                    <input
                      id="repository-path"
                      className="text-input path-input"
                      value={repositoryPath}
                      onChange={(event) => setRepositoryPath(event.target.value)}
                      placeholder={workspaceMode === "analyze" ? "src/" : "src/module.py"}
                      maxLength={500}
                      required
                    />
                  </div>
                  <p className="field-hint">
                    {workspaceMode === "analyze"
                      ? 'Relative to the server-configured repository root. Use "." to inspect its files.'
                      : "Must resolve to one Python file under the server-configured repository root."}
                  </p>
                </>
              )}

              {workspaceMode === "verify" && sourceMode === "source" && (
                <>
                  <div className="code-toolbar">
                    <label className="field-label" htmlFor="source-code">Python source <span className="required">*</span></label>
                    <button type="button" className="text-button" onClick={() => setSourceCode(EXAMPLE_SOURCE)}>
                      <SparkIcon /> Load example
                    </button>
                  </div>
                  <div className="code-editor">
                    <div className="editor-topline"><span className="file-indicator" /> <span>source.py</span><span className="language-label">PYTHON</span></div>
                    <textarea
                      id="source-code"
                      className="code-input"
                      value={sourceCode}
                      onChange={(event) => setSourceCode(event.target.value)}
                      placeholder={"def your_function(value):\n    # Paste code to inspect\n    return value"}
                      maxLength={100000}
                      spellCheck={false}
                      autoCapitalize="off"
                      autoComplete="off"
                      autoCorrect="off"
                      aria-describedby="source-note"
                      required
                    />
                    <div className="editor-status"><span>Read-only analysis</span><span>{sourceCode.length.toLocaleString()} chars</span></div>
                  </div>
                  <p className="field-hint" id="source-note">Example is loaded as text only. It will not be executed.</p>
                </>
              )}

              {workspaceMode === "verify" && (
                <div className="optional-section">
                  <button
                    type="button"
                    className="optional-toggle"
                    aria-expanded={showDiff}
                    onClick={() => setShowDiff((current) => !current)}
                  >
                    <span><DiffIcon /> Unified diff <small>OPTIONAL</small></span>
                    <ChevronIcon open={showDiff} />
                  </button>
                  {showDiff && (
                    <textarea
                      className="text-input diff-input"
                      aria-label="Unified diff"
                      value={unifiedDiff}
                      onChange={(event) => setUnifiedDiff(event.target.value)}
                      placeholder={"--- a/module.py\n+++ b/module.py\n@@ -1 +1 @@\n-before()\n+after()"}
                      maxLength={200000}
                      spellCheck={false}
                    />
                  )}
                  {showDiff && <p className="field-hint">The backend checks diff structure; this does not establish a working fix.</p>}
                </div>
              )}

              {workspaceMode === "analyze" && (
                <div className="max-files-field">
                  <label className="field-label" htmlFor="max-files">Maximum Python files</label>
                  <input
                    id="max-files"
                    className="text-input number-input"
                    type="number"
                    min={1}
                    max={500}
                    value={maxFiles}
                    onChange={(event) => setMaxFiles(event.target.value)}
                  />
                </div>
              )}

              {workspaceMode === "github" && (
                <div className="github-readonly-note">
                  Read-only GitHub API access. This dashboard will not write to repositories, approve, comment, or merge.
                </div>
              )}

              {error && (
                <div className="error-box" role="alert">
                  <ErrorIcon />
                  <div><strong>Request not completed</strong>
                    {error.code && <p className="error-code">{error.code.replaceAll("_", " ")}</p>}
                    <p>{error.message}</p>
                    {error.fields.length > 0 && <p className="error-fields">Fields: {error.fields.join(", ")}</p>}
                  </div>
                {retryRequest &&
                  (error.status === undefined || error.status >= 500 || error.status === 429) && (
                  <button type="button" className="retry-button" onClick={() => void sendRequest(retryRequest)} disabled={loading}>
                    Retry <RetryIcon />
                  </button>
                  )}
                </div>
              )}

              <div className="form-actions">
                <button type="button" className="reset-button" onClick={resetWorkspace} disabled={loading}>
                  <ResetIcon /> Reset
                </button>
                <button type="submit" className="submit-button" disabled={loading}>
                  {loading
                    ? <><span className="spinner" /> {workspaceMode === "verify" ? "Analyzing..." : "Inspecting..."}</>
                    : <>{workspaceMode === "verify" ? "Analyze evidence" : workspaceMode === "github" ? "Inspect GitHub" : "Analyze repository"} <ArrowRight /></>}
                </button>
              </div>
              </fieldset>
            </form>
          </section>

          <section className="panel results-panel" aria-labelledby="results-title" aria-live="polite">
            <div className="panel-heading">
              <div>
                <div className="section-kicker">RESULT</div>
                <h2 id="results-title">Evidence overview</h2>
              </div>
              <span className="step-label">02 <i>/</i> 02</span>
            </div>
            {loading ? <LoadingState /> : result ? (
              result.kind === "verification"
                ? <VerificationView result={result.data} />
                : result.kind === "analysis"
                  ? <AnalysisView result={result.data} />
                  : <GitHubView result={result.data} />
            ) : <EmptyState />}
          </section>
        </div>

        <footer className="page-footer">
          <span>ProofGate AI <i>·</i> Deterministic by design</span>
          <span>Source and tests are never executed <span className="footer-dot" /></span>
        </footer>
      </main>
    </div>
  );
}

function VerificationView({ result }: { result: VerificationResult }) {
  const decision = DECISION_COPY[result.decision];
  return (
    <div className="result-content">
      <div className={`decision-card decision-${result.decision.toLowerCase()}`}>
        <div className="decision-topline">
          <span className="decision-symbol"><DecisionIcon decision={result.decision} /></span>
          <span className="decision-label">{decision.label}</span>
          <span className="policy-version">POLICY {result.policy_version}</span>
        </div>
        <p>{decision.description}</p>
        <div className="decision-summary">{result.summary}</div>
      </div>

      <div className="result-stats">
        <Stat label="CHECKS" value={String(result.checks.length).padStart(2, "0")} />
        <Stat label="PERFORMED" value={String(result.checks_performed.length).padStart(2, "0")} accent />
        <Stat label="SKIPPED" value={String(Object.keys(result.checks_skipped).length).padStart(2, "0")} muted />
        <Stat label="DURATION" value={`${result.duration_ms}ms`} />
      </div>

      {result.reasons.length > 0 && (
        <div className="reason-list">
          {result.reasons.map((reason, index) => <p key={`${reason}-${index}`}><span>i</span>{reason}</p>)}
        </div>
      )}

      {result.behavioral_findings.length > 0 && (
        <section className="behavioral-findings" aria-labelledby="behavioral-findings-title">
          <div className="subsection-heading">
            <h3 id="behavioral-findings-title">Behavioral pattern analysis</h3>
            <span>Deterministic AST rule</span>
          </div>
          {result.behavioral_findings.map((finding, index) => (
            <article
              className={`behavioral-finding finding-${finding.finding_type.toLowerCase()}`}
              key={`${finding.rule_id}-${finding.function_name ?? "unsupported"}-${index}`}
            >
              <div className="behavioral-finding-heading">
                <strong>{finding.finding_type.replaceAll("_", " ")}</strong>
                <code>{finding.rule_id}</code>
              </div>
              <p>{finding.message}</p>
              {(finding.function_name || finding.source_line !== null) && (
                <div className="behavioral-finding-meta">
                  {finding.function_name && <span>Function <code>{finding.function_name}</code></span>}
                  {finding.source_line !== null && <span>Line {finding.source_line}</span>}
                </div>
              )}
              {finding.detected_operator && finding.expected_operator && (
                <div className="behavioral-operator-comparison">
                  <span>Detected <b>{finding.detected_operator}</b></span>
                  <span>Expected <b>{finding.expected_operator}</b></span>
                </div>
              )}
              <small>
                This rule only checks explicitly stated add/subtract requirements against a
                two-argument function with one direct return expression. It does not prove
                runtime behavior or assess the rest of the program.
              </small>
            </article>
          ))}
        </section>
      )}

      <div className="subsection-heading"><h3>Checks</h3><span>{result.checks.length} recorded</span></div>
      <div className="check-list">
        {result.checks.map((check) => <CheckCard check={check} key={`${check.name}-${check.category}`} />)}
      </div>

      {Object.keys(result.checks_skipped).length > 0 && (
        <div className="skipped-block">
          <div className="subsection-heading"><h3>Checks skipped</h3><span>Not counted as passes</span></div>
          {Object.entries(result.checks_skipped).map(([name, reason]) => (
            <div className="skipped-row" key={name}><span>{name.replaceAll("_", " ")}</span><p>{reason}</p></div>
          ))}
        </div>
      )}

      <div className="subsection-heading evidence-heading"><h3>Evidence records</h3><span>{result.evidence.length} records</span></div>
      {result.evidence.length === 0
        ? <p className="no-evidence">The API returned no evidence records.</p>
        : <div className="evidence-list">{result.evidence.map((item) => <EvidenceCard item={item} key={item.evidence_id} />)}</div>}
      <div className="result-id">VERIFICATION ID <code>{result.verification_id}</code></div>
    </div>
  );
}

function CheckCard({ check }: { check: CheckResult }) {
  return (
    <details className={`check-card status-${check.status}`}>
      <summary>
        <span className={`check-indicator status-${check.status}`}><StatusIcon status={check.status} /></span>
        <span className="check-name">{check.name.replaceAll("_", " ")}</span>
        {check.required && <span className="required-pill">REQUIRED</span>}
        <span className={`status-pill status-${check.status}`}>{check.status}</span>
        <ChevronIcon />
      </summary>
      <div className="check-details">
        <p>{check.message}</p>
        <div className="check-meta"><span>{check.category.replaceAll("_", " ")}</span>{check.duration_ms !== null && <span>{check.duration_ms} ms</span>}</div>
        {Object.keys(check.details).length > 0 && <pre>{JSON.stringify(check.details, null, 2)}</pre>}
      </div>
    </details>
  );
}

function EvidenceCard({ item }: { item: EvidenceRecord }) {
  return (
    <article className="evidence-card">
      <div className="evidence-card-top">
        <span className={`evidence-outcome outcome-${item.outcome}`}>{item.outcome}</span>
        <span>{item.category.replaceAll("_", " ")}</span>
        {item.duration_ms !== null && <span>{item.duration_ms} ms</span>}
      </div>
      <p>{item.message}</p>
      {Object.keys(item.details).length > 0 && <pre>{JSON.stringify(item.details, null, 2)}</pre>}
      <time dateTime={item.timestamp}>{formatTimestamp(item.timestamp)}</time>
    </article>
  );
}

function AnalysisView({ result }: { result: AnalysisResult }) {
  return (
    <div className="result-content">
      <div className="analysis-summary-card">
        <span className="analysis-icon"><FolderIcon /></span>
        <div><strong>Read-only analysis complete</strong><p>Files were inspected as text and parsed; no project code was executed.</p></div>
      </div>
      <div className="result-stats analysis-stats">
        <Stat label="FILES" value={String(result.file_count).padStart(2, "0")} />
        <Stat label="PYTHON" value={String(result.python_file_count).padStart(2, "0")} accent />
        <Stat label="SYNTAX ERRORS" value={String(result.syntax_error_count).padStart(2, "0")} muted={result.syntax_error_count === 0} />
        <Stat label="TRUNCATED" value={result.truncated ? "YES" : "NO"} />
      </div>
      <div className="analysis-root">ROOT <code>{result.root_path}</code>{result.truncated && <span>Result limit reached</span>}</div>
      {result.files.length === 0 ? <div className="no-evidence">No Python files were returned for this path.</div> : (
        <div className="file-results">
          {result.files.map((file) => (
            <AnalysisFileCard file={file} key={file.path} />
          ))}
        </div>
      )}
      {result.analyzed_paths.length > 0 && <div className="analyzed-paths"><strong>Analyzed paths</strong><p>{result.analyzed_paths.join(" · ")}</p></div>}
    </div>
  );
}

function GitHubView({ result }: { result: GitHubInspectionResult }) {
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const decision = DECISION_COPY[result.decision];
  const syntaxErrors = result.files.filter(
    (file) => file.analysis?.syntax_valid === false,
  ).length;
  const selectedFile =
    result.files.find((file) => file.path === selectedPath) ?? result.files[0] ?? null;
  const selectedEvidence = selectedFile
    ? result.evidence.filter((item) => item.details.path === selectedFile.path)
    : [];

  return (
    <div className="result-content">
      <div className={`decision-card decision-${result.decision.toLowerCase()}`}>
        <div className="decision-topline">
          <span className="decision-symbol"><DecisionIcon decision={result.decision} /></span>
          <span className="decision-label">{decision.label}</span>
          <span className="policy-version">POLICY {result.policy_version}</span>
        </div>
        <p>{decision.description}</p>
        <div className="decision-summary">
          GitHub content was inspected statically. This result does not establish runtime correctness.
        </div>
      </div>

      <div className="github-repository-card">
        <div>
          <span className="section-kicker">PUBLIC REPOSITORY</span>
          <a href={result.repository.url} target="_blank" rel="noreferrer">
            {result.repository.full_name} <ArrowUpRight />
          </a>
          <p>Default branch: <code>{result.repository.default_branch}</code></p>
          {result.repository.revision && <p>Commit: <code>{result.repository.revision}</code></p>}
        </div>
        {result.pull_request && (
          <div className="github-pr-meta">
            <span>PULL REQUEST #{result.pull_request.number} · {result.pull_request.state}</span>
            <a href={result.pull_request.url} target="_blank" rel="noreferrer">
              {result.pull_request.title} <ArrowUpRight />
            </a>
            <p>
              {result.pull_request.base_branch} ← {result.pull_request.head_branch} ·{" "}
              {result.pull_request.changed_file_count} changed files
            </p>
            <p>Base <code>{result.pull_request.base_sha}</code> · Head <code>{result.pull_request.head_sha}</code></p>
          </div>
        )}
      </div>

      <div className="result-stats analysis-stats">
        <Stat
          label={result.pull_request ? "CHANGED FILES" : "PYTHON FILES"}
          value={String(result.pull_request?.changed_file_count ?? result.files.length).padStart(2, "0")}
          accent
        />
        <Stat label="SYNTAX ERRORS" value={String(syntaxErrors).padStart(2, "0")} muted={syntaxErrors === 0} />
        <Stat label="COVERAGE" value={result.coverage_complete ? "COMPLETE" : "PARTIAL"} muted={!result.coverage_complete} />
        <Stat label="RUNTIME TESTS" value="NOT RUN" muted />
      </div>
      {result.pull_request && (
        <p className="github-file-count">
          Showing {result.files.length} returned file records of {result.pull_request.changed_file_count} changed files.
        </p>
      )}

      {!result.coverage_complete && (
        <div className="github-coverage-warning" role="status">
          <strong>Inspection is incomplete</strong>
          {result.coverage_messages.map((message, index) => <p key={`${message}-${index}`}>{message}</p>)}
        </div>
      )}

      {result.decision_reasons.map((reason, index) => (
        <p className="github-policy-reason" key={`${reason}-${index}`}>{reason}</p>
      ))}

      <div className="subsection-heading">
        <h3>{result.pull_request ? "Changed files" : "Python files"}</h3>
        <span>{result.pull_request ? "Select a file to inspect its diff and findings" : "Default-branch snapshot · not patch verification"}</span>
      </div>
      {result.files.length === 0 ? (
        <div className="no-evidence">
          {result.pull_request
            ? "No valid changed-file records were returned."
            : "No supported Python files were returned for inspection."}
        </div>
      ) : (
        <div className="github-file-review">
          <nav className="github-file-list" aria-label="Files returned by GitHub">
            {result.files.map((file) => {
              const status = githubFileStatus(file);
              return (
                <button
                  className={`github-file-option${selectedFile?.path === file.path ? " selected" : ""}`}
                  type="button"
                  aria-pressed={selectedFile?.path === file.path}
                  key={file.path}
                  onClick={() => setSelectedPath(file.path)}
                >
                  <span className={`file-status status-${status}`}><StatusIcon status={status} /></span>
                  <span className="github-file-option-copy">
                    <code>{file.path}</code>
                    <small>
                      {result.pull_request
                        ? `${file.change_status} · +${file.additions} / −${file.deletions}`
                        : file.file_type}
                    </small>
                  </span>
                  <span className={`status-pill status-${status}`}>{status}</span>
                </button>
              );
            })}
          </nav>
          {selectedFile && (
            <section className="github-selected-file" aria-label={`Review ${selectedFile.path}`}>
              <div className="github-selected-heading">
                <div>
                  <span className="section-kicker">
                    {selectedFile.file_type === "python"
                      ? "PYTHON SOURCE"
                      : selectedFile.file_type === "unsupported"
                        ? "UNSUPPORTED SOURCE TYPE"
                        : "FILE STATUS UNKNOWN"}
                  </span>
                  <h4>{selectedFile.path}</h4>
                </div>
                {result.pull_request && (
                  <span className="github-change-count">
                    {selectedFile.change_status} · +{selectedFile.additions} / −{selectedFile.deletions}
                  </span>
                )}
              </div>
              <p className="github-file-message">{selectedFile.message}</p>
              {result.pull_request && (
                <div className={`github-patch-status patch-${selectedFile.patch_status}`}>
                  <strong>Patch: {githubPatchStatus(selectedFile.patch_status)}</strong>
                  {selectedFile.patch_status === "missing" && (
                    <p>
                      GitHub may omit patches for binary or unavailable diffs; this API response does not identify which.
                    </p>
                  )}
                  {selectedFile.diff_diagnostics.map((message, index) => (
                    <p key={`${message}-${index}`}>{message}</p>
                  ))}
                  {selectedFile.diff_lines_truncated && (
                    <p>Structured line locations were capped. The available patch below is not truncated.</p>
                  )}
                </div>
              )}
              <div className="github-file-findings">
                <div className="subsection-heading">
                  <h5>Static syntax analysis</h5>
                  <span>Python parser only</span>
                </div>
                {selectedFile.analysis ? (
                  <>
                    <p>
                      Analyzer result:{" "}
                      <strong>
                        {selectedFile.analysis.syntax_valid === true
                          ? "syntax valid"
                          : selectedFile.analysis.syntax_valid === false
                            ? "syntax invalid"
                            : "syntax not determined"}
                      </strong>
                      {" · "}status: {selectedFile.analysis.status}
                    </p>
                    {selectedFile.analysis.diagnostics.length > 0 ? (
                      selectedFile.analysis.diagnostics.map((diagnostic, index) => (
                        <p className="diagnostic" key={`${diagnostic.line}-${diagnostic.column}-${index}`}>
                          <span className="finding-category">Python syntax</span>
                          {diagnostic.line !== null && (
                            <code>
                              line {diagnostic.line}
                              {diagnostic.column !== null ? `:${diagnostic.column}` : ""}
                            </code>
                          )}
                          {diagnostic.message}
                        </p>
                      ))
                    ) : (
                      <p>No syntax diagnostics were returned. Syntax validity is not semantic or runtime proof.</p>
                    )}
                  </>
                ) : (
                  <p>
                    {selectedFile.file_type === "unsupported"
                      ? "This file type is not parsed by the Python syntax analyzer."
                      : "No Python source analysis result is available for this file."}
                  </p>
                )}
              </div>
              {selectedFile.patch !== null && (
                <div className="github-diff-section">
                  <div className="subsection-heading">
                    <h5>Available diff</h5>
                    <span>Patch line · old line · new line</span>
                  </div>
                  <GitHubDiff patch={selectedFile.patch} file={selectedFile} />
                </div>
              )}
              {selectedEvidence.length > 0 && (
                <div className="github-file-evidence">
                  <div className="subsection-heading">
                    <h5>Evidence for this file</h5>
                    <span>{selectedEvidence.length} records</span>
                  </div>
                  {selectedEvidence.map((item) => (
                    <EvidenceCard item={item} key={item.evidence_id} />
                  ))}
                </div>
              )}
            </section>
          )}
        </div>
      )}

      <div className="subsection-heading evidence-heading">
        <h3>Analysis evidence</h3>
        <span>{result.evidence.length} static records · no runtime evidence</span>
      </div>
      {result.evidence.length === 0 ? (
        <p className="no-evidence">The API returned no static analysis evidence records.</p>
      ) : (
        <div className="evidence-list">
          {result.evidence.map((item) => (
            <EvidenceCard item={item} key={item.evidence_id} />
          ))}
        </div>
      )}
    </div>
  );
}

function githubFileStatus(file: GitHubInspectionResult["files"][number]): string {
  if (file.status === "error") return "error";
  if (file.status === "skipped") return "skipped";
  if (file.analysis?.syntax_valid === true) return "passed";
  if (file.analysis?.syntax_valid === false) return "failed";
  return "inconclusive";
}

function githubPatchStatus(status: GitHubInspectionResult["files"][number]["patch_status"]): string {
  switch (status) {
    case "available": return "available and structurally valid";
    case "missing": return "missing from GitHub response";
    case "oversized": return "omitted due to configured size limit";
    case "incomplete": return "incomplete (truncated hunk)";
    case "invalid": return "invalid structure";
    case "not_applicable": return "not applicable";
  }
}

function GitHubDiff({
  patch,
  file,
}: {
  patch: string;
  file: GitHubInspectionResult["files"][number];
}) {
  const patchLines = patch.split(/\r\n|\n|\r/);
  if (patchLines[patchLines.length - 1] === "") patchLines.pop();
  const locations = new Map(file.diff_lines.map((line) => [line.diff_line, line]));

  return (
    <div className="github-diff" role="region" aria-label={`Diff for ${file.path}`} tabIndex={0}>
      {patchLines.map((text, index) => {
        const patchLine = index + 1;
        const location = locations.get(patchLine);
        const kind = location?.kind ?? (text.startsWith("@@ ") ? "hunk" : "metadata");
        return (
          <div className={`github-diff-line diff-${kind}`} key={`${patchLine}-${text}`}>
            <span className="diff-number">{patchLine}</span>
            <span className="diff-number">{location?.old_line ?? ""}</span>
            <span className="diff-number">{location?.new_line ?? ""}</span>
            <code>{text || " "}</code>
          </div>
        );
      })}
    </div>
  );
}

function AnalysisFileCard({ file }: { file: AnalysisResult["files"][number] }) {
  const checkStatus =
    file.status === "skipped"
      ? "skipped"
      : file.status === "analyzed" && file.syntax_valid === true
        ? "passed"
        : file.status === "analyzed" && file.syntax_valid === false
          ? "failed"
          : "inconclusive";
  const statusLabel =
    file.status === "analyzed" && file.syntax_valid === null
      ? "syntax unknown"
      : file.syntax_valid === false
        ? "syntax error"
        : file.status;

  return (
    <details className="file-card">
      <summary>
        <span className={`file-status status-${checkStatus}`}><StatusIcon status={checkStatus} /></span>
        <code>{file.path}</code>
        <span className={`status-pill status-${checkStatus}`}>{statusLabel}</span>
        <ChevronIcon />
      </summary>
      <div className="file-detail">
        {file.size_bytes !== null && <p>{file.size_bytes.toLocaleString()} bytes</p>}
        {file.diagnostics.map((diagnostic, index) => (
          <p className="diagnostic" key={`${diagnostic.line}-${index}`}>
            {diagnostic.line !== null && <code>line {diagnostic.line}{diagnostic.column !== null ? `:${diagnostic.column}` : ""} — </code>}
            {diagnostic.message}
          </p>
        ))}
        {file.diagnostics.length === 0 && <p>No diagnostics.</p>}
      </div>
    </details>
  );
}

function EmptyState() {
  return (
    <div className="empty-state">
      <div className="empty-art"><span><FileSearchIcon /></span><i className="art-line line-one" /><i className="art-line line-two" /><i className="art-node" /></div>
      <span className="empty-kicker">AWAITING INPUT</span>
      <h3>Evidence starts with<br />a clear question.</h3>
      <p>Submit source or a repository path to inspect the backend’s actual analysis and policy result.</p>
      <div className="empty-note"><ShieldIcon /> No code will be executed</div>
    </div>
  );
}

function LoadingState() {
  return (
    <div className="loading-state">
      <span className="loading-orbit"><span /></span>
      <strong>Collecting safe evidence</strong>
      <p>Parsing inputs and waiting for the ProofGate API…</p>
      <span className="loading-caption">READ-ONLY · NO CODE EXECUTION</span>
    </div>
  );
}

function Stat({ label, value, accent = false, muted = false }: { label: string; value: string; accent?: boolean; muted?: boolean }) {
  return <div className={`stat ${accent ? "stat-accent" : ""} ${muted ? "stat-muted" : ""}`}><span>{label}</span><strong>{value}</strong></div>;
}

function StatusIcon({ status }: { status: string }) {
  if (status === "passed" || status === "analyzed") return <CheckGlyph />;
  if (status === "failed" || status === "error") return <CrossGlyph />;
  if (status === "skipped") return <MinusGlyph />;
  return <QuestionGlyph />;
}

function DecisionIcon({ decision }: { decision: Decision }) {
  if (decision === "VERIFIED") return <CheckGlyph />;
  if (decision === "NOT_REPRODUCED") return <MinusGlyph />;
  return <QuestionGlyph />;
}

function formatTimestamp(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function BrandGlyph() { return <svg viewBox="0 0 32 32" fill="none"><path d="M16 3.5 27 8v7.1c0 7.1-4.7 11.6-11 13.4C9.7 26.7 5 22.2 5 15.1V8l11-4.5Z" stroke="currentColor" strokeWidth="1.7"/><path d="m11.5 15.7 3 3 6.5-6.7" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"/></svg>; }
function ArrowRight() { return <svg viewBox="0 0 18 18" fill="none" aria-hidden="true"><path d="M3 9h11M9 4l5 5-5 5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg>; }
function ArrowUpRight() { return <svg viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="M4 12 12 4M5 4h7v7" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round"/></svg>; }
function ShieldIcon() { return <svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="m10 2 7 3v4.5c0 4.6-2.9 7.5-7 8.5-4.1-1-7-3.9-7-8.5V5l7-3Z" stroke="currentColor" strokeWidth="1.5"/><path d="m7 9.7 2 2 4-4.2" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg>; }
function ScanIcon() { return <svg viewBox="0 0 18 18" fill="none" aria-hidden="true"><path d="M6 2.5H3.5v3M12 2.5h2.5v3M15 12.5v3H12M3.5 12.5v3H6M5.5 9h7" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round"/></svg>; }
function FolderIcon() { return <svg viewBox="0 0 18 18" fill="none" aria-hidden="true"><path d="M2.5 5.5a1 1 0 0 1 1-1h4l1.5 1.5h5.5a1 1 0 0 1 1 1v6.5a1 1 0 0 1-1 1h-11a1 1 0 0 1-1-1v-8Z" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round"/></svg>; }
function GithubIcon() { return <svg viewBox="0 0 18 18" fill="none" aria-hidden="true"><circle cx="5" cy="4" r="2" stroke="currentColor" strokeWidth="1.4"/><circle cx="13" cy="5" r="2" stroke="currentColor" strokeWidth="1.4"/><circle cx="9" cy="14" r="2" stroke="currentColor" strokeWidth="1.4"/><path d="M7 4.5 11 4.8M5.8 5.8l2.1 6.3m4-5.3-2.1 5.3" stroke="currentColor" strokeWidth="1.3"/></svg>; }
function SparkIcon() { return <svg viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="m8 1.8 1.4 4.8L14 8l-4.6 1.4L8 14.2l-1.4-4.8L2 8l4.6-1.4L8 1.8Z" stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round"/></svg>; }
function DiffIcon() { return <svg viewBox="0 0 18 18" fill="none" aria-hidden="true"><path d="M5 3v12M13 3v12M2.5 6h5M10.5 12h5M6 4.5 7.5 6 6 7.5M12 10.5 10.5 12 12 13.5" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round"/></svg>; }
function ChevronIcon({ open = false }: { open?: boolean }) { return <svg className={open ? "chevron open" : "chevron"} viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="m4 6 4 4 4-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg>; }
function ErrorIcon() { return <svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><circle cx="10" cy="10" r="7.5" stroke="currentColor" strokeWidth="1.5"/><path d="M10 6v4.5M10 13.5v.1" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/></svg>; }
function RetryIcon() { return <svg viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="M13 6a5.3 5.3 0 0 0-9.5-1L2.5 7M2.5 4v3h3M3 10a5.3 5.3 0 0 0 9.5 1l1-2M13.5 12V9h-3" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round"/></svg>; }
function ResetIcon() { return <svg viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="M3 4.5h10M6 4.5V3h4v1.5m2.5 0-.5 8H4l-.5-8M6.5 7v3.5M9.5 7v3.5" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round"/></svg>; }
function CheckGlyph() { return <svg viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="m3.5 8.2 3 3 6-6.3" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"/></svg>; }
function CrossGlyph() { return <svg viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="m4.5 4.5 7 7m0-7-7 7" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/></svg>; }
function MinusGlyph() { return <svg viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="M3.5 8h9" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/></svg>; }
function QuestionGlyph() { return <svg viewBox="0 0 16 16" fill="none" aria-hidden="true"><circle cx="8" cy="8" r="5.8" stroke="currentColor" strokeWidth="1.3"/><path d="M6.5 6.1a1.6 1.6 0 1 1 2.7 1.2c-.7.6-1.2.8-1.2 1.8M8 11.3v.1" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round"/></svg>; }
function FileSearchIcon() { return <svg viewBox="0 0 34 34" fill="none" aria-hidden="true"><path d="M9 4.5h10l7 7v16a2 2 0 0 1-2 2H9a2 2 0 0 1-2-2v-21a2 2 0 0 1 2-2Z" stroke="currentColor" strokeWidth="1.5"/><path d="M19 5v7h7M11 17h7m-7 4h4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/><circle cx="22" cy="22" r="3.2" stroke="currentColor" strokeWidth="1.4"/><path d="m24.5 24.5 2.3 2.3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/></svg>; }

export default App;
