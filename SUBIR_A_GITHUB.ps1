$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "CuotaGo - publicar en GitHub" -ForegroundColor Cyan
Write-Host ""

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "Git no esta instalado o no esta disponible en PATH."
}

if (-not (Test-Path ".git")) {
    git init
}

# Nunca publicar secretos locales.
if (Test-Path ".env") {
    git rm --cached .env 2>$null | Out-Null
}

git add .

$envTracked = git ls-files -- ".env"
if ($envTracked) {
    throw "SEGURIDAD: .env quedo preparado para Git. No se publicara. Revisa .gitignore."
}

Write-Host "[OK] .env NO se publicara." -ForegroundColor Green
Write-Host ""

$status = git status --short
if ($status) {
    Write-Host $status
} else {
    Write-Host "No hay cambios nuevos para commit." -ForegroundColor Yellow
}

$hasHead = $true
try { git rev-parse --verify HEAD *> $null } catch { $hasHead = $false }

if (-not $hasHead -or $status) {
    git add .
    git commit -m "CuotaGo v1.9.1 - Superadmin + PWA + Push"
}

git branch -M main

$remote = git remote get-url origin 2>$null
if (-not $remote) {
    $remote = Read-Host "Pega la URL HTTPS del repo vacio de GitHub"
    if (-not $remote) { throw "Falta la URL del repositorio." }
    git remote add origin $remote
} else {
    Write-Host "Origin actual: $remote" -ForegroundColor DarkGray
}

Write-Host ""
Write-Host "Subiendo a GitHub..." -ForegroundColor Cyan
git push -u origin main
Write-Host ""
Write-Host "[OK] Codigo publicado. El archivo .env local NO fue subido." -ForegroundColor Green
