<#
.SYNOPSIS
    Migrador de Atalhos - ssjfarm.com.br (Windows, 100% nativo - sem dependência de Python)

.DESCRIPTION
    Migra atalhos de área de trabalho entre o domínio físico (ssjfarm.com.br)
    e um servidor virtual (IP:porta), reescrevendo-os para abrir com o Firefox.
    Roda com o PowerShell que já vem embutido no Windows - nada para instalar.

    NOVO - troca de gateway (somente -Modo VIRTUAL):
    além dos atalhos, o gateway padrão da máquina é trocado para
    "<sub-rede do gateway atual>.1". Ex.: gateway atual 10.5.125.254 -> 10.5.125.1.
    Em -Modo FISICO o gateway NÃO é alterado.

    A troca exige PowerShell como Administrador e é uma operação de risco
    quando feita remotamente (PsExec/WinRM): se a nova rota não funcionar, a
    sessão remota pode cair. Por isso existe uma rede de segurança: antes de
    trocar, é agendada (em um processo separado da sessão) a restauração do
    gateway antigo após -GatewayTimeout segundos, cancelada apenas se o novo
    gateway responder a ping. A reversão restaura também a configuração
    persistida do adaptador.

.PARAMETER Modo
    VIRTUAL: ssjfarm.com.br -> IP:porta (e troca o gateway para final .1)
    FISICO:  IP:porta -> ssjfarm.com.br (gateway não é alterado)

.PARAMETER Ip
    IP do servidor virtual (padrão: 192.168.100.123)

.PARAMETER Porta
    Porta do servidor virtual (padrão: 8181)

.PARAMETER DryRun
    Mostra o que seria alterado (atalhos e gateway), sem gravar nada em disco
    nem mexer na rede. Apenas o log é gravado.

.PARAMETER SemGateway
    Em -Modo VIRTUAL, migra só os atalhos e NÃO altera o gateway.

.PARAMETER GatewayTimeout
    Segundos até a reversão automática do gateway caso a conectividade com o
    novo gateway não seja confirmada (padrão: 90; mínimo 10, máximo 600).

.PARAMETER LogDir
    Diretório para salvar o log. Padrão: %ProgramData%\MigradorSSJ\logs

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\migrador_ssjfarm_windows.ps1 -Modo VIRTUAL -DryRun

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\migrador_ssjfarm_windows.ps1 -Modo VIRTUAL -SemGateway

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\migrador_ssjfarm_windows.ps1 -Modo VIRTUAL

.NOTES
    Códigos de saída: 0 = sem erros | 1 = concluído com erros em itens (inclui falha na troca de gateway) | 2 = erro fatal
#>

param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("VIRTUAL", "FISICO")]
    [string]$Modo,

    [string]$Ip = "192.168.100.123",
    [string]$Porta = "8181",
    [switch]$DryRun,
    [switch]$SemGateway,

    [ValidateRange(10, 600)]
    [int]$GatewayTimeout = 90,

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
# GATEWAY (somente -Modo VIRTUAL)
# Usa WMI (Win32_IP4RouteTable / Win32_NetworkAdapterConfiguration), que
# funciona do Windows 7 em diante (PowerShell 2.0) e persiste a mudança na
# configuração do adaptador.
# --------------------------------------------------------------------------
function Test-IPv4 {
    param([string]$Value)
    $parsed = $null
    if ([System.Net.IPAddress]::TryParse($Value, [ref]$parsed)) {
        if ($parsed.AddressFamily -eq [System.Net.Sockets.AddressFamily]::InterNetwork -and $Value.Split('.').Count -eq 4) {
            return $true
        }
    }
    return $false
}

function Test-SameSubnet {
    param([string]$IpA, [string]$Mask, [string]$IpB)
    $a = [System.Net.IPAddress]::Parse($IpA).GetAddressBytes()
    $m = [System.Net.IPAddress]::Parse($Mask).GetAddressBytes()
    $b = [System.Net.IPAddress]::Parse($IpB).GetAddressBytes()
    for ($i = 0; $i -lt 4; $i++) {
        if (($a[$i] -band $m[$i]) -ne ($b[$i] -band $m[$i])) { return $false }
    }
    return $true
}

function Test-IsAdmin {
    try {
        $id = [Security.Principal.WindowsIdentity]::GetCurrent()
        $principal = New-Object Security.Principal.WindowsPrincipal($id)
        return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    } catch {
        return $false
    }
}

