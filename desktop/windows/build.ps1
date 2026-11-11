param(
    [ValidateSet('win-x64','win-arm64')][string]$Runtime = '',
    [string]$Output = ''
)
$ErrorActionPreference = 'Stop'
if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw 'Run this script in native Windows PowerShell; WSL is not the UI acceptance target.'
}
if (-not (Get-Command dotnet -ErrorAction SilentlyContinue)) {
    throw 'Install the official .NET 10 SDK first; this script does not install dependencies.'
}
if (-not $Runtime) {
    # Works in Windows PowerShell 5.1 as well as PowerShell 7, including WOW64.
    $osArchitecture = $env:PROCESSOR_ARCHITEW6432
    if (-not $osArchitecture) { $osArchitecture = $env:PROCESSOR_ARCHITECTURE }
    $Runtime = if ($osArchitecture -eq 'ARM64') { 'win-arm64' } else { 'win-x64' }
}
$buildCache = Join-Path $env:LOCALAPPDATA 'ClawdyPrototype\Build'
$project = Join-Path $PSScriptRoot 'Clawdy.Windows.csproj'
$artifacts = Join-Path $buildCache 'artifacts'
if ($Output) {
    $Output = [System.IO.Path]::GetFullPath($Output)
    $artifacts = "$Output.artifacts"
} else {
    $Output = Join-Path $buildCache "publish\$Runtime"
}
$revision = ''
if (Get-Command git -ErrorAction SilentlyContinue) {
    $source = Join-Path $PSScriptRoot '..\..'
    try {
        $head = & git -C $source rev-parse --verify HEAD 2>$null
        if ($LASTEXITCODE -eq 0 -and $head -cmatch '^[0-9a-f]{40}$') {
            $changes = & git -C $source status --porcelain --untracked-files=normal -- desktop/windows desktop/macos/Assets scripts 2>$null
            if ($LASTEXITCODE -eq 0 -and -not $changes) { $revision = $head }
        }
    } catch {
        # A source archive or unavailable Git metadata still supports a demo build.
    }
}
$env:DOTNET_CLI_TELEMETRY_OPTOUT = '1'
$env:DOTNET_GENERATE_ASPNET_CERTIFICATE = 'false'
& dotnet publish $project --configuration Release --runtime $Runtime --self-contained false --artifacts-path $artifacts --output $Output "-p:ClawdySourceRevision=$revision" --nologo
if ($LASTEXITCODE -ne 0) { throw 'Build failed; no app was launched or installed.' }
Write-Host "Private unsigned prototype built: $Output"
Write-Host 'Run Clawdy.Windows.exe explicitly. No hooks, hardware or startup entries were installed.'
