<#
.SYNOPSIS
    Gera o executável Windows (.exe) do AI-Audio-Capture com PyInstaller.

.DESCRIPTION
    Cria (ou reutiliza) um ambiente virtual isolado, instala as dependências
    e empacota o aplicativo. Por padrão gera o build LEVE (rápido, pequeno,
    sem redução de ruído). Use -Full para incluir noisereduce.

    Os dois perfis usam o formato onedir. Ao final, o script também gera
    AI-Audio-Capture.exe na raiz, pronto para abrir por duplo clique.

    Requer Python 3.10+ (testado em 3.14) no PATH.

.PARAMETER Full
    Gera o build completo (com redução de ruído). Bundle maior que o leve.

.PARAMETER Clean
    Remove build/ e dist/ antes de empacotar.

.EXAMPLE
    .\build\build_exe.ps1
    # Build leve e launcher -> .\AI-Audio-Capture.exe

.EXAMPLE
    .\build\build_exe.ps1 -Full -Clean
    # Build completo e launcher -> .\AI-Audio-Capture.exe
#>
[CmdletBinding()]
param(
    [switch]$Full,
    [switch]$Clean
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvDir = Join-Path $ProjectRoot '.venv-build'
$Spec = if ($Full) { 'AI-Audio-Capture-full.spec' } else { 'AI-Audio-Capture.spec' }
$SpecPath = Join-Path $PSScriptRoot $Spec

Write-Host '== AI-Audio-Capture :: build do executável ==' -ForegroundColor Cyan
Write-Host ("Perfil: {0} | Formato: onedir" -f ($(if ($Full) { 'COMPLETO' } else { 'LEVE' })))

# 1. Ambiente virtual isolado
if (-not (Test-Path $VenvDir)) {
    Write-Host 'Criando ambiente virtual de build...' -ForegroundColor Yellow
    python -m venv $VenvDir
}
$Py = Join-Path $VenvDir 'Scripts\python.exe'

# 2. Dependências
Write-Host 'Instalando dependências...' -ForegroundColor Yellow
& $Py -m pip install --upgrade pip --quiet
& $Py -m pip install 'pyinstaller>=6.17' --quiet
if ($Full) {
    & $Py -m pip install -r (Join-Path $ProjectRoot 'requirements-postprocess.txt') --quiet
} else {
    # Build leve precisa de scipy (ducking) mas NÃO de noisereduce.
    & $Py -m pip install -r (Join-Path $ProjectRoot 'requirements.txt') --quiet
    & $Py -m pip install 'scipy>=1.10' --quiet
}

# 3. Limpeza opcional
if ($Clean) {
    Write-Host 'Limpando build/ e dist/...' -ForegroundColor Yellow
    foreach ($d in @('build\AI-Audio-Capture', 'build\AI-Audio-Capture-full', 'dist')) {
        $p = Join-Path $ProjectRoot $d
        if (Test-Path $p) { Remove-Item -Recurse -Force $p }
    }
    $rootLauncher = Join-Path $ProjectRoot 'AI-Audio-Capture.exe'
    if (Test-Path -LiteralPath $rootLauncher) {
        Remove-Item -LiteralPath $rootLauncher -Force
    }
}

# 4. Empacotamento
Write-Host "Executando PyInstaller ($Spec)..." -ForegroundColor Yellow
Push-Location $ProjectRoot
try {
    & $Py -m PyInstaller $SpecPath --noconfirm
} finally {
    Pop-Location
}

if ($LASTEXITCODE -ne 0) {
    throw 'O PyInstaller não concluiu o empacotamento.'
}

# 5. Resultado
$exeName = if ($Full) { 'AI-Audio-Capture-full' } else { 'AI-Audio-Capture' }
$exePath = Join-Path $ProjectRoot ("dist\{0}\{0}.exe" -f $exeName)

if (Test-Path $exePath) {
    $profile = if ($Full) { 'Full' } else { 'Light' }
    & (Join-Path $PSScriptRoot 'build_launcher.ps1') -Profile $profile

    Write-Host "`n✓ Bundle gerado:" -ForegroundColor Green
    Write-Host "   $exePath" -ForegroundColor Green
    Write-Host "`nAbra por duplo clique:" -ForegroundColor Green
    Write-Host "   $(Join-Path $ProjectRoot 'AI-Audio-Capture.exe')" -ForegroundColor Green
    Write-Host 'Mantenha a pasta dist junto ao launcher na raiz.' -ForegroundColor Cyan
    Write-Host 'Teste-o em uma máquina SEM Python para validar o bundle.' -ForegroundColor Cyan
} else {
    Write-Warning "Build concluído, mas não encontrei $exePath. Verifique o log do PyInstaller."
}
