# Plugin Install & Security — Features in openclaw Missing from Synapse-OSS

## Overview

openclaw has a multi-layer plugin security model covering installation-time scanning, path-escape
detection, world-writable path blocking, file ownership verification, and npm integrity drift
detection. It also has a structured install/update/uninstall lifecycle with host-version
compatibility checks. Synapse-OSS has no equivalent security model or structured extension
install flow.

---

## What openclaw has

### 1. Security Scan at Install Time

**Files:** `src/plugins/install-security-scan.ts`, `src/plugins/install-security-scan.runtime.ts`

Four scan entry points gate installation:

```typescript
export async function scanBundleInstallSource(params: InstallSafetyOverrides & {
  logger: InstallScanLogger;
  pluginId: string;
  sourceDir: string;
  requestKind?: PluginInstallRequestKind;
  requestedSpecifier?: string;
  mode?: "install" | "update";
  version?: string;
}): Promise<InstallSecurityScanResult | undefined>

export async function scanPackageInstallSource(params: InstallSafetyOverrides & {
  extensions: string[];       // openclaw.extensions array from package.json
  packageDir: string;
  pluginId: string;
  requestKind?: PluginInstallRequestKind;
  ...
}): Promise<InstallSecurityScanResult | undefined>

export async function scanFileInstallSource(params: ...): Promise<InstallSecurityScanResult | undefined>

export async function scanArchiveInstallSource(params: ...): Promise<InstallSecurityScanResult | undefined>
```

The runtime scan is lazy-loaded (`install-security-scan.runtime.ts`) to avoid adding startup
cost when no install is in progress.

```typescript
export type InstallSecurityScanResult = {
  blocked?: {
    code?: "security_scan_blocked" | "security_scan_failed";
    reason: string;
  };
};
```

`dangerouslyForceUnsafeInstall?: boolean` can override blocks in development — must be
explicitly set by the caller.

---

### 2. Request Kind Classification

**File:** `src/plugins/install-security-scan.ts`

```typescript
export type PluginInstallRequestKind =
  | "plugin-dir"      // local directory
  | "plugin-archive"  // zip/tarball
  | "plugin-file"     // single .ts/.js file
  | "plugin-npm";     // npm registry package
```

The security scan logic can apply different scrutiny levels based on how the plugin was sourced.
NPM packages get integrity verification; local dirs get path-escape checks.

---

### 3. Structured Install Error Codes

**File:** `src/plugins/install.ts`

```typescript
export const PLUGIN_INSTALL_ERROR_CODE = {
  INVALID_NPM_SPEC: "invalid_npm_spec",
  INVALID_MIN_HOST_VERSION: "invalid_min_host_version",
  UNKNOWN_HOST_VERSION: "unknown_host_version",
  INCOMPATIBLE_HOST_VERSION: "incompatible_host_version",
  MISSING_OPENCLAW_EXTENSIONS: "missing_openclaw_extensions",
  EMPTY_OPENCLAW_EXTENSIONS: "empty_openclaw_extensions",
  NPM_PACKAGE_NOT_FOUND: "npm_package_not_found",
  PLUGIN_ID_MISMATCH: "plugin_id_mismatch",
  SECURITY_SCAN_BLOCKED: "security_scan_blocked",
  SECURITY_SCAN_FAILED: "security_scan_failed",
} as const;

export type InstallPluginResult =
  | {
      ok: true;
      pluginId: string;
      targetDir: string;
      manifestName?: string;
      version?: string;
      extensions: string[];
      npmResolution?: NpmSpecResolution;
      integrityDrift?: NpmIntegrityDrift;
    }
  | { ok: false; error: string; code?: PluginInstallErrorCode };
```

---

### 4. Min Host Version Compatibility Check

**File:** `src/plugins/min-host-version.ts`

Each plugin can declare a `minHostVersion` in `package.json → openclaw.install.minHostVersion`.
The installer checks this before proceeding:

```typescript
export function checkMinHostVersion(params: {
  minHostVersion?: string;
  hostVersion?: string;
}): { ok: true } | { ok: false; error: string; code: PluginInstallErrorCode }
```

This prevents installing plugins built for a newer openclaw API against an older host, which
could cause silent breakage at runtime.

---

### 5. Multi-Format Archive Detection

**File:** `src/plugins/install.ts`

```typescript
const PLUGIN_ARCHIVE_ROOT_MARKERS = [
  "package.json",
  "openclaw.plugin.json",
  ".codex-plugin/plugin.json",    // Codex plugin format
  ".claude-plugin/plugin.json",   // Claude plugin format
  ".cursor-plugin/plugin.json",   // Cursor plugin format
];
```

Plugin archives (zip/tarball) are detected by probing for these root markers. This allows
openclaw to install plugins packaged in compatible formats from other AI tool ecosystems
while still validating the openclaw manifest.

---

### 6. Path-Based Security at Discovery Time

**File:** `src/plugins/discovery.ts`

Before a plugin candidate is loaded, the discovery layer checks:

#### 6a. Path Escape (symlink traversal)
```typescript
type CandidateBlockReason =
  | "source_escapes_root"         // symlink resolves outside plugin root
  | "path_stat_failed"            // cannot stat the path
  | "path_world_writable"         // directory/file is world-writable (0o002)
  | "path_suspicious_ownership";  // uid mismatch
```

`safeRealpathSync()` is used (never `fs.realpath` — avoids TOCTOU). The check uses
`isPathInside(rootRealPath, sourceRealPath)` to detect escapes.

