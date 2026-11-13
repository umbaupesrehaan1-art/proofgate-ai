import type {
  AnalysisResult,
  ApiErrorBody,
  GitHubInspectionRequest,
  GitHubInspectionResult,
  VerifyRequest,
  VerificationResult,
} from "./types";

const configuredApiUrl = import.meta.env.VITE_PROOFGATE_API_URL?.trim();
const apiBase = (configuredApiUrl || "/api").replace(/\/+$/, "");

export class ApiRequestError extends Error {
  constructor(
    message: string,
    readonly status?: number,
    readonly fields: string[] = [],
    readonly code?: string,
  ) {
    super(message);
    this.name = "ApiRequestError";
  }
}

async function postJson<T>(
  endpoint: string,
  body: unknown,
  isExpected: (value: unknown) => value is T,
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${apiBase}${endpoint}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    throw new ApiRequestError(
      "Could not reach the ProofGate API. Check that the backend is running and try again.",
    );
  }

  let result: unknown;
  try {
    result = await response.json();
  } catch {
    throw new ApiRequestError(
      "The API returned an unreadable response. Please retry the request.",
      response.status,
    );
  }

  if (!response.ok) {
    const error = isApiError(result) ? result : undefined;
    throw new ApiRequestError(
      error?.message ?? `The API request failed with HTTP ${response.status}.`,
      response.status,
      error?.fields ?? [],
      error?.error,
    );
  }
  if (!isExpected(result)) {
    throw new ApiRequestError(
      "The API response did not match the expected ProofGate result format.",
      response.status,
    );
  }
  return result;
}

