# Migrador de Atalhos — ssjfarm.com.br

Ferramenta para migrar atalhos de área de trabalho entre o domínio físico
(`ssjfarm.com.br`) e um servidor virtual (`IP:porta`), reescrevendo-os para
abrir com o Firefox. Feita para rodar em uma frota mista de **Windows**,
**CentOS 6** e **Ubuntu**, de forma remota e em massa (10–15 máquinas).

---

## 1. Arquivos do projeto

| Arquivo                          | Para quê serve                                    | Precisa de Python no destino? |
|-----------------------------------|----------------------------------------------------|:---:|
| `migrador_ssjfarm_windows.ps1`    | Migração em máquinas **Windows**                   | ❌ Não (usa só PowerShell nativo) |
| `migrador_ssjfarm_linux.py`       | Código-fonte da migração em **Linux** (Ubuntu/CentOS 6) | ✅ Sim, ou compile em binário (seção 4) |
| `migrador_ssjfarm_linux` (binário)| Versão compilada do script Linux, gerada com PyInstaller | ❌ Não |

Use o `.ps1` no Windows e o **binário compilado** no Linux sempre que
possível — assim nenhuma das 15 máquinas precisa ter Python instalado.

---

## 2. Como funciona (resumo)

- **Modo `VIRTUAL`**: troca `ssjfarm.com.br` → `IP:porta` (padrão `192.168.100.123:8181`)
- **Modo `FISICO`**: troca `IP:porta` → `ssjfarm.com.br`
- Todo atalho alterado é reescrito para abrir com o **Firefox**.
- Antes de qualquer alteração, o **original é copiado para um backup oculto**
  (`.bak` no Windows com atributo Hidden; `.nome.bak-<data>` no Linux).
- Existe um modo **`--dry-run` / `-DryRun`** que mostra o que seria alterado
  sem gravar nada em disco — **use sempre antes de rodar de verdade**.
- Tudo fica registrado em log (console + arquivo), identificado pelo nome
  da máquina, para facilitar auditoria quando reunir os logs das 15 máquinas.

---

## 3. Windows — `migrador_ssjfarm_windows.ps1`

### 3.1 Pré-requisitos

- Windows 7 ou superior (PowerShell já vem instalado — nada para baixar).
- Firefox instalado em `C:\Program Files\Mozilla Firefox\firefox.exe`
  (se estiver em outro caminho, avise para ajustarmos o script — ele avisa
  no log se não encontrar, mas não bloqueia a execução).

### 3.2 Testando em uma máquina (antes de qualquer coisa)

1. Copie `migrador_ssjfarm_windows.ps1` para a máquina de teste (ex.:
   `C:\Temp\migrador_ssjfarm_windows.ps1`).
2. Abra o **PowerShell** (não precisa ser como administrador para atalhos
   do usuário atual; precisa se for mexer no Public Desktop de outro usuário).
3. Rode em modo **dry-run** primeiro:

   ```powershell
   powershell -ExecutionPolicy Bypass -File C:\Temp\migrador_ssjfarm_windows.ps1 -Modo VIRTUAL -DryRun
   ```

4. Leia a saída no console. Cada atalho que seria alterado aparece assim:

   ```
   2026-08-27 14:30:12 - PC01 - [INFO] - [OK] MinhaFarmacia.lnk (dry-run) -> 192.168.100.123:8181
   ```

5. Se os atalhos listados forem os esperados, rode **sem** `-DryRun` para
   aplicar de verdade:

   ```powershell
   powershell -ExecutionPolicy Bypass -File C:\Temp\migrador_ssjfarm_windows.ps1 -Modo VIRTUAL
   ```

6. Confirme que os atalhos alterados abrem corretamente no Firefox e no
   endereço certo.

> **Por que `-ExecutionPolicy Bypass`?** Por padrão o Windows bloqueia a
> execução de scripts `.ps1` baixados/copiados de outra máquina. O parâmetro
> `-ExecutionPolicy Bypass` permite rodar só para essa execução, sem alterar
> a política do sistema.

