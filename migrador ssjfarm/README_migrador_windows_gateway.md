# Migrador de Atalhos — Windows (`migrador_ssjfarm_windows.ps1`)

Script 100% PowerShell (nada para instalar) para máquinas **Windows** que:

1. **Migra atalhos `.lnk`** da área de trabalho entre o servidor físico
   (`ssjfarm.com.br`) e o servidor virtualizado (`IP:porta`), reescrevendo-os
   para abrir com o Firefox.
2. **Troca o gateway padrão da máquina** para o final `.1` da mesma sub-rede,
   **somente** ao migrar do físico para o virtual (`-Modo VIRTUAL`).

Foi pensado para execução remota e em massa (PsExec etc.), com `-DryRun`, log
por máquina, backup automático dos atalhos e código de saída para automação.

> **Status de validação:** a parte dos **atalhos** é a mesma lógica já testada
> em campo. A parte do **gateway é nova** e foi escrita sem possibilidade de
> execução em uma máquina Windows real — siga o roteiro de testes da seção 7
> (com acesso físico/console) antes de usar em produção.

---

## 1. O que o script faz

### 1.1 Atalhos

| Modo | Troca realizada |
|------|-----------------|
| `-Modo VIRTUAL` | `ssjfarm.com.br` → `IP:porta` (padrão `192.168.100.123:8181`) |
| `-Modo FISICO`  | `IP:porta` → `ssjfarm.com.br` |

Pastas varridas: `%USERPROFILE%\Desktop` e `%PUBLIC%\Desktop`
(somente arquivos `.lnk`; atalhos de internet `.url` não são tratados).

Para cada atalho cujo destino + argumentos contenham o texto procurado:

- O texto é substituído nos **argumentos**.
- Se a URL estava no **destino** do atalho (e não nos argumentos), ela é
  reconstruída a partir dele, preservando caminho e parâmetros. Se mesmo assim
  não houver `http`, usa `https://<destino>`.
- O destino do atalho passa a ser o Firefox
  (`C:\Program Files\Mozilla Firefox\firefox.exe`).
- Antes de gravar, o original é copiado para `<atalho>.lnk.bak` com atributo
  **Oculto** (seção 8).

### 1.2 Gateway (somente `-Modo VIRTUAL`)

- Lê a rota padrão atual (a de menor métrica) pelo WMI.
- Calcula o novo gateway: **mesmos 3 primeiros octetos + `.1`**.
  Exemplo: `10.5.125.254` → `10.5.125.1`.
- O cálculo parte do **gateway atual da máquina**, não do valor de `-Ip`.
- Em `-Modo FISICO` o gateway **nunca** é alterado.
- Se o gateway já for `.1`, nada é feito.
- A alteração é feita na configuração do adaptador (WMI `SetGateways`), portanto
  vale na hora **e** persiste após reiniciar.

---

## 2. Requisitos

| Item | Detalhe |
|------|---------|
| Windows | 7 ou superior |
| PowerShell | **Windows PowerShell** (`powershell.exe`) 2.0+. Não use o PowerShell 7 (`pwsh`): ele não tem `Get-WmiObject` |
| Firefox | Em `C:\Program Files\Mozilla Firefox\firefox.exe` (se não existir, o script avisa no log, mas reescreve os atalhos mesmo assim) |
| Administrador | **Somente** para a troca de gateway e para gravar atalhos da área de trabalho pública |
| Rede | A parte do gateway só usa recursos locais (WMI e ping ao novo gateway) |

---

## 3. Preparação

