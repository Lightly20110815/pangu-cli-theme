# One-step install for Windows (PowerShell 5.1 or 7):
#   irm https://raw.githubusercontent.com/Lightly20110815/pangu-cli-theme/main/install.ps1 | iex
# From a checkout, with options:  .\install.ps1 --apps codex
$ErrorActionPreference = 'Stop'
$repo = 'https://github.com/Lightly20110815/pangu-cli-theme'

function Find-Python {
    foreach ($candidate in @(@('py', '-3'), @('python'), @('python3'))) {
        if (-not (Get-Command $candidate[0] -ErrorAction SilentlyContinue)) { continue }
        $rest = @()
        if ($candidate.Count -gt 1) { $rest = $candidate[1..($candidate.Count - 1)] }
        try {
            & $candidate[0] @rest -c "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)" 2>$null
            if ($LASTEXITCODE -eq 0) { return ,$candidate }
        } catch { }
    }
    return $null
}

$python = Find-Python
if (-not $python) {
    Write-Host 'pangu-cli-theme needs Python 3.8 or newer: https://www.python.org/downloads/' -ForegroundColor Red
    return
}
$pyExe = $python[0]
$pyArgs = @()
if ($python.Count -gt 1) { $pyArgs = $python[1..($python.Count - 1)] }

$tmp = $null
if ($env:PANGU_SOURCE) {
    # Install from a local checkout instead of downloading (used by CI).
    $src = $env:PANGU_SOURCE
} else {
    $tmp = Join-Path ([IO.Path]::GetTempPath()) ('pangu-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $tmp | Out-Null
    $zip = Join-Path $tmp 'src.zip'
    Invoke-WebRequest -UseBasicParsing -Uri "$repo/archive/refs/heads/main.zip" -OutFile $zip
    Expand-Archive -Path $zip -DestinationPath $tmp
    $src = Join-Path $tmp 'pangu-cli-theme-main'
}
$env:PYTHONIOENCODING = 'utf-8'
try {
    & $pyExe @pyArgs (Join-Path $src 'install.py') @args
} finally {
    if ($tmp) { Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue }
}
