<#
.SYNOPSIS
    Gera o launcher clicável AI-Audio-Capture.exe na raiz do repositório.

.DESCRIPTION
    Compila um executável nativo pequeno que abre o bundle onedir em dist/.
    O launcher resolve o caminho usando sua própria localização, portanto
    funciona mesmo quando iniciado por atalho ou por outro diretório.

.PARAMETER Profile
    Define qual bundle será procurado primeiro: Full (padrão) ou Light.
#>
[CmdletBinding()]
param(
    [ValidateSet('Full', 'Light')]
    [string]$Profile = 'Full'
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Source = Join-Path $PSScriptRoot 'launcher\Program.cs'
$Icon = Join-Path $PSScriptRoot 'icon.ico'
$Output = Join-Path $ProjectRoot 'AI-Audio-Capture.exe'

$CompilerCandidates = @(
    (Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'),
    (Join-Path $env:WINDIR 'Microsoft.NET\Framework\v4.0.30319\csc.exe')
)
$Compiler = $CompilerCandidates |
    Where-Object { Test-Path -LiteralPath $_ } |
    Select-Object -First 1

if (-not $Compiler) {
    throw 'Compilador C# do .NET Framework não encontrado neste Windows.'
}

$CompilerArguments = @(
    '/nologo',
    '/target:exe',
    '/optimize+',
    '/debug-',
    '/platform:anycpu',
    '/reference:System.Windows.Forms.dll',
    "/win32icon:$Icon",
    "/out:$Output"
)
if ($Profile -eq 'Light') {
    $CompilerArguments += '/define:PREFER_LIGHT'
}
$CompilerArguments += $Source

Write-Host 'Gerando launcher clicável na raiz...' -ForegroundColor Yellow
& $Compiler @CompilerArguments
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $Output)) {
    throw 'Não foi possível gerar AI-Audio-Capture.exe.'
}

$SizeKiB = [Math]::Round((Get-Item -LiteralPath $Output).Length / 1KB, 1)
Write-Host "✓ Launcher: $Output ($SizeKiB KiB)" -ForegroundColor Green
