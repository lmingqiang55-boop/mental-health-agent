param([switch]$SmokeTest)

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$configPath = Join-Path $PSScriptRoot '.env'
$pythonPath = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $configPath)) {
    throw 'Local .env configuration is missing.'
}
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw 'Project Python environment is missing.'
}

foreach ($line in Get-Content -LiteralPath $configPath) {
    if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)=(.*)$') {
        [Environment]::SetEnvironmentVariable($matches[1], $matches[2], 'Process')
    }
}

if ($SmokeTest) {
    & $pythonPath -c 'from backend.assessment.engine import AssessmentEngine; engine = AssessmentEngine(); print(engine.question_decider.version); print(engine.question_generator.version); session, first = engine.start(); print(first); print(session.action_log[-1].model_dump_json())'
    exit $LASTEXITCODE
}

& $pythonPath -m uvicorn backend.main:app --reload