### 3.3 Parâmetros disponíveis

| Parâmetro   | Obrigatório | Padrão                    | Descrição |
|-------------|:---:|----------------------------|-----------|
| `-Modo`     | ✅ | —                          | `VIRTUAL` ou `FISICO` |
| `-Ip`       | ❌ | `192.168.100.123`          | IP do servidor virtual |
| `-Porta`    | ❌ | `8181`                     | Porta do servidor virtual |
| `-DryRun`   | ❌ | desligado                  | Simula sem gravar nada |
| `-LogDir`   | ❌ | `%ProgramData%\MigradorSSJ\logs` | Pasta onde salvar o log |

Exemplo com IP/porta customizados:

```powershell
powershell -ExecutionPolicy Bypass -File .\migrador_ssjfarm_windows.ps1 -Modo FISICO -Ip 10.0.5.20 -Porta 9090
```

### 3.4 Onde ficam os logs e backups

- **Log**: `C:\ProgramData\MigradorSSJ\logs\migrador_<NOME-DO-PC>_<data>.log`
- **Backup de cada atalho alterado**: mesmo local do atalho original, com
  sufixo `.bak` e atributo **Oculto** (não aparece no Explorer com
  configuração padrão). Para ver: `dir /a:h *.bak` no `cmd`, ou marque
  "Mostrar itens ocultos" no Explorer.

### 3.5 Como desfazer (rollback) uma máquina

1. Localize o `.bak` correspondente ao atalho (mesmo nome + `.bak`).
2. Delete o atalho alterado.
3. Renomeie o `.bak` removendo o sufixo `.bak`.
4. (Opcional) Remova o atributo oculto: clique com botão direito → Propriedades → desmarque "Oculto".

---

## 4. Linux — `migrador_ssjfarm_linux.py` (e o binário compilado)

### 4.1 Opção A — rodar o script Python diretamente (se já tiver Python 3)

**Pré-requisitos:**
- Python 3.6+ instalado (`python3 --version` para conferir).
- **Ubuntu**: geralmente já vem com Python 3.
- **CentOS 6**: **não** vem com Python 3 por padrão (só Python 2.6, que não
  serve). É necessário instalar via EPEL antes de usar esta opção:

  ```bash
  sudo yum install epel-release
  sudo yum install python34
  ```

  Se isso não for viável em todas as máquinas CentOS 6, use a **Opção B**
  (binário compilado) — não precisa de Python nenhum no destino.

**Testando (dry-run):**

```bash
python3 migrador_ssjfarm_linux.py --modo VIRTUAL --dry-run
```

**Rodando de verdade:**

```bash
python3 migrador_ssjfarm_linux.py --modo VIRTUAL
```

### 4.2 Opção B — compilar um binário standalone (recomendado para a frota)

Essa opção gera **um único arquivo executável** que não depende de Python
estar instalado na máquina de destino — ideal para as 15 máquinas,
principalmente as CentOS 6.

> ⚠️ **Importante:** compile **na máquina CentOS 6**, não no Ubuntu. Um
> binário do PyInstaller é compatível com versões de `glibc` iguais ou
> **mais novas** que a usada na compilação — ou seja, um binário compilado
> no CentOS 6 roda também no Ubuntu, mas o contrário não é garantido.

**Passo a passo (rodar uma vez, na máquina CentOS 6 usada para o build):**

1. Instale Python 3 e pip (se ainda não tiver, ver seção 4.1):

   ```bash
   sudo yum install epel-release
   sudo yum install python34 python34-pip
   ```

2. Instale o PyInstaller:

   ```bash
   pip3 install pyinstaller
   ```

3. Compile o binário:

   ```bash
   pyinstaller --onefile --name migrador_ssjfarm_linux migrador_ssjfarm_linux.py
   ```

