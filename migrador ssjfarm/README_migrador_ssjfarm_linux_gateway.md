# Migrador de Atalhos — Linux (`migrador_ssjfarm_linux.py`)

Script para máquinas **Ubuntu** e **CentOS 6** que:

1. **Migra atalhos `.desktop`** entre o servidor físico (`ssjfarm.com.br`) e o
   servidor virtualizado (`IP:porta`), reescrevendo-os para abrir com o Firefox.
2. **Troca o gateway padrão da máquina** para o final `.1` da mesma sub-rede,
   **somente** ao migrar do físico para o virtual (`--modo VIRTUAL`).

Foi pensado para execução remota e em massa (SSH, Ansible etc.), com
`--dry-run`, logs por máquina, backups automáticos e código de saída para
automação.

---

## 1. O que o script faz

### 1.1 Atalhos

| Modo | Troca realizada |
|------|-----------------|
| `--modo VIRTUAL` | `ssjfarm.com.br` → `IP:porta` (padrão `192.168.100.123:8181`) |
| `--modo FISICO`  | `IP:porta` → `ssjfarm.com.br` |

Pastas varridas (se existirem):

- `~/Área de Trabalho`, `~/Área de trabalho`, `~/Desktop`, `~/Mesa`
- `~/.local/share/applications`
- A pasta retornada por `xdg-user-dir DESKTOP`
- `/usr/share/applications` — **somente** com `--include-system` (exige root)

Para cada `.desktop` que contenha o texto procurado:

- O texto é substituído em todo o arquivo.
- Se a linha `Exec=` **não** mencionar `firefox`, ela é reescrita para
  `Exec=firefox https://<destino>` (parâmetros do navegador anterior são
  descartados, e o script registra um `[AVISO]` no log).
- Antes de gravar, o original é copiado para a pasta de backup (seção 8).
- A codificação original do arquivo (UTF-8 ou latin-1) é preservada.

### 1.2 Gateway (somente `--modo VIRTUAL`)

- Lê o gateway atual com `ip route show default`.
- Calcula o novo: **mesmos 3 primeiros octetos + `.1`**.
  Exemplo: `10.5.125.254` → `10.5.125.1`.
- O cálculo parte do **gateway atual da máquina**, não do valor de `--ip`.
- Em `--modo FISICO` o gateway **nunca** é alterado.
- Se o gateway já for `.1`, nada é feito.

---

## 2. Requisitos

| Item | Detalhe |
|------|---------|
| Python | **3.7 ou superior** para rodar o `.py` (o código usa `subprocess.run(capture_output=..., text=...)`). Não é necessário se usar o binário compilado. |
| Comandos usados | `ip` (iproute2) e `ping` para o gateway; `nmcli` é opcional (persistência via NetworkManager) |
| Root (`sudo`) | Só para a troca de gateway e para `--include-system` |
| Firefox | Deve estar instalado e disponível como `firefox` no PATH |

> **Atenção CentOS 6:** o pacote `python34` do EPEL é Python 3.4 e **não**
> atende (falta `capture_output`). Para rodar o `.py` ou compilar o binário,
> é preciso um Python 3.7+ no CentOS 6 (por exemplo, compilado do código-fonte
> com `make altinstall`). Por isso a opção do **binário compilado** é a mais
> prática para a frota.

---

## 3. Instalação

### Opção A — rodar o `.py` direto

```bash
python3 migrador_ssjfarm_linux.py --modo VIRTUAL --dry-run
```

### Opção B — binário standalone (recomendado)

Gere o binário **uma única vez**, na máquina **mais antiga** do parque
(CentOS 6). Binários do PyInstaller rodam em sistemas com glibc igual ou
**mais nova** que a do build; compilado no Ubuntu, não é garantido que rode
no CentOS 6.

```bash
pip3 install pyinstaller
pyinstaller --onefile --name migrador_ssjfarm_linux migrador_ssjfarm_linux.py
# resultado: dist/migrador_ssjfarm_linux
```

Copie só o arquivo `dist/migrador_ssjfarm_linux` para as demais máquinas:

```bash
chmod +x migrador_ssjfarm_linux
```

A sintaxe de uso é idêntica para o `.py` e para o binário.

---

## 4. Parâmetros

| Parâmetro | Obrigatório | Padrão | Descrição |
|-----------|:-----------:|--------|-----------|
| `--modo {VIRTUAL,FISICO}` | ✅ | — | Direção da migração |
| `--ip` | ❌ | `192.168.100.123` | IP do servidor virtual |
| `--porta` | ❌ | `8181` | Porta do servidor virtual |
| `--dry-run` | ❌ | desligado | Simula: não altera atalhos nem rede (apenas grava o log) |
| `--include-system` | ❌ | desligado | Também varre `/usr/share/applications` (root) |
| `--sem-gateway` | ❌ | desligado | Em `VIRTUAL`, migra só os atalhos e **não** mexe no gateway |
| `--gateway-timeout` | ❌ | `90` | Segundos até a reversão automática do gateway (seção 5) |
| `--log-dir` | ❌ | `~/.migrador_ssjfarm/logs` | Pasta do log |