1. Copie `migrador_ssjfarm_windows.ps1` para a máquina (ex.: `C:\Temp\`).
2. Rode sempre com `powershell -ExecutionPolicy Bypass -File ...`. O Windows
   bloqueia scripts copiados de outra máquina por padrão; o `Bypass` libera
   apenas essa execução, sem alterar a política do sistema.

O arquivo é gravado em UTF-8 com BOM, para os acentos aparecerem corretamente
nos logs. Se for editá-lo, mantenha essa codificação.

---

## 4. Parâmetros

| Parâmetro | Obrigatório | Padrão | Descrição |
|-----------|:-----------:|--------|-----------|
| `-Modo` | ✅ | — | `VIRTUAL` ou `FISICO` |
| `-Ip` | ❌ | `192.168.100.123` | IP do servidor virtual |
| `-Porta` | ❌ | `8181` | Porta do servidor virtual |
| `-DryRun` | ❌ | desligado | Simula: não altera atalhos nem rede (apenas grava o log) |
| `-SemGateway` | ❌ | desligado | Em `VIRTUAL`, migra só os atalhos e **não** mexe no gateway |
| `-GatewayTimeout` | ❌ | `90` | Segundos até a reversão automática do gateway (10 a 600) |
| `-LogDir` | ❌ | `%ProgramData%\MigradorSSJ\logs` | Pasta do log |

Exemplos:

```powershell
# Simulação completa (atalhos + gateway), sem alterar nada
powershell -ExecutionPolicy Bypass -File C:\Temp\migrador_ssjfarm_windows.ps1 -Modo VIRTUAL -DryRun

# Só atalhos, sem tocar na rede
powershell -ExecutionPolicy Bypass -File C:\Temp\migrador_ssjfarm_windows.ps1 -Modo VIRTUAL -SemGateway

# Atalhos + gateway (PowerShell como Administrador)
powershell -ExecutionPolicy Bypass -File C:\Temp\migrador_ssjfarm_windows.ps1 -Modo VIRTUAL

# IP/porta diferentes e timeout de reversão maior
powershell -ExecutionPolicy Bypass -File C:\Temp\migrador_ssjfarm_windows.ps1 -Modo VIRTUAL -Ip 10.0.5.20 -Porta 9090 -GatewayTimeout 120

# Voltar para o físico (gateway NÃO é alterado)
powershell -ExecutionPolicy Bypass -File C:\Temp\migrador_ssjfarm_windows.ps1 -Modo FISICO
```

---

## 5. Como a troca de gateway funciona (e a rede de segurança)

Trocar o gateway de uma máquina **remotamente** pode derrubar a própria sessão
(PsExec, WinRM) se a nova rota não funcionar. Por isso o fluxo é:

1. Descobre a rota padrão (gateway e interface) pelo WMI.
2. Calcula o novo gateway (`.1`).
3. **Salvaguardas** — a troca é pulada, com erro no log, se:
   - a rota padrão não vier da configuração do adaptador (VPN ou rota manual);
   - o novo gateway não estiver na **sub-rede** do adaptador (IP/máscara atuais);
   - o novo gateway for o **próprio IP** da máquina.
4. Em `-DryRun`, mostra `Atual -> Novo` e para aqui.
5. Exige **Administrador**; sem isso, pula a troca (os atalhos já foram migrados).
6. **Agenda a reversão**: cria um processo PowerShell separado (via WMI,
   desacoplado da sessão — continua rodando mesmo que o PsExec caia). Ele
   espera `-GatewayTimeout` segundos e, **a menos que a troca seja
   confirmada**, restaura o gateway antigo e registra no log.
7. Aplica o novo gateway com `SetGateways`, preservando a métrica atual.
   Se a chamada falhar, a reversão é cancelada (nada foi alterado).
8. Aguarda 2 s e faz `ping` (3 tentativas) no novo gateway. Se responder,
   **cancela a reversão** e a troca fica definitiva.

Como a reversão usa o mesmo `SetGateways`, ela restaura também a configuração
persistida do adaptador.

### Limitações importantes

- **Ping como confirmação:** se o novo gateway não responder a ICMP, o script
  entende como falha e reverte após o timeout, mesmo com a rede funcionando.
- **DHCP:** em adaptadores com DHCP o script avisa no log. O gateway definido
  localmente pode ser sobrescrito na renovação da concessão; o ideal é ajustar
  também no servidor DHCP. Nesse caso, a reversão grava o gateway antigo como
  fixo. Esse cenário não foi validado.
- **Reinício:** se o Windows retornar código `1` do `SetGateways`, o log avisa
  que é necessário reiniciar para concluir.
- O gateway antigo fica registrado no log (`[GATEWAY] Atual: … -> Novo: …`).
  **Guarde os logs** até validar tudo.

---

## 6. Contas e privilégios (leia antes de rodar remotamente)

Os atalhos ficam no **perfil do usuário**; o gateway exige **Administrador**.
Rodando como `SYSTEM` (`psexec -s`), `%USERPROFILE%` é o perfil do SYSTEM, que
não tem os atalhos do usuário — só a área de trabalho **pública** é alcançada.
Rodando como usuário comum, a área de trabalho pública não pode ser gravada.

Por isso, o caminho mais seguro é em **duas etapas**:

1. **Atalhos do usuário** — executando como o próprio usuário da farmácia (ou
   localmente, ou por script de logon/GPO), sem gateway:

   ```powershell
   powershell -ExecutionPolicy Bypass -File C:\Temp\migrador_ssjfarm_windows.ps1 -Modo VIRTUAL -SemGateway
   ```

   Atalhos da área de trabalho pública darão erro de permissão nesta etapa
   (esperado, conta como erro no código de saída); a etapa 2 os trata.

2. **Gateway (e atalhos públicos)** — como Administrador ou `SYSTEM`:

   ```powershell
   powershell -ExecutionPolicy Bypass -File C:\Temp\migrador_ssjfarm_windows.ps1 -Modo VIRTUAL
   ```

Se o usuário logado já for administrador e o PowerShell for aberto
"como Administrador", uma única execução cobre tudo.

---

## 7. Roteiro de testes (nesta ordem)

1. **Dry-run completo** em uma máquina de teste:

   ```powershell
   powershell -ExecutionPolicy Bypass -File C:\Temp\migrador_ssjfarm_windows.ps1 -Modo VIRTUAL -DryRun
   ```

   Confira no log:
   - os atalhos listados: `[OK] Nome.lnk (dry-run) -> <novos argumentos>`;
   - a linha `[GATEWAY] Atual: X -> Novo: Y`, e se `Y` é mesmo o gateway correto
     da sua rede;
   - avisos de DHCP.
2. **Atalhos reais, sem gateway**:

   ```powershell
   powershell -ExecutionPolicy Bypass -File C:\Temp\migrador_ssjfarm_windows.ps1 -Modo VIRTUAL -SemGateway
   ```

   Abra o atalho e confirme que abre no Firefox, no endereço certo.
3. **Gateway real em UMA máquina com acesso físico/console** (não só remoto),
   como Administrador. Confira no log a sequência: rede de segurança
   agendada → gateway alterado → conectividade confirmada. Depois valide:

   ```powershell
   route print -4 0.0.0.0
   ipconfig /all
   ```

   Teste acesso ao servidor virtual e à internet, e **reinicie a máquina** para
   conferir se o gateway persistiu.
4. **Teste a reversão** em uma máquina de teste: rode com `-GatewayTimeout 30`
   apontando para uma sub-rede cujo `.1` não responda a ping, e confira que,
   em ~30 s, o gateway antigo volta e o log registra `Reversao automatica executada`.
5. Só então rode nas demais, mantendo a rede de segurança padrão.
6. Teste o caminho de volta (`-Modo FISICO`) e confirme que o gateway **não** muda.

---

## 8. Logs e backups

| O quê | Onde |
|-------|------|
| Log | `%ProgramData%\MigradorSSJ\logs\migrador_<PC>_<data>.log` (se não for possível criar a pasta, usa `%TEMP%`) |
| Backup de cada atalho alterado | Mesma pasta do atalho: `<nome>.lnk.bak`, com atributo **Oculto** |
| Marcador temporário da reversão | `%TEMP%\migrador_gw_ok_<id>.flag` (removido pelo processo de reversão) |

O backup guarda apenas a versão **imediatamente anterior à última alteração**:
migrar o mesmo atalho outra vez sobrescreve o `.bak`.

Para ver os backups ocultos:

```cmd
dir /a:h "%USERPROFILE%\Desktop\*.bak"
```

---

## 9. Como desfazer (rollback)

**Atalho:**

```powershell
$d = "$env:USERPROFILE\Desktop"
attrib -h "$d\MinhaFarmacia.lnk.bak"
Remove-Item "$d\MinhaFarmacia.lnk" -Force
Rename-Item "$d\MinhaFarmacia.lnk.bak" "MinhaFarmacia.lnk"
```

**Gateway** (use o valor antigo registrado no log):

- Pela interface: `ncpa.cpl` → adaptador → Propriedades → IPv4 → Propriedades →
  Gateway padrão.
- Ou por PowerShell (Administrador), ajustando índice e gateway:

  ```powershell
  $cfg = Get-WmiObject Win32_NetworkAdapterConfiguration -Filter "InterfaceIndex=12"
  $cfg.SetGateways([string[]]@("10.5.125.254"), [uint16[]]@(1))
  ```

  (O índice da interface aparece no log: `[GATEWAY] Atual: … (interface 12)`.
  A métrica `1` do exemplo é ilustrativa e fixa a métrica do gateway; a
  interface gráfica mantém a métrica automática, por isso é a forma mais
  fiel de restaurar.)

---

## 10. Execução em massa (PsExec)

Sempre em duas etapas, começando por `-DryRun`:

```powershell
$hosts = "PC01","PC02","PC03"

foreach ($h in $hosts) {
    Copy-Item .\migrador_ssjfarm_windows.ps1 "\\$h\C$\Temp\migrador_ssjfarm_windows.ps1" -Force

    # Etapa 1 - atalhos do usuário (como o usuário da farmácia), sem gateway
    psexec \\$h -accepteula -u DOMINIO\usuario -p SENHA `
        powershell.exe -NoProfile -ExecutionPolicy Bypass `
        -File C:\Temp\migrador_ssjfarm_windows.ps1 -Modo VIRTUAL -SemGateway
    "$h etapa 1 -> código $LASTEXITCODE"
}
```

Depois de validar os logs, a etapa do gateway (uma máquina por vez no início):

```powershell
psexec \\$h -accepteula -s `
    powershell.exe -NoProfile -ExecutionPolicy Bypass `
    -File C:\Temp\migrador_ssjfarm_windows.ps1 -Modo VIRTUAL
"$h etapa 2 -> código $LASTEXITCODE"
```

O PsExec devolve o código de saída do script, então dá para montar um resumo
de sucesso/falha por máquina. Antivírus/EDR costumam bloquear o PsExec; pode
ser necessário criar uma exceção.

---

## 11. Códigos de saída

| Código | Significado |
|:------:|-------------|
| `0` | Concluído sem erros |
| `1` | Concluído, mas com erro em algum item — **inclui falha na troca de gateway** (ver log) |
| `2` | Erro fatal (não foi possível inicializar o `WScript.Shell`) |

Uma falha no gateway **não** impede a migração dos atalhos (feita antes).

---

## 12. Solução de problemas

| Sintoma | Causa provável / ação |
|---------|-----------------------|
| `... não é reconhecido como um nome de cmdlet` / `--modo` | Faltou o comando completo: `powershell -ExecutionPolicy Bypass -File caminho\script.ps1 -Modo ...` |
| `a execução de scripts foi desabilitada neste sistema` | Faltou `-ExecutionPolicy Bypass` |
| `Parâmetro ... Modo ... obrigatório` | `-Modo` é obrigatório (`VIRTUAL` ou `FISICO`) |
| `Firefox não encontrado em ...` | Firefox em outro caminho ou não instalado; ajuste `$FirefoxPath` no script |
| Nenhum atalho encontrado após rodar como `SYSTEM` | `%USERPROFILE%` é o do SYSTEM; veja a seção 6 |
| Erro ao salvar atalho da área de trabalho pública | Falta permissão de administrador (seção 6) |
| `[GATEWAY] ... requer PowerShell como Administrador` | Abra o PowerShell como Administrador ou rode via `psexec -s` |
| `[GATEWAY] Não há rota padrão configurada` | A máquina não tem gateway atual para basear o cálculo |
| `[GATEWAY] ... não vem da configuração do adaptador (VPN ou rota manual?)` | A rota padrão não pertence ao adaptador físico; troque manualmente |
| `[GATEWAY] ... não está na sub-rede do adaptador` | A máscara da máquina não inclui o `.1` calculado (ex.: máscara diferente de `/24`) |
| `[GATEWAY] ... é o próprio IP desta máquina` | A máquina é o `.1` da sub-rede; não há o que trocar |
| `[GATEWAY] A troca não foi aplicada (código de retorno N)` | Erro do WMI: por exemplo `71` (gateway inválido), `84` (IP não habilitado no adaptador), `91` (acesso negado) |
| `Não confirmei conectividade com o novo gateway` | O `.1` não responde a ping ou não existe; a reversão ocorre em até `-GatewayTimeout` s |
| Gateway voltou ao valor antigo após ~90 s | A reversão automática disparou (procure `Reversao automatica executada` no log); investigue o `.1` antes de repetir |
| Gateway novo sumiu depois de um tempo | Adaptador com DHCP sobrescreveu o valor; ajuste no servidor DHCP |

---

## 13. Checklist antes da produção

- [ ] `-DryRun` executado em máquinas representativas; atalhos listados conferem.
- [ ] Gateway calculado (`Atual -> Novo`) conferido para cada sub-rede da frota.
- [ ] Sei se cada máquina usa **IP fixo ou DHCP**.
- [ ] Gateway `.1` testado com **acesso físico/console** em uma máquina, inclusive
      após reiniciar.
- [ ] Reversão automática testada (seção 7, passo 4).
- [ ] Caminho de volta (`-Modo FISICO`) testado, sem alteração de gateway.
- [ ] Logs de todas as máquinas coletados e guardados (contêm o gateway antigo).
