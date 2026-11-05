# ======================================================================
#   _   _             __        ___       
#  | \ | |_   ___  __ \ \      / (_)_ __  
#  |  \| | | | \ \/ /  \ \ /\ / /| | '_ \ 
#  | |\  | |_| |>  <    \ V  V / | | | | |
#  |_| \_|\__, /_/\_\    \_/\_/  |_|_| |_|
#         |___/                           
#  NyxWin - Automated One-Click Installer & Environment Setup
#  Strictly Native Windows (No macOS, No Linux, No WSL)
#  Usage (PowerShell One-Liner):
#    irm https://raw.githubusercontent.com/xAbdoAT/NyxWin/main/install.ps1 | iex
# ======================================================================

param (
    [switch]$Unattended,
    [switch]$SkipDoctor,
    [string]$Branch = "main"
)

$ErrorActionPreference = "Continue"

# Fix console encoding to UTF-8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

function Write-Banner {
    Write-Host ""
    Write-Host "======================================================================" -ForegroundColor Cyan
    Write-Host "  _   _             __        ___       " -ForegroundColor Cyan
    Write-Host " | \ | |_   ___  __ \ \      / (_)_ __  " -ForegroundColor Cyan
    Write-Host " |  \| | | | \ \/ /  \ \ /\ / /| | '_ \ " -ForegroundColor Cyan
    Write-Host " | |\  | |_| |>  <    \ V  V / | | | | |" -ForegroundColor Cyan
    Write-Host " |_| \_|\__, /_/\_\    \_/\_/  |_|_| |_|" -ForegroundColor Cyan
    Write-Host "        |___/                           " -ForegroundColor Cyan
    Write-Host " Native iOS Toolchain & IPA Builder for Windows (No macOS / No WSL)" -ForegroundColor White
    Write-Host " Developed by Abdo AT (@xAbdoAT) · https://github.com/xAbdoAT/NyxWin" -ForegroundColor Yellow
    Write-Host " Automated One-Click Installer & Environment Setup" -ForegroundColor Gray
    Write-Host "======================================================================" -ForegroundColor Cyan
    Write-Host ""
}

function Log-Info($msg)    { Write-Host "  [INFO] $msg" -ForegroundColor Blue }
function Log-Success($msg) { Write-Host "  [OK]   $msg" -ForegroundColor Green }
function Log-Warn($msg)    { Write-Host "  [WARN] $msg" -ForegroundColor Yellow }
function Log-Error($msg)   { Write-Host "  [FAIL] $msg" -ForegroundColor Red }
function Log-Step($num, $total, $title) {
    Write-Host "`n[$num/$total] $title" -ForegroundColor Cyan
    Write-Host ("-" * 60) -ForegroundColor DarkGray
}

Write-Banner

$TotalSteps = 7
$DataRoot = if ($env:LOCALAPPDATA) { Join-Path $env:LOCALAPPDATA "NyxWin" } else { Join-Path $HOME "AppData\Local\NyxWin" }
$ManagedAppDir = Join-Path $DataRoot "app"
$BinDir = Join-Path $DataRoot "bin"
$SdkDir = Join-Path $DataRoot "SDKs"

New-Item -ItemType Directory -Force -Path $DataRoot | Out-Null
New-Item -ItemType Directory -Force -Path $BinDir | Out-Null
New-Item -ItemType Directory -Force -Path $SdkDir | Out-Null

# ──────────────────────────────────────────────────────────────────────
# Step 1: Resolve or Download NyxWin Application Source
# ──────────────────────────────────────────────────────────────────────
Log-Step 1 $TotalSteps "Resolving NyxWin Installation Directory"

$ScriptDir = if ($MyInvocation.MyCommand.Path) { Split-Path -Parent $MyInvocation.MyCommand.Path } else { $null }