Exemplos:

```bash
# Simulação completa (atalhos + gateway), sem alterar nada
./migrador_ssjfarm_linux --modo VIRTUAL --dry-run

# Só atalhos, sem tocar na rede
./migrador_ssjfarm_linux --modo VIRTUAL --sem-gateway

# Atalhos + gateway (precisa de root para a parte do gateway)
sudo ./migrador_ssjfarm_linux --modo VIRTUAL

# Voltar para o físico (gateway NÃO é alterado)
./migrador_ssjfarm_linux --modo FISICO
```

---

## 5. Como a troca de gateway funciona (e a rede de segurança)

Trocar o gateway de uma máquina **via SSH** pode derrubar a própria sessão se
a nova rota não funcionar. Por isso o fluxo é:

1. Descobre gateway e interface atuais (ex.: `10.5.125.254` em `eth0`).
2. Calcula o novo (`10.5.125.1`).
3. **Agenda a reversão**: um processo desacoplado da sessão (`setsid`) que,
   após `--gateway-timeout` segundos, restaura a rota antiga — **a menos que**
   a troca seja confirmada. Como roda na própria máquina, ele continua
   funcionando mesmo que o SSH caia.
4. Aplica a nova rota em tempo real: `ip route replace default via <novo> dev <iface>`.
5. Tenta **persistir** a mudança:
   - via **NetworkManager** (`nmcli connection modify … ipv4.gateway …` e
     `nmcli connection up …`), ou
   - via arquivo `/etc/sysconfig/network-scripts/ifcfg-<iface>` (estilo
     CentOS/RHEL; faz backup antes de editar).
   - Se nenhum for detectado, a troca vale só até o próximo reboot e o log avisa.
6. Faz `ping` no novo gateway. Se responder, **cancela a reversão** e a troca
   fica definitiva.

### Limitações importantes

- **Ping como confirmação:** se o novo gateway não responder a ICMP, o script
  entende como falha e a reversão automática ocorrerá após o timeout, mesmo que
  a rede estivesse funcionando.
- **A reversão restaura só a rota em tempo de execução.** Se a persistência
  (nmcli/ifcfg) já tiver sido gravada, ela **permanece** com o novo gateway e
  pode voltar a valer após reiniciar a rede ou a máquina. Se a reversão
  automática disparar, confira e corrija a configuração persistida (seção 9).
- O gateway antigo fica registrado no log (`[GATEWAY] Atual: … -> Novo: …`).
  **Guarde os logs** até validar tudo.

---

## 6. Rodando com `sudo` (cuidado com o `HOME`)

Os atalhos ficam na pasta do **usuário**; a troca de gateway exige **root**.
Dependendo da configuração do `sudo`, `~` passa a ser `/root`, e o script
varreria os atalhos errados.

Confira sempre a linha `Diretórios a escanear: [...]` do log. Duas formas
seguras de operar:

**Em duas etapas (recomendado):**

```bash
# 1) Como usuário comum: só os atalhos
./migrador_ssjfarm_linux --modo VIRTUAL --sem-gateway

# 2) Como root: gateway (a varredura de atalhos em /root não encontra nada)
sudo ./migrador_ssjfarm_linux --modo VIRTUAL
```

**Em uma etapa**, preservando o HOME do usuário:

```bash
sudo HOME=/home/usuario ./migrador_ssjfarm_linux --modo VIRTUAL
```

---

## 7. Roteiro de testes (faça nesta ordem)

1. **Dry-run completo** em uma máquina de cada tipo (Ubuntu e CentOS 6):

   ```bash
   sudo ./migrador_ssjfarm_linux --modo VIRTUAL --dry-run
   ```

   Confira no log: quais `.desktop` seriam alterados e a linha
   `[GATEWAY] Atual: X -> Novo: Y`. Verifique se `Y` é o gateway correto da
   sua rede.
2. **Atalhos reais, sem gateway**, em uma máquina de teste:

   ```bash
   ./migrador_ssjfarm_linux --modo VIRTUAL --sem-gateway
   ```

   Abra o atalho e confirme que abre no Firefox no endereço certo.
3. **Gateway real em UMA máquina com acesso físico/console** (não só SSH).
   Confirme que o gateway `.1` existe e roteia de fato (ping, acesso ao servidor
   virtual, acesso à internet se aplicável). Teste também reiniciar a máquina e
   conferir se o gateway persistiu (`ip route show default`).
4. Só então rode nas demais, mantendo a rede de segurança padrão.
5. Teste o caminho de volta (`--modo FISICO`) e confirme que o gateway
   **não** muda.

---

## 8. Logs e backups

