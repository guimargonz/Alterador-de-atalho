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

NOVO - alteração automática de gateway (somente FISICO -> VIRTUAL):
    Quando --modo VIRTUAL, além de migrar os atalhos, o script também troca
    o gateway padrão da máquina para "<sub-rede do gateway atual>.1". Ex.:
    se o gateway atual é 10.5.125.254, o novo gateway será 10.5.125.1.
    Ao migrar de volta (--modo FISICO) o gateway NÃO é alterado.

    Isso requer root (sudo) e é uma operação de risco quando feita via SSH
    remoto: se a nova rota não funcionar, a própria sessão pode cair. Por
    isso existe uma rede de segurança (ver GATEWAY_REVERT_TIMEOUT_PADRAO):
    a troca é agendada para reverter automaticamente ao gateway antigo caso
    a conectividade não seja confirmada a tempo - mesmo que a sessão SSH
    caia no meio do processo, a reversão roda de forma desacoplada na
    própria máquina.

    Use --sem-gateway para pular essa etapa (só migrar os atalhos).

Códigos de saída:
    0 - concluído sem erros
    1 - concluído, mas com um ou mais itens com erro
    2 - erro fatal
"""

import argparse
import datetime
import ipaddress
import logging
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile

DOMINIO_FISICO = "ssjfarm.com.br"
IP_VIRTUAL_PADRAO = "192.168.100.123"
PORTA_VIRTUAL_PADRAO = "8181"
FIREFOX_BIN_LINUX = "firefox"
GATEWAY_REVERT_TIMEOUT_PADRAO = 90  # segundos até reverter automaticamente

HOSTNAME = socket.gethostname()
EXIT_OK = 0
EXIT_ITEM_ERRORS = 1
EXIT_FATAL = 2


def _run(cmd, timeout=None, check=False):
    """subprocess.run compatível com Python 3.5+.

    Os argumentos capture_output= e text= só existem a partir do Python 3.7;
    em versões anteriores causam "TypeError: __init__() got an unexpected
    keyword argument 'capture_output'". Esta função usa os equivalentes
    antigos (stdout/stderr=PIPE e universal_newlines=True)."""
    return subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
        timeout=timeout,
        check=check,
    )


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


BACKUP_ROOT = os.path.join(os.path.expanduser("~"), ".migrador_ssjfarm", "backups")


def backup_file(path):
    """Copia o arquivo original para uma pasta de backup separada
    (~/.migrador_ssjfarm/backups), fora da Área de Trabalho.

    Alguns ambientes gráficos (Nautilus/Files, Cinnamon, XFCE em algumas
    versões) renderizam qualquer arquivo *.desktop presente na pasta da
    área de trabalho como ícone, mesmo que o nome comece com '.' - ou seja,
    prefixar com ponto não é suficiente para "esconder" o backup do usuário.
    Guardar o backup em outra pasta resolve isso de vez, além de manter a
    Área de Trabalho limpa.

    A estrutura de diretórios original é espelhada dentro da pasta de
    backup (ex.: um arquivo em ~/Desktop/app.desktop vira
    ~/.migrador_ssjfarm/backups/home/usuario/Desktop/app.desktop.bak-<data>)
    para evitar colisão de nomes entre pastas diferentes (Desktop,
    .local/share/applications, etc.)."""
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    abs_path = os.path.abspath(path)
    orig_dir = os.path.dirname(abs_path).lstrip(os.sep)
    basename = os.path.basename(abs_path)

    target_dir = os.path.join(BACKUP_ROOT, orig_dir)
    backup_path = os.path.join(target_dir, "{}.bak-{}".format(basename, ts))

    try:
        os.makedirs(target_dir, exist_ok=True)
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
        cmd = _run(["xdg-user-dir", "DESKTOP"], timeout=5)
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


# --------------------------------------------------------------------------
# GATEWAY (somente FISICO -> VIRTUAL)
# --------------------------------------------------------------------------
def _is_root():
    try:
        return os.geteuid() == 0
    except AttributeError:
        return False


def _get_default_route(logger):
    """Retorna (gateway_atual, interface) lendo `ip route show default`."""
    try:
        result = _run(["ip", "route", "show", "default"], timeout=5)
    except FileNotFoundError:
        logger.error("[GATEWAY] Comando 'ip' (pacote iproute2) não encontrado nesta máquina.")
        return None, None
    except Exception as e:
        logger.error("[GATEWAY] Falha ao consultar a rota padrão: %s", e)
        return None, None

    if result.returncode != 0 or not result.stdout.strip():
        logger.error("[GATEWAY] Não há rota padrão configurada ou falha ao lê-la.")
        return None, None

    linha = result.stdout.strip().splitlines()[0]
    m = re.search(r"default via (\S+) dev (\S+)", linha)
    if not m:
        logger.error("[GATEWAY] Não consegui interpretar a rota padrão: %s", linha)
        return None, None
    return m.group(1), m.group(2)


def _compute_new_gateway(gw_atual):
    """Mesma sub-rede do gateway atual, trocando o último octeto para 1.
    Ex.: 10.5.125.254 -> 10.5.125.1"""
    try:
        ipaddress.IPv4Address(gw_atual)
    except Exception:
        return None
    partes = gw_atual.split(".")
    return "{}.{}.{}.1".format(partes[0], partes[1], partes[2])


def _check_connectivity(alvo, tentativas=2, timeout=3):
    try:
        result = _run(
            ["ping", "-c", str(tentativas), "-W", str(timeout), alvo],
            timeout=timeout * (tentativas + 1),
        )
        return result.returncode == 0
    except Exception:
        return False


def _schedule_revert(logger, comando_revert, delay_segundos):
    """Agenda `comando_revert` para rodar em `delay_segundos`, de forma
    desacoplada da sessão atual (sobrevive mesmo que o SSH caia). Retorna
    o caminho de um arquivo-marcador: se ele existir quando o tempo acabar,
    a reversão é CANCELADA (ou seja, para confirmar sucesso, cria-se esse
    arquivo; para permitir a reversão, não faz nada)."""
    try:
        marcador = tempfile.mktemp(prefix="migrador_gw_ok_", suffix=".flag")
        script = (
            "sleep {delay}; "
            "if [ ! -f '{marcador}' ]; then {cmd}; fi"
        ).format(delay=delay_segundos, marcador=marcador, cmd=comando_revert)

        subprocess.Popen(
            ["setsid", "bash", "-c", script],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        logger.info(
            "[GATEWAY] Rede de segurança agendada: se a conectividade não for confirmada em %ss, "
            "o gateway antigo será restaurado automaticamente.",
            delay_segundos,
        )
        return marcador
    except Exception as e:
        logger.error("[GATEWAY] Não consegui agendar a rede de segurança (%s). Abortando troca de gateway por precaução.", e)
        return False  # False (não None) sinaliza falha no agendamento, tratado como erro fatal da etapa


def _confirm_revert_cancelled(logger, marcador):
    """Cria o arquivo-marcador, cancelando a reversão automática agendada."""
    if not marcador:
        return
    try:
        with open(marcador, "w") as f:
            f.write("ok")
    except Exception as e:
        logger.warning("[GATEWAY] Não consegui confirmar o cancelamento da reversão (marcador %s): %s", marcador, e)


def _persist_gateway(logger, gateway, iface):
    """Tenta deixar a troca de gateway permanente (sobrevivendo a reboot).
    Tenta NetworkManager (nmcli) primeiro; se não houver, tenta o estilo
    CentOS/RHEL (ifcfg-<iface>). Retorna True se persistiu de alguma forma."""
    try:
        conn = _run(
            ["nmcli", "-t", "-f", "NAME,DEVICE", "connection", "show", "--active"],
            timeout=5,
        )
        if conn.returncode == 0:
            for linha in conn.stdout.strip().splitlines():
                partes = linha.split(":")
                if len(partes) == 2 and partes[1] == iface:
                    nome_conexao = partes[0]
                    _run(
                        ["nmcli", "connection", "modify", nome_conexao, "ipv4.gateway", gateway],
                        timeout=10, check=True,
                    )
                    _run(
                        ["nmcli", "connection", "up", nome_conexao],
                        timeout=15, check=True,
                    )
                    logger.info("[GATEWAY] Persistido via NetworkManager (conexão '%s').", nome_conexao)
                    return True
    except FileNotFoundError:
        pass
    except Exception as e:
        logger.warning("[GATEWAY] Tentativa de persistir via NetworkManager falhou: %s", e)

    ifcfg_path = "/etc/sysconfig/network-scripts/ifcfg-{}".format(iface)
    if os.path.isfile(ifcfg_path):
        try:
            with open(ifcfg_path, "r") as f:
                linhas = f.readlines()

            novas_linhas = []
            achou = False
            for linha in linhas:
                if linha.strip().startswith("GATEWAY="):
                    novas_linhas.append("GATEWAY={}\n".format(gateway))
                    achou = True
                else:
                    novas_linhas.append(linha)
            if not achou:
                novas_linhas.append("GATEWAY={}\n".format(gateway))

            backup_file(ifcfg_path)
            with open(ifcfg_path, "w") as f:
                f.writelines(novas_linhas)

            logger.info(
                "[GATEWAY] Persistido em %s. Pode ser necessário reiniciar o serviço de rede "
                "('service network restart') para garantir após reboot.",
                ifcfg_path,
            )
            return True
        except Exception as e:
            logger.warning("[GATEWAY] Falha ao persistir em %s: %s", ifcfg_path, e)

    logger.warning(
        "[GATEWAY] Não identifiquei NetworkManager nem arquivo ifcfg para a interface %s. "
        "A troca foi aplicada só em tempo de execução (não sobrevive a um reboot) - "
        "ajuste manualmente a persistência se necessário.",
        iface,
    )
    return False


def migrate_gateway(logger, dry_run, revert_timeout):
    """Troca o gateway padrão para '<sub-rede do gateway atual>.1'.
    Só deve ser chamada quando modo == VIRTUAL. Retorna True em sucesso
    (ou dry-run/no-op), False em caso de erro."""
    gw_atual, iface = _get_default_route(logger)
    if not iface:
        logger.error("[GATEWAY] Pulei a troca de gateway: não detectei a rota padrão atual.")
        return False

    novo_gw = _compute_new_gateway(gw_atual)
    if not novo_gw:
        logger.error("[GATEWAY] Gateway atual '%s' não é um IPv4 válido. Pulei a troca.", gw_atual)
        return False

    if gw_atual == novo_gw:
        logger.info("[GATEWAY] Gateway já é %s. Nada a fazer.", novo_gw)
        return True

    logger.info("[GATEWAY] Atual: %s (interface %s) -> Novo: %s", gw_atual, iface, novo_gw)

    if dry_run:
        logger.info("[GATEWAY] (dry-run) O gateway seria alterado para %s.", novo_gw)
        return True

    if not _is_root():
        logger.error(
            "[GATEWAY] Alterar o gateway requer root (rode com sudo). "
            "Os atalhos já foram migrados normalmente; a troca de gateway foi pulada."
        )
        return False

    comando_revert = "ip route replace default via {} dev {}".format(gw_atual, iface)
    marcador = _schedule_revert(logger, comando_revert, revert_timeout)
    if marcador is False:
        return False

    try:
        _run(
            ["ip", "route", "replace", "default", "via", novo_gw, "dev", iface],
            timeout=10, check=True,
        )
        logger.info("[GATEWAY] Rota padrão alterada em tempo real para %s.", novo_gw)
    except subprocess.CalledProcessError as e:
        logger.error("[GATEWAY] Falha ao alterar a rota padrão: %s", e.stderr)
        return False
    except Exception as e:
        logger.error("[GATEWAY] Falha ao alterar a rota padrão: %s", e)
        return False

    persistido = _persist_gateway(logger, novo_gw, iface)

    if _check_connectivity(novo_gw):
        logger.info("[GATEWAY] Conectividade confirmada com o novo gateway (%s). Reversão automática cancelada.", novo_gw)
        _confirm_revert_cancelled(logger, marcador)
    else:
        logger.error(
            "[GATEWAY] Não confirmei conectividade com o novo gateway (%s). "
            "Se esta sessão cair, o gateway antigo (%s) será restaurado automaticamente em até %ss.",
            novo_gw, gw_atual, revert_timeout,
        )

    if not persistido:
        logger.warning(
            "[GATEWAY] Atenção: a troca pode não sobreviver a um reboot nesta máquina (ver aviso acima)."
        )

    return True


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
                         help="Mostra o que seria alterado, sem gravar nada em disco nem mexer na rede.")
    parser.add_argument("--include-system", action="store_true",
                         help="Também escaneia /usr/share/applications (requer root).")
    parser.add_argument("--sem-gateway", action="store_true",
                         help="Não altera o gateway padrão, mesmo em --modo VIRTUAL (só migra os atalhos).")
    parser.add_argument("--gateway-timeout", type=int, default=GATEWAY_REVERT_TIMEOUT_PADRAO,
                         help="Segundos até reverter automaticamente o gateway se a conectividade "
                              "não for confirmada (padrão: {}).".format(GATEWAY_REVERT_TIMEOUT_PADRAO))
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

    if args.modo == "VIRTUAL" and not args.sem_gateway:
        ok = migrate_gateway(logger, args.dry_run, args.gateway_timeout)
        if not ok:
            errors += 1
    elif args.modo == "VIRTUAL" and args.sem_gateway:
        logger.info("[GATEWAY] Pulado por causa de --sem-gateway.")

    logger.info("Concluído. %d atalho(s) alterado(s), %d erro(s).", changed, errors)

    return EXIT_ITEM_ERRORS if errors else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