# Script executado em um processo SEPARADO (criado via WMI, portanto
# desacoplado da sessão atual - sobrevive mesmo que PsExec/WinRM caia).
# Espera o timeout; se o arquivo-marcador existir, a troca foi confirmada e
# nada é feito; caso contrário, restaura o gateway antigo.
$RevertTemplate = @'
Start-Sleep -Seconds __DELAY__
$marker = '__MARKER__'
if (Test-Path $marker) {
    Remove-Item $marker -Force -ErrorAction SilentlyContinue
    exit 0
}
$msg = ''
try {
    $cfg = Get-WmiObject Win32_NetworkAdapterConfiguration -Filter 'InterfaceIndex=__IDX__'
    $r = $cfg.SetGateways([string[]]@(__GWS__), [uint16[]]@(__METRICS__))
    $msg = 'Reversao automatica executada (SetGateways retornou ' + $r.ReturnValue + ').'
} catch {
    $msg = 'Reversao automatica FALHOU: ' + $_.Exception.Message
}
$linha = (Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + ' - __HOST__ - [WARN] - [GATEWAY] ' + $msg
Add-Content -Path '__LOG__' -Value $linha -Encoding UTF8
'@

function Invoke-GatewayMigration {
    param([bool]$Simular, [int]$TimeoutSeg)

    # 1) Rota padrão atual (menor métrica)
    try {
        $rota = Get-WmiObject Win32_IP4RouteTable |
            Where-Object { $_.Destination -eq "0.0.0.0" -and $_.Mask -eq "0.0.0.0" } |
            Sort-Object Metric1 |
            Select-Object -First 1
    } catch {
        Write-Log "ERROR" "[GATEWAY] Falha ao consultar a tabela de rotas: $($_.Exception.Message)"
        return $false
    }

    if (-not $rota) {
        Write-Log "ERROR" "[GATEWAY] Não há rota padrão configurada. Pulei a troca de gateway."
        return $false
    }

    $gwAtual = [string]$rota.NextHop
    $idx = [int]$rota.InterfaceIndex

    if (-not (Test-IPv4 $gwAtual) -or $gwAtual -eq "0.0.0.0") {
        Write-Log "ERROR" "[GATEWAY] Gateway atual '$gwAtual' não é um IPv4 válido. Pulei a troca."
        return $false
    }

    # 2) Novo gateway = mesmos 3 primeiros octetos + .1
    $p = $gwAtual.Split('.')
    $novoGw = "$($p[0]).$($p[1]).$($p[2]).1"

    if ($gwAtual -eq $novoGw) {
        Write-Log "INFO" "[GATEWAY] Gateway já é $novoGw. Nada a fazer."
        return $true
    }

    # 3) Configuração do adaptador dono dessa rota
    try {
        $cfg = Get-WmiObject Win32_NetworkAdapterConfiguration -Filter "InterfaceIndex=$idx"
    } catch {
        Write-Log "ERROR" "[GATEWAY] Falha ao consultar o adaptador (índice $idx): $($_.Exception.Message)"
        return $false
    }

    if (-not $cfg) {
        Write-Log "ERROR" "[GATEWAY] Não encontrei a configuração do adaptador (índice $idx). Pulei a troca."
        return $false
    }

    $oldGateways = @($cfg.DefaultIPGateway | Where-Object { $_ })
    if ($oldGateways -notcontains $gwAtual) {
        Write-Log "ERROR" "[GATEWAY] A rota padrão ($gwAtual) não vem da configuração do adaptador (VPN ou rota manual?). Pulei a troca."
        return $false
    }

    # Preserva as métricas atuais de cada gateway
    $oldMetrics = @($cfg.GatewayCostMetric)
    $metrics = @()
    for ($i = 0; $i -lt $oldGateways.Count; $i++) {
        if ($i -lt $oldMetrics.Count -and $oldMetrics[$i] -ne $null) {
            $metrics += [int]$oldMetrics[$i]
        } else {
            $metrics += 1
        }
    }

    # 4) Salvaguardas: o novo gateway precisa estar na sub-rede do adaptador
    #    e não pode ser o próprio IP da máquina
    $naSubrede = $false
    $ipConflito = $false
    $ips = @($cfg.IPAddress)
    $masks = @($cfg.IPSubnet)
    for ($i = 0; $i -lt $ips.Count; $i++) {
        if ($i -lt $masks.Count -and (Test-IPv4 ([string]$ips[$i])) -and (Test-IPv4 ([string]$masks[$i]))) {
            if (Test-SameSubnet -IpA ([string]$ips[$i]) -Mask ([string]$masks[$i]) -IpB $novoGw) { $naSubrede = $true }
            if ([string]$ips[$i] -eq $novoGw) { $ipConflito = $true }
        }
    }
    if ($ipConflito) {
        Write-Log "ERROR" "[GATEWAY] O novo gateway ($novoGw) é o próprio IP desta máquina. Pulei a troca."
        return $false
    }
    if (-not $naSubrede) {
        Write-Log "ERROR" "[GATEWAY] O novo gateway ($novoGw) não está na sub-rede do adaptador (IP/máscara atuais). Pulei a troca."
        return $false
    }

    Write-Log "INFO" "[GATEWAY] Atual: $gwAtual (interface $idx) -> Novo: $novoGw"

    if ($cfg.DHCPEnabled) {
        Write-Log "WARN" "[GATEWAY] Este adaptador usa DHCP. O gateway definido aqui pode ser sobrescrito na renovação da concessão; o ideal é ajustar também no servidor DHCP."
    }

    if ($Simular) {
        Write-Log "INFO" "[GATEWAY] (dry-run) O gateway seria alterado para $novoGw."
        return $true
    }

    if (-not (Test-IsAdmin)) {
        Write-Log "ERROR" "[GATEWAY] Alterar o gateway requer PowerShell como Administrador. Os atalhos foram migrados normalmente; a troca de gateway foi pulada."
        return $false
    }

    # 5) Rede de segurança: agenda a reversão ANTES de mexer na rede
    $marcador = Join-Path $env:TEMP ("migrador_gw_ok_" + [guid]::NewGuid().ToString("N") + ".flag")
    $gwsTxt = (($oldGateways | ForEach-Object { "'" + $_ + "'" }) -join ",")
    $metTxt = ($metrics -join ",")

    $scriptRevert = $RevertTemplate.Replace("__DELAY__", [string]$TimeoutSeg)
    $scriptRevert = $scriptRevert.Replace("__MARKER__", $marcador.Replace("'", "''"))
    $scriptRevert = $scriptRevert.Replace("__IDX__", [string]$idx)
    $scriptRevert = $scriptRevert.Replace("__GWS__", $gwsTxt)
    $scriptRevert = $scriptRevert.Replace("__METRICS__", $metTxt)
    $scriptRevert = $scriptRevert.Replace("__HOST__", $ComputerName)
    $scriptRevert = $scriptRevert.Replace("__LOG__", $LogPath.Replace("'", "''"))

    $b64 = [Convert]::ToBase64String([System.Text.Encoding]::Unicode.GetBytes($scriptRevert))
    $psExe = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
    $cmdLine = "`"$psExe`" -NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -EncodedCommand $b64"

    try {
        $res = ([wmiclass]"Win32_Process").Create($cmdLine)
        if ($res.ReturnValue -ne 0) {
            Write-Log "ERROR" "[GATEWAY] Não consegui agendar a rede de segurança (código $($res.ReturnValue)). Abortando a troca de gateway por precaução."
            return $false
        }
    } catch {
        Write-Log "ERROR" "[GATEWAY] Não consegui agendar a rede de segurança ($($_.Exception.Message)). Abortando a troca de gateway por precaução."
        return $false
    }

    Write-Log "INFO" "[GATEWAY] Rede de segurança agendada: se a conectividade não for confirmada em $TimeoutSeg s, o gateway antigo ($gwAtual) será restaurado automaticamente."

    # 6) Aplica a troca (tempo real + persistente)
    $novoGateways = @()
    foreach ($g in $oldGateways) {
        if ($g -eq $gwAtual) { $novoGateways += $novoGw } else { $novoGateways += $g }
    }

    $codigo = -1
    try {
        $ret = $cfg.SetGateways([string[]]$novoGateways, [uint16[]]$metrics)
        $codigo = [int]$ret.ReturnValue
    } catch {
        Write-Log "ERROR" "[GATEWAY] Falha ao alterar o gateway: $($_.Exception.Message)"
    }

    if ($codigo -ne 0 -and $codigo -ne 1) {
        # Nada foi alterado: cancela a reversão para ela não reescrever a configuração à toa
        try { Set-Content -Path $marcador -Value "cancelado" } catch { }
        Write-Log "ERROR" "[GATEWAY] A troca não foi aplicada (código de retorno $codigo)."
        return $false
    }

    Write-Log "INFO" "[GATEWAY] Gateway alterado para $novoGw (persistente na configuração do adaptador)."
    if ($codigo -eq 1) {
        Write-Log "WARN" "[GATEWAY] O Windows indicou que é necessário reiniciar para concluir a alteração."
    }

    # 7) Confirma conectividade; se OK, cancela a reversão
    Start-Sleep -Seconds 2
    $alcancavel = $false
    try {
        $alcancavel = [bool](Test-Connection -ComputerName $novoGw -Count 3 -Quiet)
    } catch {
        $alcancavel = $false
    }

    if ($alcancavel) {
        try { Set-Content -Path $marcador -Value "ok" } catch {
            Write-Log "WARN" "[GATEWAY] Não consegui gravar o marcador de confirmação ($($_.Exception.Message)); a reversão automática pode ocorrer."
        }
        Write-Log "INFO" "[GATEWAY] Conectividade confirmada com o novo gateway ($novoGw). Reversão automática cancelada."
    } else {
        Write-Log "ERROR" "[GATEWAY] Não confirmei conectividade com o novo gateway ($novoGw). O gateway antigo ($gwAtual) será restaurado automaticamente em até $TimeoutSeg s."
    }

    return $true
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

# --------------------------------------------------------------------------
# Gateway (somente FISICO -> VIRTUAL; os atalhos já foram tratados acima)
# --------------------------------------------------------------------------
if ($Modo -eq "VIRTUAL" -and -not $SemGateway) {
    $gwOk = Invoke-GatewayMigration -Simular $DryRun.IsPresent -TimeoutSeg $GatewayTimeout
    if (-not $gwOk) { $errors++ }
} elseif ($Modo -eq "VIRTUAL" -and $SemGateway) {
    Write-Log "INFO" "[GATEWAY] Pulado por causa de -SemGateway."
}

Write-Log "INFO" "Concluído. $changed atalho(s) alterado(s), $errors erro(s)."

if ($errors -gt 0) {
    exit 1
} else {
    exit 0
}