if ($ScriptDir -and (Test-Path (Join-Path $ScriptDir "src\nyxwin")) -and (Test-Path (Join-Path $ScriptDir "main.py"))) {
    $RootDir = $ScriptDir
    Log-Success "Running from local NyxWin source directory: $RootDir"
} else {
    $RootDir = $ManagedAppDir
    Log-Info "Bootstrapping NyxWin into managed directory: $RootDir"
    $gitCmd = (Get-Command git -ErrorAction SilentlyContinue).Source

    if ($gitCmd -and (Test-Path (Join-Path $RootDir ".git"))) {
        Log-Info "Updating existing NyxWin installation via Git..."
        & $gitCmd -C $RootDir pull --ff-only origin $Branch 2>$null
        Log-Success "Updated NyxWin at $RootDir"
    } elseif ($gitCmd -and (-not (Test-Path (Join-Path $RootDir "main.py")))) {
        Log-Info "Cloning https://github.com/xAbdoAT/NyxWin.git into $RootDir..."
        if (Test-Path $RootDir) { Remove-Item $RootDir -Recurse -Force -ErrorAction SilentlyContinue }
        & $gitCmd clone --depth 1 --branch $Branch "https://github.com/xAbdoAT/NyxWin.git" $RootDir
    }

    if (-not (Test-Path (Join-Path $RootDir "main.py"))) {
        Log-Info "Downloading NyxWin archive from GitHub..."
        $zipUrl = "https://github.com/xAbdoAT/NyxWin/archive/refs/heads/$Branch.zip"
        $tmpZip = Join-Path $env:TEMP "nyxwin-bootstrap.zip"
        $tmpExt = Join-Path $env:TEMP "nyxwin-bootstrap-ext"
        if (Test-Path $tmpExt) { Remove-Item $tmpExt -Recurse -Force -ErrorAction SilentlyContinue }
        Invoke-WebRequest -Uri $zipUrl -OutFile $tmpZip -UseBasicParsing
        Expand-Archive -Path $tmpZip -DestinationPath $tmpExt -Force
        Remove-Item $tmpZip -ErrorAction SilentlyContinue

        $innerDir = Get-ChildItem -Path $tmpExt -Directory | Select-Object -First 1
        if ($innerDir -and (Test-Path (Join-Path $innerDir.FullName "main.py"))) {
            New-Item -ItemType Directory -Force -Path $RootDir | Out-Null
            Copy-Item -Path (Join-Path $innerDir.FullName "*") -Destination $RootDir -Recurse -Force
            Log-Success "Extracted NyxWin to $RootDir"
        } else {
            Log-Error "Failed to download NyxWin source archive from GitHub."
            exit 1
        }
        Remove-Item $tmpExt -Recurse -Force -ErrorAction SilentlyContinue
    }
}

Set-Location $RootDir

# ──────────────────────────────────────────────────────────────────────
# Step 2: Detect / Install Python 3.10+
# ──────────────────────────────────────────────────────────────────────
Log-Step 2 $TotalSteps "Checking Python Runtime (3.10+)"

$PythonExe = $null
$pyCandidates = @(
    (Get-Command python -ErrorAction SilentlyContinue).Source,
    (Get-Command py -ErrorAction SilentlyContinue).Source,
    "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python310\python.exe",
    "C:\Program Files\Python312\python.exe"
) | Where-Object { $_ -and (Test-Path $_) }

foreach ($cand in $pyCandidates) {
    try {
        $verStr = & $cand -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
        $parts = $verStr.Split('.')
        if ([int]$parts[0] -ge 3 -and [int]$parts[1] -ge 10) {
            $PythonExe = $cand
            break
        }
    } catch {}
}

if ($PythonExe) {
    $fullVer = & $PythonExe --version 2>$null
    Log-Success "Python found: $PythonExe ($fullVer)"
} else {
    Log-Warn "Python 3.10+ not found. Installing Python 3.12 via winget..."
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        & winget install Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements
        $PythonExe = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
        if (-not (Test-Path $PythonExe)) {
            $PythonExe = (Get-Command python -ErrorAction SilentlyContinue).Source
        }
    } else {
        Log-Info "Downloading Python 3.12 installer..."
        $pyInstaller = "$env:TEMP\python-3.12-installer.exe"
        Invoke-WebRequest -Uri "https://www.python.org/ftp/python/3.12.7/python-3.12.7-amd64.exe" -OutFile $pyInstaller -UseBasicParsing
        Start-Process $pyInstaller -ArgumentList "/quiet InstallAllUsers=0 PrependPath=1" -Wait
        Remove-Item $pyInstaller -ErrorAction SilentlyContinue
        $PythonExe = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
    }

    if ($PythonExe -and (Test-Path $PythonExe)) {
        Log-Success "Python installed successfully: $PythonExe"
    } else {
        Log-Error "Python installation failed. Please install Python 3.10+ manually from https://python.org"
        exit 1
    }
}

# Install Pillow for app icon generation
& $PythonExe -m pip install "pillow>=9.0.0" --quiet --disable-pip-version-check 2>$null

# ──────────────────────────────────────────────────────────────────────
# Step 3: Detect / Install LLVM (clang.exe, lld.exe, ld64.lld.exe)
# ──────────────────────────────────────────────────────────────────────
Log-Step 3 $TotalSteps "Checking LLVM Compiler & Linker (clang.exe & ld64.lld.exe)"