4. O executável final fica em:

   ```
   dist/migrador_ssjfarm_linux
   ```

   Esse é o **único arquivo** que você precisa copiar para as outras 14
   máquinas Linux. Não precisa levar o código-fonte `.py` nem instalar nada
   nelas.

### 4.3 Testando o binário em uma máquina

1. Copie `migrador_ssjfarm_linux` para a máquina de teste (ex.: `/tmp/`).
2. Dê permissão de execução:

   ```bash
   chmod +x /tmp/migrador_ssjfarm_linux
   ```

3. Rode em dry-run:

   ```bash
   /tmp/migrador_ssjfarm_linux --modo VIRTUAL --dry-run
   ```

4. Leia a saída — cada `.desktop` que seria alterado aparece com `[OK]`.
5. Se estiver correto, rode de verdade (sem `--dry-run`):

   ```bash
   /tmp/migrador_ssjfarm_linux --modo VIRTUAL
   ```

6. Abra o atalho migrado e confirme que abre no Firefox, no endereço certo.

### 4.4 Parâmetros disponíveis (idênticos no `.py` e no binário)

| Parâmetro          | Obrigatório | Padrão                        | Descrição |
|---------------------|:---:|--------------------------------|-----------|
| `--modo`             | ✅ | —                              | `VIRTUAL` ou `FISICO` |
| `--ip`               | ❌ | `192.168.100.123`              | IP do servidor virtual |
| `--porta`            | ❌ | `8181`                         | Porta do servidor virtual |
| `--dry-run`          | ❌ | desligado                      | Simula sem gravar nada |
| `--include-system`   | ❌ | desligado                      | Também escaneia `/usr/share/applications` (precisa de `sudo`) |
| `--log-dir`          | ❌ | `~/.migrador_ssjfarm/logs`     | Pasta onde salvar o log |

Exemplo completo:

```bash
sudo /tmp/migrador_ssjfarm_linux --modo FISICO --ip 10.0.5.20 --porta 9090 --include-system
```

> Use `sudo` **apenas** se precisar de `--include-system` (atalhos do
> sistema em `/usr/share/applications`). Para atalhos normais de área de
> trabalho do usuário, **não** rode como root — o script precisa acessar a
> pasta pessoal (`~/Desktop` ou `~/Área de Trabalho`) do usuário logado.

### 4.5 Onde ficam os logs e backups

- **Log**: `~/.migrador_ssjfarm/logs/migrador_<hostname>_<data>.log`
- **Backup de cada `.desktop` alterado**: mesma pasta do arquivo original,
  com nome iniciado por `.` (oculto por padrão no `ls`, Nautilus, Dolphin
  etc.), no formato `.nome-original.desktop.bak-<data>`.

Para ver os backups:

```bash
ls -la ~/Desktop        # ou ~/"Área de Trabalho"
```

### 4.6 Como desfazer (rollback) uma máquina

```bash
# Exemplo: restaurar um atalho específico
cp ~/Desktop/.MinhaFarmacia.desktop.bak-20260827_143012 ~/Desktop/MinhaFarmacia.desktop
```

---

## 5. Execução em massa (15 máquinas de uma vez)

### 5.1 Windows via PsExec

```powershell
$windowsHosts = "PC01","PC02","PC03"

foreach ($h in $windowsHosts) {
    Copy-Item .\migrador_ssjfarm_windows.ps1 "\\$h\C$\Temp\migrador_ssjfarm_windows.ps1" -Force

    # Dry-run primeiro
    psexec \\$h -u DOMAIN\admin -p SENHA -h `
        powershell -ExecutionPolicy Bypass -File C:\Temp\migrador_ssjfarm_windows.ps1 -Modo VIRTUAL -DryRun
}
```

Depois de conferir os logs, repita **sem `-DryRun`** para aplicar de verdade.

### 5.2 Linux via SSH (com o binário compilado)

```bash
#!/bin/bash
linux_hosts=("192.168.1.10" "192.168.1.11" "192.168.1.12")
user="seu_usuario"

