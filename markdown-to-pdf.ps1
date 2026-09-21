# Launch from any working directory. All arguments are forwarded to the converter.
$ErrorActionPreference = 'Stop'
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Error 'uv is required. Install it from https://docs.astral.sh/uv/ and run again.'
    exit 2
}
$previousCache = $env:UV_CACHE_DIR
$previousEnvironment = $env:VIRTUAL_ENV
try {
    $env:UV_CACHE_DIR = Join-Path $PSScriptRoot '.uv-cache'
    $env:VIRTUAL_ENV = $null
    & uv run --project (Join-Path $PSScriptRoot 'tools\markdown_pdf') --locked --no-dev markdown-pdf @args
    $converterExitCode = $LASTEXITCODE
}
finally {
    $env:UV_CACHE_DIR = $previousCache
    $env:VIRTUAL_ENV = $previousEnvironment
}
exit $converterExitCode