$ClangPath = "C:\Program Files\LLVM\bin\clang.exe"
$LldPath = "C:\Program Files\LLVM\bin\lld.exe"
$Ld64Path = "C:\Program Files\LLVM\bin\ld64.lld.exe"

$hasLLVM = (Test-Path $ClangPath) -and ((Test-Path $LldPath) -or (Test-Path $Ld64Path))

if ($hasLLVM) {
    $clangVer = (& $ClangPath --version 2>$null)[0]
    Log-Success "LLVM found: $ClangPath"
    Log-Info "Version: $clangVer"
} else {
    Log-Warn "LLVM not detected. Installing official LLVM package..."
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Log-Info "Running winget install LLVM.LLVM..."
        & winget install --id LLVM.LLVM --exact --silent --accept-package-agreements --accept-source-agreements
    } else {
        Log-Info "Downloading LLVM installer from GitHub Releases..."
        $llvmInstaller = "$env:TEMP\LLVM-Install.exe"
        Invoke-WebRequest -Uri "https://github.com/llvm/llvm-project/releases/download/llvmorg-18.1.8/LLVM-18.1.8-win64.exe" -OutFile $llvmInstaller -UseBasicParsing
        Start-Process $llvmInstaller -ArgumentList "/S" -Wait
        Remove-Item $llvmInstaller -ErrorAction SilentlyContinue
    }

    if ((Test-Path $ClangPath) -and ((Test-Path $LldPath) -or (Test-Path $Ld64Path))) {
        Log-Success "LLVM installed successfully to C:\Program Files\LLVM\bin"
    } else {
        Log-Error "LLVM installation failed. Please run: winget install LLVM.LLVM"
        exit 1
    }
}

# Ensure LLVM\bin is in User PATH
$userPath = [Environment]::GetEnvironmentVariable("PATH", "User")
$llvmBin = "C:\Program Files\LLVM\bin"
if ($userPath -notmatch [regex]::Escape($llvmBin)) {
    Log-Info "Adding $llvmBin to User PATH..."
    [Environment]::SetEnvironmentVariable("PATH", "$llvmBin;$userPath", "User")
    $env:PATH = "$llvmBin;$env:PATH"
    Log-Success "User PATH updated with LLVM."
}

# ──────────────────────────────────────────────────────────────────────
# Step 4: Detect / Install Swift Toolchain (swiftc.exe)
# ──────────────────────────────────────────────────────────────────────
Log-Step 4 $TotalSteps "Checking Swift Toolchain for Windows (swiftc.exe)"

$SwiftCandidates = @(
    (Get-Command swiftc -ErrorAction SilentlyContinue).Source,
    "$env:LOCALAPPDATA\Programs\Swift\Toolchains\*\usr\bin\swiftc.exe",
    "C:\Program Files\Swift\Toolchains\*\usr\bin\swiftc.exe",
    "C:\Local\Swift\Toolchains\*\usr\bin\swiftc.exe"
)

$SwiftcPath = $null
foreach ($pattern in $SwiftCandidates) {
    if ($pattern) {
        $resolved = Resolve-Path $pattern -ErrorAction SilentlyContinue
        if ($resolved) {
            $SwiftcPath = $resolved[-1].Path
            break
        }
    }
}

if ($SwiftcPath -and (Test-Path $SwiftcPath)) {
    $swiftVer = (& $SwiftcPath --version 2>$null)[0]
    Log-Success "Swift Toolchain found: $SwiftcPath"
    Log-Info "Version: $swiftVer"
} else {
    Log-Warn "Swift Toolchain not detected. Installing official Swift Toolchain..."
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Log-Info "Running winget install Swift.Toolchain (may take a few minutes)..."
        & winget install --id Swift.Toolchain --exact --silent --accept-package-agreements --accept-source-agreements
    } else {
        Log-Error "Automatic Swift install requires winget. Install from: https://www.swift.org/install/windows"
        exit 1
    }

    foreach ($pattern in $SwiftCandidates) {
        $resolved = Resolve-Path $pattern -ErrorAction SilentlyContinue
        if ($resolved) {
            $SwiftcPath = $resolved[-1].Path
            break
        }
    }

    if ($SwiftcPath -and (Test-Path $SwiftcPath)) {
        Log-Success "Swift Toolchain installed successfully!"
    } else {
        Log-Error "Swift Toolchain installation failed. Please check winget logs or visit swift.org."
        exit 1
    }
}

