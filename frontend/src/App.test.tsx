import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  ApiRequestError,
  analyzeRepository,
  inspectGitHubRepository,
  verifyChange,
} from "./api";
import App from "./App";
import type { VerificationResult } from "./types";

vi.mock("./api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./api")>();
  return {
    ...actual,
    analyzeRepository: vi.fn(),
    inspectGitHubRepository: vi.fn(),
    verifyChange: vi.fn(),
  };
});

const verificationResult: VerificationResult = {
  verification_id: "verification-demo",
  decision: "INSUFFICIENT_EVIDENCE",
  summary: "The code was inspected, but no runtime evidence is available.",
  evidence: [
    {
      evidence_id: "static-pattern-1",
      category: "behavioral_analysis",
      outcome: "inconclusive",
      message: "The detected operator differs from the stated requirement.",
      details: {},
      timestamp: "2026-10-20T12:00:00Z",
      duration_ms: null,
    },
  ],
  behavioral_findings: [
    {
      finding_type: "POTENTIAL_BEHAVIOR_MISMATCH",
      rule_id: "PG-PY-ADD-SUB-001",
      function_name: "add",
      detected_operator: "subtraction",
      expected_operator: "addition",
      source_line: 2,
      message: "Function add uses subtraction where addition was requested.",
    },
  ],
  checks: [],
  checks_performed: ["python_syntax", "behavioral_pattern"],
  checks_skipped: { regression_tests: "Submitted tests are never executed." },
  reasons: ["Runtime evidence is unavailable."],
  duration_ms: 5,
  policy_version: "1.0.1",
};

beforeEach(() => {
  vi.mocked(analyzeRepository).mockReset();
  vi.mocked(inspectGitHubRepository).mockReset();
  vi.mocked(verifyChange).mockReset();
});

describe("ProofGate dashboard", () => {
  it("rejects an empty bug description before calling the API", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.type(screen.getByLabelText(/python source/i), "def add(a, b): return a + b");
    await user.click(screen.getByRole("button", { name: /analyze evidence/i }));

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Describe the reported behavior in at least 5 characters.",
    );
    expect(verifyChange).not.toHaveBeenCalled();
  });

  it("submits valid verification input in analysis-only mode and renders evidence", async () => {
    const user = userEvent.setup();
    vi.mocked(verifyChange).mockResolvedValue(verificationResult);
    render(<App />);

    await user.type(
      screen.getByLabelText(/reported behavior/i),
      "add should add its two arguments",
    );
    await user.type(
      screen.getByLabelText(/python source/i),
      "def add(a, b):\n    return a - b",
    );
    await user.click(screen.getByRole("button", { name: /analyze evidence/i }));

    await waitFor(() => expect(verifyChange).toHaveBeenCalledOnce());
    expect(verifyChange).toHaveBeenCalledWith({
      bug_description: "add should add its two arguments",
      source_code: "def add(a, b):\n    return a - b",
      execution_mode: "analysis_only",
    });
    expect(await screen.findByText("Insufficient evidence")).toBeInTheDocument();
    expect(screen.getByText(verificationResult.summary)).toBeInTheDocument();
    expect(screen.getByText("POTENTIAL BEHAVIOR MISMATCH")).toBeInTheDocument();
    expect(screen.getByText(verificationResult.evidence[0].message)).toBeInTheDocument();
    expect(screen.getByText(/Submitted tests are never executed/)).toBeInTheDocument();
  });

  it("shows loading until the API request resolves", async () => {
    const user = userEvent.setup();
    let resolveRequest!: (result: VerificationResult) => void;
    vi.mocked(verifyChange).mockReturnValue(
      new Promise((resolve) => {
        resolveRequest = resolve;
      }),
    );
    render(<App />);

    await user.type(screen.getByLabelText(/reported behavior/i), "expected output");
    await user.type(screen.getByLabelText(/python source/i), "def f(): return 1");
    await user.click(screen.getByRole("button", { name: /analyze evidence/i }));

    expect(screen.getByText("Collecting safe evidence")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /analyzing/i })).toBeDisabled();
    resolveRequest(verificationResult);
    expect(await screen.findByText("Insufficient evidence")).toBeInTheDocument();
  });

  it("shows API errors and allows retry for server failures", async () => {
    const user = userEvent.setup();
    vi.mocked(verifyChange)
      .mockRejectedValueOnce(new ApiRequestError("Backend unavailable.", 503))
      .mockResolvedValueOnce(verificationResult);
    render(<App />);

    await user.type(screen.getByLabelText(/reported behavior/i), "expected output");
    await user.type(screen.getByLabelText(/python source/i), "def f(): return 1");
    await user.click(screen.getByRole("button", { name: /analyze evidence/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Backend unavailable.");
    await user.click(screen.getByRole("button", { name: /retry/i }));
    expect(await screen.findByText("Insufficient evidence")).toBeInTheDocument();
    expect(verifyChange).toHaveBeenCalledTimes(2);
  });

  it("rejects an invalid GitHub file limit before making a request", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole("tab", { name: /inspect github/i }));
    await user.type(
      screen.getByLabelText(/public repository url/i),
      "https://github.com/owner/repository",
    );
    const fileLimit = screen.getByLabelText(/maximum files to inspect/i);
    await user.clear(fileLimit);
    await user.type(fileLimit, "21");
    await user.click(screen.getByRole("button", { name: /inspect github/i }));

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Maximum files must be a whole number from 1 to 20.",
    );
    expect(inspectGitHubRepository).not.toHaveBeenCalled();
  });

  it("requires a GitHub URL but delegates URL validity to the API", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole("tab", { name: /inspect github/i }));
    await user.click(screen.getByRole("button", { name: /inspect github/i }));
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Enter a public GitHub repository URL.",
    );
    expect(inspectGitHubRepository).not.toHaveBeenCalled();

    vi.mocked(inspectGitHubRepository).mockRejectedValue(
      new ApiRequestError("Only public GitHub repository URLs are accepted.", 422),
    );
    await user.type(screen.getByLabelText(/public repository url/i), "not a valid URL");
    await user.click(screen.getByRole("button", { name: /inspect github/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Only public GitHub repository URLs are accepted.",
    );
    expect(inspectGitHubRepository).toHaveBeenCalledWith({
      repository_url: "not a valid URL",
      max_files: 20,
    });
  });

  it("keeps other workspace API methods available", async () => {
    const user = userEvent.setup();
    vi.mocked(analyzeRepository).mockResolvedValue({
      root_path: ".",
      file_count: 0,
      python_file_count: 0,
      syntax_error_count: 0,
      analyzed_paths: [],
      files: [],
      truncated: false,
    });
    render(<App />);

    await user.click(screen.getByRole("tab", { name: /analyze repository/i }));
    await user.type(screen.getByLabelText(/repository-relative python path/i), ".");
    await user.click(screen.getByRole("button", { name: /analyze repository/i }));

    expect(await screen.findByText("Read-only analysis complete")).toBeInTheDocument();
    expect(analyzeRepository).toHaveBeenCalledWith({
      repository_path: ".",
      max_files: 100,
    });
    expect(
      within(screen.getByLabelText(/execution safety notice/i)).getByText(
        /submitted code is never run/i,
      ),
    ).toBeInTheDocument();
  });
});