| O quê | Onde |
|-------|------|
| Log | `~/.migrador_ssjfarm/logs/migrador_<hostname>_<data>.log` |
| Backup de cada arquivo alterado | `~/.migrador_ssjfarm/backups/<caminho original espelhado>/<arquivo>.bak-<data>` |

Exemplo: `~/Desktop/app.desktop` gera
`~/.migrador_ssjfarm/backups/home/usuario/Desktop/app.desktop.bak-20261006_015106`.

Os backups ficam **fora da Área de Trabalho** para não aparecerem como ícones.
Se o script rodar como root, "home" é o de root (ex.: `/root/.migrador_ssjfarm/`),
inclusive o backup do `ifcfg-<iface>`
(`.../backups/etc/sysconfig/network-scripts/`).

Listar backups:

```bash
find ~/.migrador_ssjfarm/backups -type f
```

---

## 9. Como desfazer (rollback)

**Atalho:**

```bash
find ~/.migrador_ssjfarm/backups -name "MinhaFarmacia.desktop*"
cp ~/.migrador_ssjfarm/backups/home/usuario/Desktop/MinhaFarmacia.desktop.bak-20261006_015106 \
   ~/Desktop/MinhaFarmacia.desktop
```

**Gateway** (use o valor antigo registrado no log):

```bash
# Em tempo de execução
sudo ip route replace default via 10.5.125.254 dev eth0

# Persistência via NetworkManager
sudo nmcli connection modify "NOME_DA_CONEXAO" ipv4.gateway 10.5.125.254
sudo nmcli connection up "NOME_DA_CONEXAO"

# Persistência via ifcfg (CentOS): restaure o backup ou edite GATEWAY=
sudo cp /root/.migrador_ssjfarm/backups/etc/sysconfig/network-scripts/ifcfg-eth0.bak-<data> \
        /etc/sysconfig/network-scripts/ifcfg-eth0
sudo service network restart
```

---

## 10. Execução em massa (SSH)

Sempre em duas etapas e começando por `--dry-run`:

```bash
#!/bin/bash
hosts=("192.168.1.10" "192.168.1.11" "192.168.1.12")
user="seu_usuario"

for h in "${hosts[@]}"; do
    echo "=== $h ==="
    scp migrador_ssjfarm_linux "$user@$h:/tmp/"
    ssh -t "$user@$h" "chmod +x /tmp/migrador_ssjfarm_linux \
        && /tmp/migrador_ssjfarm_linux --modo VIRTUAL --sem-gateway"
    echo "exit code: $?"
done
```

Depois de validar, a etapa do gateway (uma máquina por vez no início):

```bash
ssh -t "$user@$h" "sudo /tmp/migrador_ssjfarm_linux --modo VIRTUAL"
```

O `-t` é necessário para o `sudo` poder pedir senha.

---

## 11. Códigos de saída

| Código | Significado |
|:------:|-------------|
| `0` | Concluído sem erros |
| `1` | Concluído, mas com erro em algum item — **inclui falha na troca de gateway** (ver log) |
| `2` | Erro fatal |

Uma falha no gateway **não** impede a migração dos atalhos (feita antes).

---

## 12. Solução de problemas

| Sintoma | Causa provável / ação |
|---------|-----------------------|
| `the following arguments are required: --modo` | `--modo` é obrigatório em toda execução |
| `TypeError: ... 'capture_output'` | Python anterior ao 3.7. Use o binário compilado ou um Python 3.7+ |
| `[GATEWAY] Comando 'ip' ... não encontrado` | Instale o `iproute`/`iproute2` |
| `[GATEWAY] Alterar o gateway requer root` | Rode a etapa do gateway com `sudo` (seção 6) |
| Nenhum atalho encontrado após `sudo` | O `HOME` virou `/root`; veja `Diretórios a escanear` no log (seção 6) |
| `Sem permissão para escrever em ...` | Arquivo pertence a outro usuário/sistema; use `sudo` e/ou `--include-system` |
| `Não confirmei conectividade com o novo gateway` | O `.1` não responde a ping ou não existe. A reversão ocorrerá em até `--gateway-timeout` s |
| Gateway voltou ao valor antigo após ~90 s | A reversão automática disparou (ver acima); investigue o gateway `.1` antes de repetir |
| Gateway novo sumiu após reboot | A persistência não foi detectada (sem NetworkManager nem `ifcfg`); configure manualmente |
| `[AVISO] ... linha Exec= reescrita` | O atalho usava outro navegador; parâmetros originais foram descartados. Revise se necessário |

---

## 13. Checklist antes da produção

- [ ] `--dry-run` executado em Ubuntu e CentOS 6; atalhos listados conferem.
- [ ] Gateway calculado (`Atual -> Novo`) conferido para cada sub-rede da frota.
- [ ] Gateway `.1` testado com **acesso físico/console** em uma máquina.
- [ ] Persistência após reboot validada.
- [ ] Caminho de volta (`--modo FISICO`) testado, sem alteração de gateway.
- [ ] Logs de todas as máquinas coletados e guardados (contêm o gateway antigo).
