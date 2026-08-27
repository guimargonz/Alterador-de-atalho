#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Migrador de Atalhos - ssjfarm.com.br (Linux: Ubuntu + CentOS 6)
==================================================================

Versão enxuta, feita para ser compilada com PyInstaller em um binário
standalone (--onefile), de forma que máquinas SEM Python instalado
consigam rodar o migrador mesmo assim.

IMPORTANTE - build do binário:
    Compile este arquivo NA MÁQUINA MAIS ANTIGA do seu parque (CentOS 6),
    não no Ubuntu. Binários do PyInstaller são compatíveis com versões de
    glibc IGUAIS OU MAIS NOVAS que a usada no build - ou seja, um binário
    compilado no CentOS 6 roda no Ubuntu, mas o inverso não é garantido.

    No CentOS 6 (com Python 3 + pip já instalados via EPEL/SCL):
        pip3 install pyinstaller
        pyinstaller --onefile --name migrador_ssjfarm_linux migrador_ssjfarm_linux.py

    O binário final fica em dist/migrador_ssjfarm_linux - copie só esse
    arquivo para as 15 máquinas Linux, dê permissão de execução e rode.

Uso (script ou binário compilado, mesma sintaxe):
    ./migrador_ssjfarm_linux --modo VIRTUAL --dry-run
    ./migrador_ssjfarm_linux --modo FISICO --ip 192.168.100.123 --porta 8181

Códigos de saída:
    0 - concluído sem erros
    1 - concluído, mas com um ou mais itens com erro
    2 - erro fatal
"""

import argparse
import datetime
import logging
import os
import re
import shutil
import socket
import subprocess
import sys

DOMINIO_FISICO = "ssjfarm.com.br"
IP_VIRTUAL_PADRAO = "192.168.100.123"
PORTA_VIRTUAL_PADRAO = "8181"
FIREFOX_BIN_LINUX = "firefox"

HOSTNAME = socket.gethostname()
EXIT_OK = 0
EXIT_ITEM_ERRORS = 1
EXIT_FATAL = 2


def setup_logging(log_dir):
    try:
        os.makedirs(log_dir, exist_ok=True)
    except Exception:
        log_dir = "/tmp"

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
    """Copia o arquivo original para um backup OCULTO (nome iniciado com
    '.') antes de qualquer alteração."""
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    dirname, basename = os.path.split(path)
    backup_name = ".{}.bak-{}".format(basename, ts)
    backup_path = os.path.join(dirname, backup_name)
    try:
        shutil.copy2(path, backup_path)
        return backup_path
    except Exception:
        return None


def _read_text_any_encoding(path):
    """Lê tentando UTF-8 e, se falhar, latin-1 - preservando a codificação
    original em vez de descartar bytes silenciosamente."""
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


def main():
    parser = argparse.ArgumentParser(
        description="Migração de atalhos ssjfarm.com.br (Linux: Ubuntu / CentOS 6)."
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
                         help="Também escaneia /usr/share/applications (requer root).")
    parser.add_argument("--log-dir", default=None,
                         help="Diretório para salvar o log. Padrão: ~/.migrador_ssjfarm/logs")
    args = parser.parse_args()

    log_dir = args.log_dir or os.path.join(os.path.expanduser("~"), ".migrador_ssjfarm", "logs")
    logger, log_path = setup_logging(log_dir)

    host_virtual = "{}:{}".format(args.ip, args.porta)
    if args.modo == "VIRTUAL":
        busca, troca = DOMINIO_FISICO, host_virtual
    else:
        busca, troca = host_virtual, DOMINIO_FISICO

    logger.info("Host: %s | SO: Linux | Modo: %s", HOSTNAME, args.modo)
    logger.info("Migrando: %s -> %s%s", busca, troca, " [DRY-RUN]" if args.dry_run else "")
    logger.info("Log salvo em: %s", log_path)

    try:
        changed, errors = migrate_linux(logger, busca, troca, args.dry_run, args.include_system)
    except Exception as e:
        logger.exception("Erro fatal não tratado: %s", e)
        return EXIT_FATAL

    logger.info("Concluído. %d atalho(s) alterado(s), %d erro(s).", changed, errors)

    return EXIT_ITEM_ERRORS if errors else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
