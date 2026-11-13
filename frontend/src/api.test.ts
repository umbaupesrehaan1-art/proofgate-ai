import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiRequestError, verifyChange } from "./api";
import type { VerificationResult } from "./types";

const validResult: VerificationResult = {
  verification_id: "verification-123",
  decision: "INSUFFICIENT_EVIDENCE",
  summary: "Static analysis completed; runtime evidence is unavailable.",
  evidence: [],
  behavioral_findings: [],
  checks: [],
  checks_performed: ["python_syntax"],
  checks_skipped: { regression_tests: "Submitted tests are not executed." },
  reasons: ["Runtime evidence is unavailable."],
  duration_ms: 4,
  policy_version: "1.0.1",
};

function response(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: vi.fn().mockResolvedValue(body),
  } as unknown as Response;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("verifyChange", () => {
  it("reports network failures as connectivity errors", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));

    await expect(
      verifyChange({
        bug_description: "Expected arithmetic behavior",
        source_code: "def add(a, b): return a + b",
        execution_mode: "analysis_only",
      }),
    ).rejects.toMatchObject({
      name: "ApiRequestError",
      message: "Could not reach the ProofGate API. Check that the backend is running and try again.",
    });
  });

  it("surfaces structured HTTP 422 validation errors", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        response(422, {
          error: "validation_error",
          message: "Request validation failed.",
          fields: ["bug_description"],
        }),
      ),
    );

    const request = {
      bug_description: "Expected arithmetic behavior",
      source_code: "def add(a, b): return a + b",
      execution_mode: "analysis_only" as const,
    };
    await expect(verifyChange(request)).rejects.toEqual(
      expect.objectContaining<ApiRequestError>({
        name: "ApiRequestError",
        message: "Request validation failed.",
        status: 422,
        fields: ["bug_description"],
        code: "validation_error",
      }),
    );
  });

  it("rejects a malformed successful response", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(200, { decision: "VERIFIED" })));

    await expect(
      verifyChange({
        bug_description: "Expected arithmetic behavior",
        source_code: "def add(a, b): return a + b",
        execution_mode: "analysis_only",
      }),
    ).rejects.toMatchObject({
      name: "ApiRequestError",
      message: "The API response did not match the expected ProofGate result format.",
      status: 200,
    });
  });

  it("never accepts a plausible result returned with a non-success status", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(503, validResult)));

    await expect(
      verifyChange({
        bug_description: "Expected arithmetic behavior",
        source_code: "def add(a, b): return a + b",
        execution_mode: "analysis_only",
      }),
    ).rejects.toMatchObject({
      name: "ApiRequestError",
      message: "The API request failed with HTTP 503.",
      status: 503,
    });
  });

  it("returns a valid response and sends the existing API request shape", async () => {
    const fetchMock = vi.fn().mockResolvedValue(response(200, validResult));
    vi.stubGlobal("fetch", fetchMock);
    const request = {
      bug_description: "Expected arithmetic behavior",
      source_code: "def add(a, b): return a + b",
      execution_mode: "analysis_only" as const,
    };

    await expect(verifyChange(request)).resolves.toEqual(validResult);
    expect(fetchMock).toHaveBeenCalledWith("/api/v1/verify", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    });
  });

  it("reports unreadable response bodies", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: vi.fn().mockRejectedValue(new SyntaxError("invalid JSON")),
      }),
    );

    await expect(
      verifyChange({
        bug_description: "Expected arithmetic behavior",
        source_code: "def add(a, b): return a + b",
        execution_mode: "analysis_only",
      }),
    ).rejects.toMatchObject({
      name: "ApiRequestError",
      message: "The API returned an unreadable response. Please retry the request.",
      status: 200,
    });
  });
});