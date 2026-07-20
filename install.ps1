#Requires -Version 5.1
# RailCall native Windows installer (PowerShell). Mirrors install.sh's contract for testers who are
# on native Windows (not WSL2). Run in PowerShell:
#   irm https://raw.githubusercontent.com/patl4588/railcall-core/main/install.ps1 | iex
# or, from a checkout:
#   powershell -ExecutionPolicy Bypass -File .\install.ps1
#
# Honest + non-destructive: it discloses every path it writes BEFORE the first write, never resets an
# existing token, and REFUSES any core file whose bytes do not match the sha256 pinned into this
# installer (see $Pins) — the same supply-chain gate install.sh uses. This file does not touch the
# bash installer's path.

$ErrorActionPreference = 'Stop'
$ProgressPreference    = 'SilentlyContinue'   # skip the slow Invoke-WebRequest progress bars
# Some older Windows PowerShell defaults negotiate SSLv3/TLS1.0; force TLS 1.2 for GitHub + the CDN.
try { [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12 } catch {}

function Write-C([string]$msg, [string]$color = 'Gray') { Write-Host $msg -ForegroundColor $color }

Write-C "================================================================" Cyan
Write-C "                 R A I L C A L L   I N S T A L L E R            " Cyan
Write-C "================================================================" Cyan

# ---- Paths + sources ------------------------------------------------------------------------------
$RcHome  = Join-Path $env:USERPROFILE '.railcall'
$RcBin   = Join-Path $RcHome 'bin'
$RcConf  = Join-Path $env:USERPROFILE '.config\railcall'
$Files   = @('railcall_cli.py','railcall_companion_daemon.py','vault_io.py','receipt_signer.py')

# raw.githubusercontent.com is blocked/throttled by some regional ISPs (a transparent proxy can even
# hand back a fake "200 OK" whose body is a 404 page); jsDelivr mirrors the SAME repo. We try raw, then
# the CDN — identical to install.sh.
$RawBase = 'https://raw.githubusercontent.com/patl4588/railcall-core/main'
$CdnBase = 'https://cdn.jsdelivr.net/gh/patl4588/railcall-core@main'

# ---- Supply-chain integrity pins ------------------------------------------------------------------
# Every core file is verified against a sha256 PINNED here. This stops a compromised 'main' (or a MITM
# proxy that swaps the body) from injecting code that merely happens to parse — a file whose bytes do
# not match its pin is REFUSED and never installed, even if py_compile passes. This is the SAME pin set
# embedded in install.sh; keep the two in sync.
#
# Regenerate after an INTENTIONAL change to the core files, from a repo checkout, with:
#   Get-ChildItem railcall_cli.py,railcall_companion_daemon.py,vault_io.py,receipt_signer.py |
#     ForEach-Object { "    '{0}' = '{1}'" -f $_.Name, (Get-FileHash $_ -Algorithm SHA256).Hash.ToLower() }
# then paste the printed lines into $Pins below.
$Pins = @{
    'railcall_cli.py'              = '45f2e8a6ea4910ecf2a878098d60905f8b1071f2e9ac9f328a7f40320fb5a3bc'
    'railcall_companion_daemon.py' = '6a40af4c5bfdf34b706496eea2889488d563acb35d5c9b7484dd2ae8a7c80805'
    'vault_io.py'                  = '17b0e644a93c773d3f7b5e5e8b046ea39472364b532b545846f3c617433792f8'
    'receipt_signer.py'            = '36b84579880db9bf78c9bc21cd40c6976094ae8ea978c939f2feef4f97041b9e'
}

# Resolve ONE Python 3 interpreter, tried in order: python3, python, then the 'py -3' launcher. Stored
# as $script:PyExe + $script:PyPre (a prefix-args array) so 'py -3' works everywhere below.
$script:PyExe = $null
$script:PyPre = @()
function Resolve-Python {
    $cands = @(
        @{ Exe = 'python3'; Pre = @()      },
        @{ Exe = 'python';  Pre = @()      },
        @{ Exe = 'py';      Pre = @('-3')  }
    )
    foreach ($c in $cands) {
        if (Get-Command $c.Exe -ErrorAction SilentlyContinue) {
            $pre = $c.Pre
            try {
                $major = (& $c.Exe @pre -c "import sys; print(sys.version_info[0])" 2>$null)
                if ($LASTEXITCODE -eq 0 -and ("$major").Trim() -eq '3') {
                    $script:PyExe = $c.Exe; $script:PyPre = $c.Pre; return $true
                }
            } catch {
                # Microsoft Store alias or other transient failure on this candidate; try next
            }
        }
    }
    return $false
}

# Does the resolved Python compile this file? (mirrors install.sh's py_compile gate)
function Test-PyCompile([string]$path) {
    $pre = $script:PyPre
    & $script:PyExe @pre -m py_compile $path 2>$null | Out-Null
    return ($LASTEXITCODE -eq 0)
}

# Is 'cryptography' importable by the resolved Python?
function Test-Crypto {
    $pre = $script:PyPre
    & $script:PyExe @pre -c "import cryptography" 2>$null | Out-Null
    return ($LASTEXITCODE -eq 0)
}

# Verify a file on disk against its pin. $false (with a LOUD security refusal) on any mismatch or an
# unpinned filename — we would rather refuse than install unverified code.
function Test-Pin([string]$f, [string]$path) {
    $want = $Pins[$f]
    if (-not $want) {
        Write-C "  [x] SECURITY: $f has no integrity pin in this installer - refusing to install unpinned code." Red
        return $false
    }
    $got = (Get-FileHash -Path $path -Algorithm SHA256).Hash.ToLower()
    if ($got -ne $want) {
        Write-C "  [x] SECURITY: $f failed its integrity pin - REFUSING this file. It parses, but the bytes are not what we published." Red
        Write-C "      expected sha256 $want" Red
        Write-C "      got      sha256 $got" Red
        return $false
    }
    return $true
}

# Get + validate one file: local checkout (if run from one), then raw GitHub, then jsDelivr. A source
# counts only if it is non-empty AND compiles as Python AND matches its pinned sha256 — so a proxy's
# fake 404 body (fails compile) and any tampered-but-compiling body (fails the pin) are both rejected.
function Get-CoreFile([string]$f) {
    $dest = Join-Path $RcHome $f
    if ($ScriptDir) {
        $src = Join-Path $ScriptDir $f
        if ((Test-Path $src) -and ((Get-Item $src).Length -gt 0) -and (Test-PyCompile $src) -and (Test-Pin $f $src)) {
            Copy-Item $src $dest -Force
            Write-C "  [ok] $f (local checkout)" Green
            return $true
        }
    }
    foreach ($base in @($RawBase, $CdnBase)) {
        try {
            Invoke-WebRequest -Uri "$base/$f" -OutFile $dest -UseBasicParsing -ErrorAction Stop
        } catch {
            if (Test-Path $dest) { Remove-Item $dest -Force -ErrorAction SilentlyContinue }
            continue
        }
        if ((Test-Path $dest) -and ((Get-Item $dest).Length -gt 0) -and (Test-PyCompile $dest) -and (Test-Pin $f $dest)) {
            if ($base -like '*jsdelivr*') { Write-C "  [ok] $f (via CDN mirror)" Green } else { Write-C "  [ok] $f" Green }
            return $true
        }
        if (Test-Path $dest) { Remove-Item $dest -Force -ErrorAction SilentlyContinue }
    }
    return $false
}

# If run from a checkout (git clone / unzipped ZIP) the source files sit next to us; $PSScriptRoot is
# empty when piped via irm|iex, in which case we skip the local source and go straight to the network.
$ScriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { $null }

# ---- Full disclosure BEFORE the first write -------------------------------------------------------
Write-C "This installer writes to:" Blue
Write-C "  - $RcHome - the 4 core CLI files, the 'railcall' launcher shim, and the Studio bundle (~5MB)" Blue
Write-C "  - $RcConf - your pre-login local trial token (token.json)" Blue
Write-C "  - your USER PATH (HKCU environment) - one entry for $RcBin, only if not already present" Blue
Write-C "  - Python user packages - the 'cryptography' package via pip --user, only if missing" Blue

New-Item -ItemType Directory -Force -Path $RcHome, $RcBin, $RcConf | Out-Null

if (-not (Resolve-Python)) {
    Write-C "Python 3 is required and was not found on PATH (looked for 'python3', 'python', then 'py -3')." Red
    Write-C "Install Python 3 from https://www.python.org/downloads/windows/ (check 'Add python.exe to PATH') and re-run." Red
    exit 1
}
Write-C "  Using Python: $script:PyExe $(($script:PyPre) -join ' ')" Blue

# ---- Download + verify the CLI --------------------------------------------------------------------
Write-C "Downloading CLI (raw.githubusercontent.com, CDN fallback) ..." Blue
foreach ($f in $Files) {
    if (-not (Get-CoreFile $f)) {
        Write-C "[x] Could not install a valid $f from GitHub or the CDN mirror." Red
        Write-C "    If a SECURITY integrity-pin refusal printed above, STOP - do not work around it; the published" Red
        Write-C "    bytes did not match this installer's pin. Otherwise it is usually a regional network block." Red
        Write-C "    Install from a checkout instead:" Blue
        Write-C "      git clone https://github.com/patl4588/railcall-core" Blue
        Write-C "      cd railcall-core; powershell -ExecutionPolicy Bypass -File .\install.ps1" Blue
        exit 1
    }
}

# ---- Receipt signing (cryptography) - best-effort, NON-FATAL --------------------------------------
# Without it the daemon still writes airlock-verified, SHA-256 receipts - just honestly UNSIGNED. With
# it, every receipt is Ed25519-signed. We verify the import after installing (pip's exit code alone is
# not proof it's importable).
if (Test-Crypto) {
    Write-C "  [ok] receipt signing available (Ed25519)" Green
} else {
    Write-C "  - installing the Python 'cryptography' package so receipts can be Ed25519-signed ..." Blue
    $pre = $script:PyPre
    try { & $script:PyExe @pre -m pip install --user --quiet --disable-pip-version-check cryptography 2>$null | Out-Null } catch {}
    if (Test-Crypto) {
        Write-C "  [ok] receipt signing enabled (installed cryptography)" Green
    } else {
        Write-C "  ! receipt signing is NOT enabled - receipts will be written UNSIGNED (airlock-verified, SHA-256 only)." Red
        Write-C "    Turn it on later with:  $script:PyExe $(($script:PyPre) -join ' ') -m pip install --user cryptography" Cyan
        Write-C "    (verify with:  $script:PyExe $(($script:PyPre) -join ' ') -c ""import cryptography""  - no output means it's ready)" Blue
    }
}

# ---- Studio (the visual builder) - fetch + SHA-verify + unpack the station bundle (~5MB) ----------
# SHA gate matches install.sh's STATION_SHA — Windows users get the same fail-closed integrity
# check macOS/Linux users have had since v0.4. Uses tar (Windows 10 1803+ ships tar.exe natively);
# the older ZIP-first path was removed because we've never actually shipped a .zip release asset.
$StationTgzUrl = 'https://github.com/patl4588/railcall-core/releases/download/station-v0.15/railcall_station.tar.gz'
$StationSha    = '9d0102ab6951af9ad72bc89c96f7c0eeb631dc86fba729288f074e73abce8a2b'
$StationDir    = Join-Path $RcHome 'station'
$StationTgz    = Join-Path $RcHome 'station.tar.gz'
Write-C "Downloading the RailCall Studio (one-time, ~5MB) ..." Blue
$studioOk = $false

try {
    Invoke-WebRequest -Uri $StationTgzUrl -OutFile $StationTgz -UseBasicParsing -ErrorAction Stop
    # SHA gate — fail-closed. Silent bytes-mismatch would be a supply-chain smuggling window.
    $actual = (Get-FileHash -Path $StationTgz -Algorithm SHA256).Hash.ToLower()
    if ($actual -ne $StationSha) {
        # Fatal — matches install.sh behavior. Mismatched bytes indicate tampering,
        # MITM, or a wrong URL; safer to abort than to proceed with maybe-clean-CLI-
        # and-tampered-Studio. Non-fatal handling would defeat the point of the gate.
        Write-C "  [x] SECURITY: station bundle failed integrity check - refusing" Red
        Write-C "      expected $StationSha" Red
        Write-C "      got      $actual" Red
        Remove-Item $StationTgz -Force -ErrorAction SilentlyContinue
        exit 1
    }
    New-Item -ItemType Directory -Force -Path $StationDir | Out-Null
    if (Get-Command tar -ErrorAction SilentlyContinue) {
        tar -xzf $StationTgz -C $StationDir 2>$null
        if (Test-Path (Join-Path $StationDir 'workbench\studio_server.py')) { $studioOk = $true }
    } else {
        Write-C "  [x] tar not found (Windows 10 1803+ ships it) - Studio skipped, CLI still works." Red
    }
} catch {
    # Reached only for network failures — SHA mismatch takes the exit 1 path above.
    Write-C "  [x] Could not download the Studio bundle - CLI still works; re-run to retry." Red
}
if (Test-Path $StationTgz) { Remove-Item $StationTgz -Force -ErrorAction SilentlyContinue }

if ($studioOk) {
    Write-C "  [ok] Studio installed - run 'railcall studio' to open it in your browser." Green
}

# ---- Pre-login LOCAL trial token ------------------------------------------------------------------
# The CLI reads token["runs_remaining"], decrements it per build, and hard-blocks at 0. Re-running
# never resets an existing token. rc_local_ is a LOCAL sentinel the engine allowlists - it must NEVER
# touch the gateway. Lives under the per-user profile, so it is already user-scoped on NTFS.
$TokenFile = Join-Path $RcConf 'token.json'
if (-not (Test-Path $TokenFile)) {
    '{"api_key": "rc_local_trial_100", "tier": "free", "runs_remaining": 100}' | Set-Content -Path $TokenFile -Encoding ascii
    Write-C "Provisioned a pre-login LOCAL trial of 100 flows - enforced by the CLI on this machine only, never a hosted balance." Green
    Write-C "It is replaced by your account balance the moment you run 'railcall login <key>' (free accounts include 100 flows)." Green
} else {
    Write-C "Existing token kept (not reset)." Green
}

# ---- Launcher shim: railcall.cmd forwards every arg to the real CLI --------------------------------
# Bakes in the interpreter resolved above so 'py -3'-only or 'python'-only setups keep working.
$Shim      = Join-Path $RcBin 'railcall.cmd'
$PyInvoke  = (($script:PyExe + ' ' + (($script:PyPre) -join ' ')).Trim())
$CliPath   = Join-Path $RcHome 'railcall_cli.py'
$ShimBody  = "@echo off`r`n$PyInvoke `"$CliPath`" %*`r`n"
Set-Content -Path $Shim -Value $ShimBody -Encoding ascii -NoNewline
Write-C "  [ok] wrote launcher shim $Shim" Green

# ---- Add the bin dir to the USER PATH (once) ------------------------------------------------------
$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
if ($null -eq $userPath) { $userPath = '' }
$parts = @($userPath.Split(';') | Where-Object { $_ -ne '' })
if ($parts -notcontains $RcBin) {
    $trimmed = $userPath.TrimEnd(';')
    $newPath = if ($trimmed -eq '') { $RcBin } else { "$trimmed;$RcBin" }
    [Environment]::SetEnvironmentVariable('Path', $newPath, 'User')
    Write-C "Added $RcBin to your USER PATH (new terminals will find 'railcall')." Green
} else {
    Write-C "$RcBin already on your USER PATH." Green
}
# Make 'railcall' resolvable in THIS session too, without reopening the terminal.
if (@(($env:Path).Split(';')) -notcontains $RcBin) { $env:Path = "$($env:Path);$RcBin" }

# ---- Done -----------------------------------------------------------------------------------------
Write-C "Installed. LOCAL - BYOK - DRY-RUN - NO SENDS - everything runs on 127.0.0.1, nothing fires without your approval." Green
Write-C "================================================================" Cyan
Write-C "  Tip: open a NEW terminal so PATH picks up 'railcall' (it is also set for THIS window already)." Cyan
Write-C "================================================================" Cyan
Write-C "Then run:" Green
Write-C "   railcall studio   - open the visual Studio in your browser (127.0.0.1:8799)" Cyan
Write-C "   railcall          - the terminal dashboard (key, flows, commands)" Cyan