function isApiError(value: unknown): value is ApiErrorBody {
  return (
    isRecord(value) &&
    typeof value.error === "string" &&
    typeof value.message === "string" &&
    (value.fields === undefined ||
      (Array.isArray(value.fields) && value.fields.every((field) => typeof field === "string")))
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

function isCheckResult(value: unknown): boolean {
  return (
    isRecord(value) &&
    typeof value.name === "string" &&
    typeof value.category === "string" &&
    ["passed", "failed", "skipped", "inconclusive"].includes(String(value.status)) &&
    typeof value.message === "string" &&
    typeof value.required === "boolean" &&
    isRecord(value.details) &&
    (value.duration_ms === null || typeof value.duration_ms === "number")
  );
}

function isEvidenceRecord(value: unknown): boolean {
  return (
    isRecord(value) &&
    typeof value.evidence_id === "string" &&
    typeof value.category === "string" &&
    ["pass", "fail", "inconclusive"].includes(String(value.outcome)) &&
    typeof value.message === "string" &&
    isRecord(value.details) &&
    typeof value.timestamp === "string" &&
    (value.duration_ms === null || typeof value.duration_ms === "number")
  );
}

function isBehavioralFinding(value: unknown): boolean {
  return (
    isRecord(value) &&
    [
      "POTENTIAL_BEHAVIOR_MISMATCH",
      "NO_MISMATCH_DETECTED",
      "UNSUPPORTED_REQUIREMENT",
      "UNSUPPORTED_EXPRESSION",
      "INVALID_SYNTAX",
    ].includes(String(value.finding_type)) &&
    typeof value.rule_id === "string" &&
    (value.function_name === null || typeof value.function_name === "string") &&
    (value.detected_operator === null ||
      value.detected_operator === "addition" ||
      value.detected_operator === "subtraction") &&
    (value.expected_operator === null ||
      value.expected_operator === "addition" ||
      value.expected_operator === "subtraction") &&
    (value.source_line === null || typeof value.source_line === "number") &&
    typeof value.message === "string"
  );
}

function isVerificationResult(value: unknown): value is VerificationResult {
  return (
    isRecord(value) &&
    typeof value.verification_id === "string" &&
    ["VERIFIED", "NOT_REPRODUCED", "INSUFFICIENT_EVIDENCE"].includes(
      String(value.decision),
    ) &&
    typeof value.summary === "string" &&
    Array.isArray(value.evidence) &&
    value.evidence.every(isEvidenceRecord) &&
    Array.isArray(value.behavioral_findings) &&
    value.behavioral_findings.every(isBehavioralFinding) &&
    Array.isArray(value.checks) &&
    value.checks.every(isCheckResult) &&
    isStringArray(value.checks_performed) &&
    isRecord(value.checks_skipped) &&
    Object.values(value.checks_skipped).every((reason) => typeof reason === "string") &&
    isStringArray(value.reasons) &&
    typeof value.duration_ms === "number" &&
    typeof value.policy_version === "string"
  );
}

function isAnalysisResult(value: unknown): value is AnalysisResult {
  return (
    isRecord(value) &&
    typeof value.root_path === "string" &&
    typeof value.file_count === "number" &&
    typeof value.python_file_count === "number" &&
    typeof value.syntax_error_count === "number" &&
    isStringArray(value.analyzed_paths) &&
    Array.isArray(value.files) &&
    value.files.every(
      (file) =>
        isRecord(file) &&
        typeof file.path === "string" &&
        (file.syntax_valid === null || typeof file.syntax_valid === "boolean") &&
        Array.isArray(file.diagnostics) &&
        file.diagnostics.every(
          (diagnostic) =>
            isRecord(diagnostic) &&
            (diagnostic.line === null || typeof diagnostic.line === "number") &&
            (diagnostic.column === null || typeof diagnostic.column === "number") &&
            typeof diagnostic.message === "string",
        ) &&
        (file.size_bytes === null || typeof file.size_bytes === "number") &&
        ["analyzed", "skipped", "error"].includes(String(file.status)),
    ) &&
    typeof value.truncated === "boolean"
  );
}

function isGitHubInspectionResult(value: unknown): value is GitHubInspectionResult {
  return (
    isRecord(value) &&
    isRecord(value.repository) &&
    typeof value.repository.full_name === "string" &&
    typeof value.repository.url === "string" &&
    typeof value.repository.default_branch === "string" &&
    (value.repository.revision === null || typeof value.repository.revision === "string") &&
    (value.pull_request === null ||
      (isRecord(value.pull_request) &&
        typeof value.pull_request.number === "number" &&
        typeof value.pull_request.title === "string" &&
        typeof value.pull_request.state === "string" &&
        typeof value.pull_request.url === "string" &&
        typeof value.pull_request.base_branch === "string" &&
        typeof value.pull_request.head_branch === "string" &&
        typeof value.pull_request.base_sha === "string" &&
        typeof value.pull_request.head_sha === "string" &&
        typeof value.pull_request.changed_file_count === "number")) &&
    Array.isArray(value.files) &&
    value.files.every(
      (file) =>
        isRecord(file) &&
        typeof file.path === "string" &&
        typeof file.change_status === "string" &&
        typeof file.additions === "number" &&
        typeof file.deletions === "number" &&
        (file.patch === null || typeof file.patch === "string") &&
        (file.diff_valid === null || typeof file.diff_valid === "boolean") &&
        (file.analysis === null ||
          (isRecord(file.analysis) &&
            typeof file.analysis.path === "string" &&
            (file.analysis.syntax_valid === null ||
              typeof file.analysis.syntax_valid === "boolean") &&
            Array.isArray(file.analysis.diagnostics) &&
            file.analysis.diagnostics.every(
              (diagnostic) =>
                isRecord(diagnostic) &&
                (diagnostic.line === null || typeof diagnostic.line === "number") &&
                (diagnostic.column === null || typeof diagnostic.column === "number") &&
                typeof diagnostic.message === "string",
            ) &&
            (file.analysis.size_bytes === null ||
              typeof file.analysis.size_bytes === "number") &&
            ["analyzed", "skipped", "error"].includes(String(file.analysis.status)))) &&
        ["analyzed", "skipped", "error"].includes(String(file.status)) &&
        typeof file.message === "string",
    ) &&
    Array.isArray(value.evidence) &&
    value.evidence.every(isEvidenceRecord) &&
    typeof value.coverage_complete === "boolean" &&
    isStringArray(value.coverage_messages) &&
    ["VERIFIED", "NOT_REPRODUCED", "INSUFFICIENT_EVIDENCE"].includes(
      String(value.decision),
    ) &&
    isStringArray(value.decision_reasons) &&
    typeof value.policy_version === "string"
  );
}

export function verifyChange(request: VerifyRequest): Promise<VerificationResult> {
  return postJson("/v1/verify", request, isVerificationResult);
}

export function analyzeRepository(
  request: { repository_path: string; max_files: number },
): Promise<AnalysisResult> {
  return postJson("/v1/analyze", request, isAnalysisResult);
}

export function inspectGitHubRepository(
  request: GitHubInspectionRequest,
): Promise<GitHubInspectionResult> {
  return postJson("/v1/github/inspect", request, isGitHubInspectionResult);
}