#### 6b. World-Writable Auto-Repair for Bundled Plugins
```typescript
if ((modeBits & 0o002) !== 0 && params.origin === "bundled") {
  // npm/global installs can create dirs without entries in tarball, widening to 0777.
  // Tighten bundled dirs in place before applying the normal safety gate.
  fs.chmodSync(targetPath, modeBits & ~0o022);
}
```

Auto-repair is only applied to `bundled` origin. `global`/`workspace`/`config` plugins that
are world-writable are blocked outright.

#### 6c. Ownership Verification (POSIX only)
```typescript
if (params.origin !== "bundled" &&
    params.uid !== null &&
    typeof stat.uid === "number" &&
    stat.uid !== params.uid &&
    stat.uid !== 0) {
  return { reason: "path_suspicious_ownership", ... };
}
```

Non-bundled plugins must be owned by the process uid or root. This blocks privilege-escalation
attacks where a lower-privilege user drops a malicious plugin into the extensions directory.

---

### 7. NPM Integrity Drift Detection

**File:** `src/plugins/install.ts` (via `NpmIntegrityDrift` from `src/infra/install-source-utils.ts`)

```typescript
export type PluginNpmIntegrityDriftParams = {
  spec: string;
  expectedIntegrity: string;
  actualIntegrity: string;
  resolution: NpmSpecResolution;
};
```

When a plugin is installed or updated from npm, the resolved package integrity (sha512 hash)
is compared against the expected value. Drift is surfaced as a warning — the install can still
proceed but the discrepancy is logged for audit.

---

### 8. Skill Install Metadata

**File:** `src/plugins/install-security-scan.ts`

```typescript
export type SkillInstallSpecMetadata = {
  id?: string;
  kind: "brew" | "node" | "go" | "uv" | "download";
  label?: string;
  bins?: string[];
  os?: string[];
  formula?: string;
  package?: string;
  module?: string;
  url?: string;
  archive?: string;
  extract?: boolean;
  stripComponents?: number;
  targetDir?: string;
};
```

Skills (binary tools invoked by plugins) have their own install metadata schema. The security
scan validates skill install specs before allowing binary downloads or package installs.

---

### 9. Boundary File Reader

**File:** `src/infra/boundary-file-read.ts` (used by `src/plugins/manifest.ts`)

`openBoundaryFileSync()` wraps `fs.openSync()` with three security checks:
1. The file must be inside the declared root directory (`isPathInside` after realpath)
2. Hardlinks are optionally rejected (`rejectHardlinks = true` by default for manifests)
3. Returns an open file descriptor to prevent TOCTOU between stat and read

Used by the manifest loader to safely open `openclaw.plugin.json` before parsing.

---

## What Synapse-OSS has (or lacks)

Synapse-OSS has **no security model for extension/skill loading**:

- Skills in `workspace/skills/` are loaded via direct `import` / `from ... import`. There is no
  validation before load.
- `synapse_config.py` has a single permission advisory check on `synapse.json`:
  ```python
  def _verify_permissions(path: Path) -> None:
      mode = path.stat().st_mode
      if mode & (stat.S_IRGRP | stat.S_IROTH):
          warnings.warn(...)
  ```
  This is advisory-only (`warnings.warn`, not a block), applies only to the config file
  (not plugins), and is skipped entirely on Windows.
- No path-escape detection, no world-writable blocking, no ownership verification for loaded code.
- No install lifecycle — skills are added by placing files in the workspace directly.
- No version compatibility check.
- No integrity verification.

---

## Gap Summary

| Feature | openclaw | Synapse-OSS |
|---------|----------|-------------|
| Security scan at install time | Yes (4 scan functions) | No |
| Install request kind classification | Yes | No |
| Structured install error codes | Yes (10 codes) | No |
| Host version compatibility check | Yes | No |
| Multi-format archive detection | Yes | No |
| Symlink/path-escape blocking at discovery | Yes | No |
| World-writable path blocking (+ auto-repair) | Yes | No |
| Process-uid ownership verification | Yes | No |
| NPM integrity drift detection | Yes | No |
| Skill binary install metadata + security | Yes | No |
| Boundary file reader (anti-TOCTOU) | Yes | No |
| `dangerouslyForceUnsafeInstall` override | Yes (explicit opt-in) | N/A |

---

## Implementation Notes for Porting

1. **Path security at discovery time:**
   ```python
   import os, stat

   def check_plugin_path_security(source: str, root: str, origin: str) -> str | None:
       real_source = os.path.realpath(source)
       real_root = os.path.realpath(root)
       if not real_source.startswith(real_root + os.sep) and real_source != real_root:
           return "source_escapes_root"
       if sys.platform != "win32":
           s = os.stat(source)
           if s.st_mode & 0o002:
               if origin == "bundled":
                   os.chmod(source, s.st_mode & ~0o022)
               else:
                   return "path_world_writable"
           if origin != "bundled" and s.st_uid not in (os.getuid(), 0):
               return "path_suspicious_ownership"
       return None
   ```

2. **Install lifecycle:**
   - Phase 1: resolve package spec → download to temp dir
   - Phase 2: run security scan on temp dir
   - Phase 3: validate `synapse.plugin.json` exists and is parseable
   - Phase 4: check `min_host_version`
   - Phase 5: atomically move to `~/.synapse/extensions/<plugin_id>/`

3. **Integrity verification:** Use `hashlib.sha512` on downloaded package bytes; compare
   against expected hash from package index before installing.

4. **Error codes:** Define structured error codes as a Python Enum or `Literal` union to
   enable typed error handling in callers.
