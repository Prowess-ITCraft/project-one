<#
Windows equivalent of the Makefile. Usage: .\scripts\dev.ps1 <command> [args]
Commands: up, down, logs, ps, test, lint, typecheck, migrate, seed, admin, openapi, backup
#>
param([Parameter(Mandatory=$true, Position=0)][string]$Command, [Parameter(ValueFromRemainingArguments=$true)][string[]]$Rest)
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
$compose = @("compose","-f","docker-compose.yml","-f","docker-compose.dev.yml","--profile","dev","--profile","monitoring")
$py = Join-Path $root "backend\.venv\Scripts\python.exe"

switch ($Command) {
  "up"        { docker @compose up -d --build }
  "down"      { docker @compose down }
  "logs"      { docker @compose logs -f --tail=100 }
  "ps"        { docker @compose ps }
  "migrate"   { docker @compose run --rm migrate }
  "seed"      { docker @compose exec api python -m app.cli seed }
  "admin"     { docker @compose exec api python -m app.cli create-admin @Rest }
  "backup"    { docker @compose exec worker python -m app.cli backup }
  "test"      { Push-Location backend; & $py -m pytest -q --cov=app; Pop-Location }
  "lint"      { Push-Location backend; & $py -m ruff check app tests; & $py -m ruff format --check app tests; Pop-Location }
  "typecheck" { Push-Location backend; & $py -m mypy app tests; Pop-Location }
  "openapi"   { Push-Location backend; & $py -m app.cli openapi --out openapi.json; Pop-Location }
  default     { Write-Error "Unknown command $Command" }
}