# Ensure Swift's usr\bin is in User PATH
$swiftBinDir = Split-Path -Parent $SwiftcPath
$userPath = [Environment]::GetEnvironmentVariable("PATH", "User")
if ($userPath -notmatch [regex]::Escape($swiftBinDir)) {
    Log-Info "Adding $swiftBinDir to User PATH..."
    [Environment]::SetEnvironmentVariable("PATH", "$swiftBinDir;$userPath", "User")
    $env:PATH = "$swiftBinDir;$env:PATH"
    Log-Success "User PATH updated with Swift."
}

# ──────────────────────────────────────────────────────────────────────
# Step 5: Verify or Download iOS SDK & Swift Target Resources
# ──────────────────────────────────────────────────────────────────────
Log-Step 5 $TotalSteps "Checking iOS SDK (iPhoneOS26.5.sdk) & Swift Target Resources"

$PrefSdk = Join-Path $SdkDir "iPhoneOS26.5.sdk"
$HasSdk = $false

if (Test-Path (Join-Path $PrefSdk "System\Library\Frameworks")) {
    $HasSdk = $true
    $fwCount = (Get-ChildItem (Join-Path $PrefSdk "System\Library\Frameworks") -Directory -Filter "*.framework").Count
    Log-Success "iOS SDK found: iPhoneOS26.5.sdk ($fwCount frameworks)"
} else {
    $existingSdks = Get-ChildItem $SdkDir -Directory -Filter "iPhoneOS*.sdk" -ErrorAction SilentlyContinue | Where-Object {
        Test-Path (Join-Path $_.FullName "System\Library\Frameworks")
    }
    if ($existingSdks) {
        $HasSdk = $true
        Log-Success "iOS SDK found: $($existingSdks[0].Name)"
    }
}

if (-not $HasSdk) {
    Log-Warn "No iOS SDK found in $SdkDir. Downloading iPhoneOS26.5.sdk (~100MB)..."
    $sdkZip = Join-Path $env:TEMP "iPhoneOS26.5.sdk.zip"
    $sdkUrl = "https://github.com/xybp888/iOS-SDKs/releases/download/iOS26.5-SDKs/iPhoneOS26.5.sdk.zip"

    Log-Info "Downloading from GitHub Releases ($sdkUrl)..."
    Invoke-WebRequest -Uri $sdkUrl -OutFile $sdkZip -UseBasicParsing

    Log-Info "Extracting SDK to $SdkDir..."
    Expand-Archive -Path $sdkZip -DestinationPath $SdkDir -Force
    Remove-Item $sdkZip -ErrorAction SilentlyContinue

    $macosx = Join-Path $SdkDir "__MACOSX"
    if (Test-Path $macosx) { Remove-Item $macosx -Recurse -Force -ErrorAction SilentlyContinue }

    if (Test-Path (Join-Path $PrefSdk "System\Library\Frameworks")) {
        Log-Success "iPhoneOS26.5.sdk installed successfully!"
    } else {
        Log-Error "SDK extraction failed. Please run: nyx sdk install 26.5"
        exit 1
    }
}

$SwiftResDir = Join-Path $SdkDir "swift_resources\swift\iphoneos"
if (Test-Path $SwiftResDir) {
    Log-Success "Swift iOS target resources verified (arm64 & arm64e)."
} else {
    $legacySwiftRes = Join-Path $RootDir "sdk\swift_resources"
    if (Test-Path (Join-Path $legacySwiftRes "swift\iphoneos")) {
        Log-Info "Migrating swift_resources to $SdkDir..."
        Copy-Item -Path $legacySwiftRes -Destination $SdkDir -Recurse -Force
        Log-Success "Migrated swift_resources to $SdkDir."
    } else {
        $swiftResUrl = "https://github.com/xAbdoAT/NyxWin/releases/latest/download/swift_resources.zip"
        $swiftResZip = Join-Path $env:TEMP "swift_resources.zip"
        try {
            Log-Info "Checking for Swift iOS target resources on GitHub Releases..."
            Invoke-WebRequest -Uri $swiftResUrl -OutFile $swiftResZip -UseBasicParsing -ErrorAction Stop
            Expand-Archive -Path $swiftResZip -DestinationPath $SdkDir -Force
            Remove-Item $swiftResZip -ErrorAction SilentlyContinue
            Log-Success "Downloaded and extracted Swift iOS target resources to $SdkDir."
        } catch {
            Log-Warn "Swift iOS target resources not yet present in $SdkDir."
        }
    }
}

