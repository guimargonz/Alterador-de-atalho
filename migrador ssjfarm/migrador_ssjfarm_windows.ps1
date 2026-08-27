<#
.SYNOPSIS
    Migrador de Atalhos - ssjfarm.com.br (Windows, 100% nativo - sem dependência de Python)

.DESCRIPTION
    Migra atalhos de área de trabalho entre o domínio físico (ssjfarm.com.br)
    e um servidor virtual (IP:porta), reescrevendo-os para abrir com o Firefox.
    Roda com o PowerShell que já vem embutido no Windows - nada para instalar.

.PARAMETER Modo
    VIRTUAL: ssjfarm.com.br -> IP:porta
    FISICO:  IP:porta -> ssjfarm.com.br

.PARAMETER Ip
    IP do servidor virtual (padrão: 192.168.100.123)

.PARAMETER Porta
    Porta do servidor virtual (padrão: 8181)

.PARAMETER DryRun
    Mostra o que seria alterado, sem gravar nada em disco.

.PARAMETER LogDir
    Diretório para salvar o log. Padrão: %ProgramData%\MigradorSSJ\logs

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\migrador_ssjfarm_windows.ps1 -Modo VIRTUAL -DryRun

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\migrador_ssjfarm_windows.ps1 -Modo VIRTUAL

.NOTES
    Códigos de saída: 0 = sem erros | 1 = concluído com erros em itens | 2 = erro fatal
#>

param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("VIRTUAL", "FISICO")]
    [string]$Modo,

    [string]$Ip = "192.168.100.123",
    [string]$Porta = "8181",
    [switch]$DryRun,
    [string]$LogDir
)

$ErrorActionPreference = "Stop"

# --------------------------------------------------------------------------
# CONFIGURAÇÕES PADRÃO
# --------------------------------------------------------------------------
$DominioFisico  = "ssjfarm.com.br"
$FirefoxPath    = "C:\Program Files\Mozilla Firefox\firefox.exe"
$ComputerName   = $env:COMPUTERNAME

if (-not $LogDir -or $LogDir -eq "") {
    $LogDir = Join-Path $env:ProgramData "MigradorSSJ\logs"
}

try {
    if (-not (Test-Path $LogDir)) {
        New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
    }
} catch {
    $LogDir = $env:TEMP
}

$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$LogPath = Join-Path $LogDir "migrador_$($ComputerName)_$Timestamp.log"

function Write-Log {
    param([string]$Level, [string]$Message)
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') - $ComputerName - [$Level] - $Message"
    Write-Host $line
    try { Add-Content -Path $LogPath -Value $line -Encoding UTF8 } catch { }
}

# --------------------------------------------------------------------------
# Aviso se o Firefox não existir no caminho esperado (não é fatal - o atalho
# ainda é reescrito, mas pode falhar ao abrir se o Firefox estiver em outro
# lugar ou não estiver instalado).
# --------------------------------------------------------------------------
if (-not (Test-Path $FirefoxPath)) {
    Write-Log "WARN" "Firefox não encontrado em '$FirefoxPath'. Os atalhos serão reescritos mesmo assim, mas podem falhar ao abrir."
}

# --------------------------------------------------------------------------
# Monta busca/troca conforme o modo
# --------------------------------------------------------------------------
$HostVirtual = "$($Ip):$($Porta)"

if ($Modo -eq "VIRTUAL") {
    $Busca = $DominioFisico
    $Troca = $HostVirtual
} else {
    $Busca = $HostVirtual
    $Troca = $DominioFisico
}

Write-Log "INFO" "Host: $ComputerName | SO: Windows | Modo: $Modo"
Write-Log "INFO" "Migrando: $Busca -> $Troca$(if ($DryRun) { ' [DRY-RUN]' } else { '' })"
Write-Log "INFO" "Log salvo em: $LogPath"

# --------------------------------------------------------------------------
# Migração
# --------------------------------------------------------------------------
$changed = 0
$errors = 0

try {
    $shell = New-Object -ComObject WScript.Shell
} catch {
    Write-Log "ERROR" "Falha ao inicializar WScript.Shell: $($_.Exception.Message)"
    exit 2
}

$locations = @("$env:USERPROFILE\Desktop", "$env:PUBLIC\Desktop")

foreach ($loc in $locations) {
    if (-not (Test-Path $loc)) { continue }

    $shortcuts = Get-ChildItem -Path $loc -Filter *.lnk -ErrorAction SilentlyContinue
    foreach ($file in $shortcuts) {
        try {
            $s = $shell.CreateShortcut($file.FullName)
            $target = [string]$s.TargetPath
            $args   = [string]$s.Arguments
            $fullCmd = "$target $args"

            if (-not $fullCmd.Contains($Busca)) {
                continue
            }

            $newArgs = $args.Replace($Busca, $Troca)

            # Se a URL estava no TargetPath (atalho aponta direto para a URL)
            # em vez de nos Arguments, reconstrói preservando o caminho/URL
            # em vez de descartá-lo.
            if (-not $newArgs.ToLower().Contains("http")) {
                $newTarget = $target.Replace($Busca, $Troca)
                if ($newTarget -ne $target -and $newTarget.ToLower().Contains("http")) {
                    $newArgs = $newTarget
                } else {
                    $newArgs = "https://$Troca"
                }
            }

            if (-not $DryRun) {
                # Backup oculto antes de qualquer alteração
                $backupPath = "$($file.FullName).bak"
                Copy-Item -Path $file.FullName -Destination $backupPath -Force -ErrorAction SilentlyContinue
                if (Test-Path $backupPath) {
                    (Get-Item $backupPath -Force).Attributes = 'Hidden'
                }

                $s.TargetPath = $FirefoxPath
                $s.Arguments = $newArgs
                $s.Save()
            }

            $suffix = if ($DryRun) { " (dry-run)" } else { "" }
            Write-Log "INFO" "[OK] $($file.Name)$suffix -> $newArgs"
            $changed++

        } catch {
            Write-Log "ERROR" "[ERRO] $($file.Name) - $($_.Exception.Message)"
            $errors++
        }
    }
}

Write-Log "INFO" "Concluído. $changed atalho(s) alterado(s), $errors erro(s)."

if ($errors -gt 0) {
    exit 1
} else {
    exit 0
}
