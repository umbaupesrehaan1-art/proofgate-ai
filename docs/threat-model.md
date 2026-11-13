# Threat model

ProofGate treats repository files, source text, diffs, and test paths as untrusted input. The initial backend does **not execute untrusted repository code**.

## Threats and controls

- **Path traversal and absolute paths:** client paths are validated as relative paths and resolved under one configured root.
- **Symlink escape and path replacement:** repository walking skips symlink and junction entries. File content is read only after opening the target and validating the opened file itself. On POSIX, each root and file path component is opened relative to a held directory descriptor with `O_NOFOLLOW`; files are read through the validated descriptor. On Windows, files are opened with `FILE_FLAG_OPEN_REPARSE_POINT`, reparse-point files are rejected, and the final path of the opened handle must remain beneath the configured root before content is read. This prevents a replaced file or parent junction from redirecting content reads outside the root.
- **Arbitrary command execution:** no API accepts commands and no submitted code or pytest process is launched. `subprocess` is not used for verification.
- **Secrets in evidence or errors:** API errors omit exception details and host paths. Evidence detail values are bounded and sensitive-key names are redacted. Operators should still avoid putting secrets in bug descriptions or source inputs.
- **Oversized inputs and denial of service:** request bodies, source files, diffs, analyzed file counts, total traversed repository entries, diagnostic strings, and model fields have bounds. AST parsing is still CPU work, so deployments should use request timeouts, concurrency controls, and process-level resource limits.
- **Unsafe sandboxing:** no sandbox is claimed to exist. The `isolated_sandbox` mode is unsupported and results in skipped execution checks. A future worker must be isolated from service credentials, host files, and network access, and separately security-reviewed.
- **Repository trust boundary:** only a server-configured root is eligible for analysis. The API is intended for local development and must not be exposed publicly without authentication, authorization, rate limiting, and deployment hardening.
- **Network access:** analysis has no network integration or network-dependent verification.

## Residual risks

The API currently has no authentication or rate limiting and holds bounded request bodies in memory. It should be bound to loopback for local development. AST parsing of adversarially complex input may consume CPU even though it does not execute the source. The configured repository root itself is trusted deployment configuration.

Race resistance is not an atomic repository snapshot. On Windows, directory enumeration uses path-based `scandir`; a concurrently replaced ancestor can cause bounded metadata/name enumeration outside the root, but no file content is read unless the final opened handle passes the root check. On POSIX, content opens are anchored to directory handles, but concurrent in-place modifications to an already-open file may still race with the read; metadata changes detected during the read cause that result to be discarded, but filesystem metadata checks cannot prove a consistent snapshot on every filesystem. Use an immutable or otherwise trusted repository snapshot when concurrent writers are in scope. Platforms lacking the required POSIX no-follow/dir-fd capabilities fail closed for file content analysis.