# ──────────────────────────────────────────────────────────────────────
# Step 6: Verify Helper Tools & Register Global CLI Shims (nyx, nyxwin)
# ──────────────────────────────────────────────────────────────────────
Log-Step 6 $TotalSteps "Verifying Native Helper Tools & Registering Global CLI Commands"

$ToolsDir = Join-Path $RootDir "src\nyxwin\resources\tools"
$ldid = Join-Path $ToolsDir "ldid.exe"
$patchMacho = Join-Path $ToolsDir "patch_macho.py"
$platformCheck = Join-Path $ToolsDir "platform_check.c"
$clangRt = Join-Path $ToolsDir "libclang_rt.ios.a"

if (Test-Path $ldid) {
    Log-Success "Code Signer (ldid.exe) verified."
} else {
    Log-Warn "ldid.exe missing. Downloading prebuilt ldid..."
    New-Item -ItemType Directory -Force -Path $ToolsDir | Out-Null
    Invoke-WebRequest -Uri "https://github.com/ProcursusTeam/ldid/releases/latest/download/ldid_windows_x86_64.exe" -OutFile $ldid -UseBasicParsing
    Log-Success "Downloaded ldid.exe."
}

if (Test-Path $clangRt) {
    Log-Success "Compiler-RT archive (libclang_rt.ios.a) verified."
}

if ((Test-Path $patchMacho) -and (Test-Path $platformCheck)) {
    Log-Success "Mach-O Patcher (#31) and Dynamic Version Check verified."
}

# Generate standalone CLI shims in %LOCALAPPDATA%\NyxWin\bin (works without requiring .whl builds)
$MainPy = Join-Path $RootDir "main.py"
$SrcDir = Join-Path $RootDir "src"
$ShimContent = "@echo off`r`nset `"PYTHONPATH=$SrcDir;%PYTHONPATH%`"`r`n`"$PythonExe`" `"$MainPy`" %*`r`n"

Set-Content -Path (Join-Path $BinDir "nyx.cmd") -Value $ShimContent -Encoding UTF8
Set-Content -Path (Join-Path $BinDir "nyxwin.cmd") -Value $ShimContent -Encoding UTF8
Log-Success "Created global CLI shims (nyx, nyxwin) in $BinDir"

# Also register editable package if pip is available
& $PythonExe -m pip install -e $RootDir --quiet --disable-pip-version-check 2>$null

# Add %LOCALAPPDATA%\NyxWin\bin to User PATH and current session PATH
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
$pathArr = $userPath -split ';' | Where-Object { $_ -ne '' }
if ($pathArr -notcontains $BinDir) {
    $newPath = (@($BinDir) + $pathArr) -join ';'
    [Environment]::SetEnvironmentVariable("Path", $newPath, "User")
    Log-Success "Added $BinDir to Windows User PATH."
}
if (($env:PATH -split ';') -notcontains $BinDir) {
    $env:PATH = "$BinDir;$env:PATH"
}

# ──────────────────────────────────────────────────────────────────────
# Step 7: Complete Setup & Run Health Diagnostic
# ──────────────────────────────────────────────────────────────────────
Log-Step 7 $TotalSteps "Running Toolchain Doctor Health Diagnostic"

if (-not $SkipDoctor) {
    Write-Host ""
    & $PythonExe $MainPy doctor
}

Write-Host ""
Write-Host "======================================================================" -ForegroundColor Green
Write-Host " [SUCCESS] NyxWin Setup & Environment Configuration Complete!" -ForegroundColor Green
Write-Host "======================================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  You can now build and package iOS applications from any terminal:" -ForegroundColor White
Write-Host "    * Interactive TUI Menu:  " -NoNewline; Write-Host "nyx" -ForegroundColor Cyan -NoNewline; Write-Host " (or " -NoNewline; Write-Host "nyxwin" -ForegroundColor Cyan -NoNewline; Write-Host ")"
Write-Host "    * Create New App:        " -NoNewline; Write-Host "nyx new swiftui MyApp" -ForegroundColor Cyan
Write-Host "    * Build Project IPA:     " -NoNewline; Write-Host "nyx build" -ForegroundColor Cyan
Write-Host "    * Check for Updates:     " -NoNewline; Write-Host "nyx update" -ForegroundColor Cyan
Write-Host ""

if (-not $Unattended) {
    $launch = Read-Host "Would you like to launch the NyxWin Interactive Menu now? (Y/n)"
    if ($launch -eq "" -or $launch -match "^[Yy]") {
        & $PythonExe $MainPy
    }
}
