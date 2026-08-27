#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Migrador de Atalhos - ssjfarm.com.br
=====================================

Ferramenta de linha de comando para migrar atalhos de área de trabalho
entre o domínio físico (ssjfarm.com.br) e um servidor virtual
(IP:porta), reescrevendo-os para abrir com o Firefox.

Projetada para execução REMOTA e EM MASSA (ex.: via PsExec, Ansible,
SSH, GPO Startup Script) em uma frota mista de:
    - Windows 7/10/11
    - CentOS 6 (Python 2.6 nativo -> requer Python 3 à parte, ver aviso abaixo)
    - Ubuntu (qualquer versão com Python 3)

Uso:
    python3 migrador_ssjfarm.py --modo VIRTUAL
    python3 migrador_ssjfarm.py --modo FISICO --ip 192.168.100.123 --porta 8181
    python3 migrador_ssjfarm.py --modo VIRTUAL --dry-run

Códigos de saída (úteis para orquestração em massa):
    0 - concluído sem erros
    1 - concluído, mas com um ou mais itens com erro (ver log)
    2 - erro fatal (não rodou de fato)
"""

import argparse
import datetime
import logging
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import tempfile

# --------------------------------------------------------------------------
# CONFIGURAÇÕES PADRÃO
# --------------------------------------------------------------------------
DOMINIO_FISICO = "ssjfarm.com.br"
IP_VIRTUAL_PADRAO = "192.168.100.123"
PORTA_VIRTUAL_PADRAO = "8181"
FIREFOX_PATH_WINDOWS = r"C:\Program Files\Mozilla Firefox\firefox.exe"
FIREFOX_BIN_LINUX = "firefox"

HOSTNAME = socket.gethostname()
EXIT_OK = 0
EXIT_ITEM_ERRORS = 1
EXIT_FATAL = 2


# --------------------------------------------------------------------------
# LOGGING (console + arquivo, com hostname, para facilitar auditoria
# quando os logs de várias máquinas forem centralizados)
# --------------------------------------------------------------------------
def setup_logging(log_dir):
    try:
        os.makedirs(log_dir, exist_ok=True)
    except Exception:
        log_dir = tempfile.gettempdir()

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = os.path.join(log_dir, "migrador_{}_{}.log".format(HOSTNAME, ts))

    logger = logging.getLogger("migrador")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    fmt = logging.Formatter(
        "%(asctime)s - {} - [%(levelname)s] - %(message)s".format(HOSTNAME)
    )

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    logger.addHandler(console)

    try:
        fileh = logging.FileHandler(log_path, encoding="utf-8")
        fileh.setFormatter(fmt)
        logger.addHandler(fileh)
    except Exception as e:
        logger.warning("Não foi possível criar arquivo de log (%s). Prosseguindo apenas com console.", e)

    return logger, log_path


def backup_file(path):
    """Copia o arquivo original para um backup oculto antes de qualquer
    alteração. No Linux/CentOS, um nome iniciado com '.' já é tratado como
    oculto por padrão (ls, Nautilus/Files, Dolphin etc.)."""
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    dirname, basename = os.path.split(path)
    backup_name = ".{}.bak-{}".format(basename, ts)
    backup_path = os.path.join(dirname, backup_name)
    try:
        shutil.copy2(path, backup_path)
        return backup_path
    except Exception:
        return None


# --------------------------------------------------------------------------
# WINDOWS
# --------------------------------------------------------------------------
# O script PowerShell roda via -File, com cada valor passado como um
# argumento de PROCESSO separado (não interpolado dentro de uma string
# Python), o que evita o risco de injeção que existia ao montar o bloco
# -Command com .format(). As comparações/substituições usam os métodos
# .Contains()/.Replace() (literais), não -match/-replace (regex), então
# um "$" dentro de um IP ou domínio nunca é interpretado como sintaxe.
_PS1_TEMPLATE = r'''
param(
    [Parameter(Mandatory=$true)][string]$Busca,
    [Parameter(Mandatory=$true)][string]$Troca,
    [Parameter(Mandatory=$true)][string]$FxPath,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$shell = New-Object -ComObject WScript.Shell

# $env:PUBLIC resolve corretamente independente da letra da unidade
# (o bug original tinha "C:\Users\Public\Desktop" fixo)
$locations = @("$env:USERPROFILE\Desktop", "$env:PUBLIC\Desktop")

foreach ($loc in $locations) {
    if (-not (Test-Path $loc)) { continue }

    Get-ChildItem -Path $loc -Filter *.lnk -ErrorAction SilentlyContinue | ForEach-Object {
        $file = $_
        try {
            $s = $shell.CreateShortcut($file.FullName)
            $target = [string]$s.TargetPath
            $args   = [string]$s.Arguments
            $fullCmd = "$target $args"

            if ($fullCmd.Contains($Busca)) {
                $newArgs = $args.Replace($Busca, $Troca)

                # Se a URL estava no TargetPath (atalho aponta direto para a
                # URL) em vez de estar nos Arguments, reconstrói preservando
                # o caminho/URL em vez de descartá-lo.
                if (-not $newArgs.ToLower().Contains("http")) {
                    $newTarget = $target.Replace($Busca, $Troca)
                    if ($newTarget -ne $target -and $newTarget.ToLower().Contains("http")) {
                        $newArgs = $newTarget
                    } else {
                        $newArgs = "https://$Troca"
                    }
                }

                if (-not $DryRun) {
                    Copy-Item -Path $file.FullName -Destination "$($file.FullName).bak" -Force -ErrorAction SilentlyContinue
                    $s.TargetPath = $FxPath
                    $s.Arguments = $newArgs
                    $s.Save()
                }
                Write-Output "OK|$($file.Name)|$newArgs"
            }
        } catch {
            Write-Output "ERR|$($file.Name)|$($_.Exception.Message)"
        }
    }
}
'''


def migrate_windows(logger, busca, troca, dry_run):
    changed = 0
    errors = 0

    fd, ps1_path = tempfile.mkstemp(suffix=".ps1", prefix="migrador_ssjfarm_")
    os.close(fd)
    try:
        with open(ps1_path, "w", encoding="utf-8") as f:
            f.write(_PS1_TEMPLATE)

        cmd = [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy", "Bypass",
            "-File", ps1_path,
            "-Busca", busca,
            "-Troca", troca,
            "-FxPath", FIREFOX_PATH_WINDOWS,
        ]
        if dry_run:
            cmd.append("-DryRun")

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

        if result.returncode != 0 and not result.stdout:
            logger.error("PowerShell falhou (rc=%s): %s", result.returncode, result.stderr.strip())
            return 0, 1

        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split("|", 2)
            if parts[0] == "OK":
                name = parts[1] if len(parts) > 1 else "?"
                logger.info("[OK] Windows: %s%s", name, " (dry-run)" if dry_run else "")
                changed += 1
            elif parts[0] == "ERR":
                name = parts[1] if len(parts) > 1 else "?"
                msg = parts[2] if len(parts) > 2 else ""
                logger.error("[ERRO] Windows: %s - %s", name, msg)
                errors += 1

        if result.stderr.strip():
            logger.warning("PowerShell stderr: %s", result.stderr.strip())

    finally:
        try:
            os.remove(ps1_path)
        except Exception:
            pass

    return changed, errors


# --------------------------------------------------------------------------
# LINUX (Ubuntu + CentOS 6)
# --------------------------------------------------------------------------
def _read_text_any_encoding(path):
    """Lê o arquivo tentando UTF-8 e, se falhar, latin-1 - preservando a
    codificação original em vez de descartar bytes silenciosamente (o bug
    original lia com errors='ignore' e sempre gravava em utf-8, corrompendo
    permanentemente acentos em conteúdo pt-BR)."""
    for enc in ("utf-8", "latin-1"):
        try:
            with open(path, "r", encoding=enc) as f:
                return f.read(), enc
        except (UnicodeDecodeError, LookupError):
            continue
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read(), "utf-8"


def _find_desktop_dirs(logger, include_system):
    home = os.path.expanduser("~")
    candidatos = [
        os.path.join(home, "Área de Trabalho"),   # Ubuntu (pt-BR)
        os.path.join(home, "Área de trabalho"),   # CentOS 6 (pt-BR)
        os.path.join(home, "Desktop"),             # en-US
        os.path.join(home, "Mesa"),                # outras distros pt
        os.path.join(home, ".local/share/applications"),
    ]
    if include_system:
        candidatos.append("/usr/share/applications")

    try:
        cmd = subprocess.run(["xdg-user-dir", "DESKTOP"], capture_output=True, text=True, timeout=5)
        if cmd.returncode == 0 and cmd.stdout.strip():
            candidatos.append(cmd.stdout.strip())
    except Exception:
        pass

    vistos = set()
    dirs = []
    for c in candidatos:
        c = os.path.abspath(c)
        if c not in vistos and os.path.isdir(c):
            vistos.add(c)
            dirs.append(c)
    logger.info("Diretórios a escanear: %s", dirs)
    return dirs


def migrate_linux(logger, busca, troca, dry_run, include_system):
    changed = 0
    errors = 0

    for d in _find_desktop_dirs(logger, include_system):
        try:
            entries = os.listdir(d)
        except PermissionError:
            logger.warning("Sem permissão para listar %s (rode com sudo se precisar migrar atalhos do sistema).", d)
            continue
        except Exception as e:
            logger.error("Falha ao listar %s: %s", d, e)
            errors += 1
            continue

        for item in entries:
            if not item.endswith(".desktop"):
                continue
            path = os.path.join(d, item)

            try:
                content, encoding = _read_text_any_encoding(path)

                if busca not in content:
                    continue

                new_content = content.replace(busca, troca)

                # Verifica "firefox" só na linha Exec= (o bug original checava
                # a palavra no arquivo INTEIRO; um Comment= ou Icon= contendo
                # "firefox" fazia o script pular a correção mesmo quando o
                # Exec= continuava apontando para outro navegador).
                exec_match = re.search(r'^Exec=.*$', new_content, flags=re.M)
                exec_line = exec_match.group(0) if exec_match else ""

                if exec_line and "firefox" not in exec_line.lower():
                    new_content = re.sub(
                        r'^Exec=.*$',
                        "Exec={} https://{}".format(FIREFOX_BIN_LINUX, troca),
                        new_content,
                        count=1,
                        flags=re.M,
                    )
                    logger.warning(
                        "[AVISO] %s: linha Exec= reescrita para abrir apenas a URL base; "
                        "parâmetros do navegador anterior foram descartados.",
                        item,
                    )

                if dry_run:
                    logger.info("[OK] Linux (dry-run): %s (%s)", item, d)
                    changed += 1
                    continue

                backup_file(path)
                with open(path, "w", encoding=encoding) as f:
                    f.write(new_content)

                logger.info("[OK] Linux: %s (%s)", item, d)
                changed += 1

            except PermissionError:
                logger.warning("[ERRO] Sem permissão para escrever em %s (precisa de sudo?).", path)
                errors += 1
            except Exception as e:
                logger.error("[ERRO] Falha ao processar %s: %s", path, e)
                errors += 1

    return changed, errors


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Migração remota/em massa de atalhos ssjfarm.com.br (Windows/CentOS 6/Ubuntu)."
    )
    parser.add_argument("--modo", choices=["VIRTUAL", "FISICO"], required=True,
                         help="VIRTUAL: ssjfarm.com.br -> IP:porta. FISICO: IP:porta -> ssjfarm.com.br.")
    parser.add_argument("--ip", default=IP_VIRTUAL_PADRAO,
                         help="IP do servidor virtual (padrão: {})".format(IP_VIRTUAL_PADRAO))
    parser.add_argument("--porta", default=PORTA_VIRTUAL_PADRAO,
                         help="Porta do servidor virtual (padrão: {})".format(PORTA_VIRTUAL_PADRAO))
    parser.add_argument("--dry-run", action="store_true",
                         help="Mostra o que seria alterado, sem gravar nada em disco.")
    parser.add_argument("--include-system", action="store_true",
                         help="(Linux) Também escaneia /usr/share/applications (requer root).")
    parser.add_argument("--log-dir", default=None,
                         help="Diretório para salvar o log. Padrão: pasta do usuário (Linux) ou "
                              "%%ProgramData%%\\MigradorSSJ\\logs (Windows).")
    args = parser.parse_args()

    is_windows = platform.system() == "Windows"

    if args.log_dir:
        log_dir = args.log_dir
    elif is_windows:
        log_dir = os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"), "MigradorSSJ", "logs")
    else:
        log_dir = os.path.join(os.path.expanduser("~"), ".migrador_ssjfarm", "logs")

    logger, log_path = setup_logging(log_dir)

    if not is_windows and sys.version_info[0] < 3:
        logger.error(
            "Python 2 detectado (padrão de fábrica no CentOS 6). Este script requer Python 3. "
            "Habilite o EPEL e instale python3 (ex.: 'yum install epel-release && yum install python34') "
            "e rode novamente com 'python3 migrador_ssjfarm.py ...'."
        )
        return EXIT_FATAL

    host_virtual = "{}:{}".format(args.ip, args.porta)
    if args.modo == "VIRTUAL":
        busca, troca = DOMINIO_FISICO, host_virtual
    else:
        busca, troca = host_virtual, DOMINIO_FISICO

    logger.info("Host: %s | SO: %s | Modo: %s", HOSTNAME, platform.system(), args.modo)
    logger.info("Migrando: %s -> %s%s", busca, troca, " [DRY-RUN]" if args.dry_run else "")
    logger.info("Log salvo em: %s", log_path)

    try:
        if is_windows:
            changed, errors = migrate_windows(logger, busca, troca, args.dry_run)
        else:
            changed, errors = migrate_linux(logger, busca, troca, args.dry_run, args.include_system)
    except Exception as e:
        logger.exception("Erro fatal não tratado: %s", e)
        return EXIT_FATAL

    logger.info("Concluído. %d atalho(s) alterado(s), %d erro(s).", changed, errors)

    return EXIT_ITEM_ERRORS if errors else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
