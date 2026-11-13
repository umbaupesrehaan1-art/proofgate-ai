export type Decision =
  | "VERIFIED"
  | "NOT_REPRODUCED"
  | "INSUFFICIENT_EVIDENCE";

export type CheckStatus = "passed" | "failed" | "skipped" | "inconclusive";

export interface CheckResult {
  name: string;
  category: string;
  status: CheckStatus;
  message: string;
  required: boolean;
  details: Record<string, unknown>;
  duration_ms: number | null;
}

export interface EvidenceRecord {
  evidence_id: string;
  category: string;
  outcome: "pass" | "fail" | "inconclusive";
  message: string;
  details: Record<string, unknown>;
  timestamp: string;
  duration_ms: number | null;
}

export interface BehavioralFinding {
  finding_type:
    | "POTENTIAL_BEHAVIOR_MISMATCH"
    | "NO_MISMATCH_DETECTED"
    | "UNSUPPORTED_REQUIREMENT"
    | "UNSUPPORTED_EXPRESSION"
    | "INVALID_SYNTAX";
  rule_id: string;
  function_name: string | null;
  detected_operator: "addition" | "subtraction" | null;
  expected_operator: "addition" | "subtraction" | null;
  source_line: number | null;
  message: string;
}

export interface VerificationResult {
  verification_id: string;
  decision: Decision;
  summary: string;
  evidence: EvidenceRecord[];
  behavioral_findings: BehavioralFinding[];
  checks: CheckResult[];
  checks_performed: string[];
  checks_skipped: Record<string, string>;
  reasons: string[];
  duration_ms: number;
  policy_version: string;
}

export interface SyntaxDiagnostic {
  line: number | null;
  column: number | null;
  message: string;
}

export interface AnalysisFileResult {
  path: string;
  syntax_valid: boolean | null;
  diagnostics: SyntaxDiagnostic[];
  size_bytes: number | null;
  status: "analyzed" | "skipped" | "error";
}

export interface AnalysisResult {
  root_path: string;
  file_count: number;
  python_file_count: number;
  syntax_error_count: number;
  analyzed_paths: string[];
  files: AnalysisFileResult[];
  truncated: boolean;
}

export interface ApiErrorBody {
  error: string;
  message: string;
  request_id?: string | null;
  fields?: string[];
}

export interface VerifyRequest {
  bug_description: string;
  source_code?: string;
  repository_path?: string;
  unified_diff?: string;
  execution_mode: "analysis_only";
}

export interface AnalyzeRequest {
  repository_path: string;
  max_files: number;
}

export interface GitHubInspectionRequest {
  repository_url: string;
  pull_request_number?: number;
  max_files: number;
}

export interface GitHubInspectionFile {
  path: string;
  change_status: string;
  additions: number;
  deletions: number;
  patch: string | null;
  diff_valid: boolean | null;
  patch_status:
    | "not_applicable"
    | "available"
    | "missing"
    | "oversized"
    | "incomplete"
    | "invalid";
  file_type: "python" | "unsupported" | "unknown";
  diff_lines: GitHubDiffLine[];
  diff_lines_truncated: boolean;
  diff_diagnostics: string[];
  analysis: AnalysisFileResult | null;
  status: "analyzed" | "skipped" | "error";
  message: string;
}

export interface GitHubDiffLine {
  diff_line: number;
  kind: "context" | "addition" | "deletion";
  old_line: number | null;
  new_line: number | null;
}

export interface GitHubInspectionResult {
  repository: {
    full_name: string;
    url: string;
    default_branch: string;
    revision: string | null;
  };
  pull_request: {
    number: number;
    title: string;
    state: string;
    url: string;
    base_branch: string;
    head_branch: string;
    base_sha: string;
    head_sha: string;
    changed_file_count: number;
  } | null;
  files: GitHubInspectionFile[];
  evidence: EvidenceRecord[];
  coverage_complete: boolean;
  coverage_messages: string[];
  decision: Decision;
  decision_reasons: string[];
  policy_version: string;
}