for h in "${linux_hosts[@]}"; do
    echo "=== $h ==="
    scp dist/migrador_ssjfarm_linux "$user@$h:/tmp/"
    ssh "$user@$h" "chmod +x /tmp/migrador_ssjfarm_linux && /tmp/migrador_ssjfarm_linux --modo VIRTUAL --dry-run"
done
```

Depois de conferir os logs, repita **sem `--dry-run`**.

### 5.3 Ansible (Windows via WinRM + Linux via SSH, tudo em um playbook)

Ver o playbook `migrar.yml` compartilhado anteriormente na conversa. Rodar
dry-run em toda a frota de uma vez:

```bash
ansible-playbook -i inventory.ini migrar.yml
```

E para valer (sobrescrevendo a variável de dry-run):

```bash
ansible-playbook -i inventory.ini migrar.yml -e "dry_run_flag="
```

---

## 6. Checklist antes de rodar em produção nas 15 máquinas

- [ ] Rodei `-DryRun` / `--dry-run` em pelo menos **1 máquina de cada tipo**
      (Windows, Ubuntu, CentOS 6) e a lista de atalhos afetados bate com o
      esperado.
- [ ] Rodei **sem** dry-run em 1 máquina de cada tipo e confirmei que os
      atalhos abrem certo no Firefox, no endereço correto.
- [ ] Confirmei o caminho do Firefox nas máquinas Windows (o script avisa
      no log se não encontrar em `C:\Program Files\Mozilla Firefox\firefox.exe`).
- [ ] Se for usar o binário Linux, ele foi **compilado no CentOS 6** (não no
      Ubuntu), para garantir compatibilidade de `glibc` em ambas as distros.
- [ ] Sei onde ficam os backups em cada SO, caso precise reverter algo
      (seções 3.5 e 4.6 deste README).
- [ ] Tenho um plano para coletar os logs das 15 máquinas depois da
      execução (`scp`/`Copy-Item` de volta para uma pasta central), para
      conferir rapidamente se algum host teve erro.

---

## 7. Códigos de saída (para automação/orquestração)

| Código | Significado |
|:---:|---|
| `0` | Concluído sem erros |
| `1` | Concluído, mas com erro em um ou mais itens (ver log) |
| `2` | Erro fatal — o script não concluiu a execução |

Válido tanto para o `.ps1` (Windows) quanto para o `.py`/binário (Linux).
Útil para o PsExec/Ansible/SSH sinalizarem automaticamente qual máquina
falhou, sem precisar ler os 15 logs manualmente.

---

## 8. Perguntas frequentes / solução de problemas

**"não é reconhecido como um comando interno"** (Windows)
Você digitou só os parâmetros (`-Modo VIRTUAL ...`) sem `powershell -File
caminho\do\script.ps1` na frente. É preciso sempre incluir o comando
completo — ver exemplo na seção 3.2.

**"cannot be loaded because running scripts is disabled"** (Windows)
Faltou o `-ExecutionPolicy Bypass` no comando. Ele não altera nada
permanentemente no sistema, só libera essa execução específica.

**Script Python não roda no CentOS 6**
Quase certo que é porque só existe Python 2 na máquina. Ou instale Python 3
via EPEL (seção 4.1), ou use o binário compilado (seção 4.2) — que não
depende de Python estar instalado.

**"the following arguments are required: --modo" / "-Modo"**
`--modo`/`-Modo` é obrigatório em toda execução. Sempre informe `VIRTUAL`
ou `FISICO`.

**Quero saber quantos atalhos serão afetados antes de mexer em nada**
Rode sempre com `--dry-run` / `-DryRun` primeiro — não grava nada em disco,
só mostra no log o que seria alterado.

**Um atalho ficou errado depois da migração**
Veja a seção 3.5 (Windows) ou 4.6 (Linux) para restaurar a partir do
backup oculto que o script cria automaticamente antes de qualquer alteração.
