#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import platform
import subprocess
import re
import tkinter as tk
from tkinter import messagebox, ttk, scrolledtext

class MigradorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Migrador Farmácia - ssjfarm.com.br")
        self.root.geometry("650x550")
        
        # --- CONFIGURAÇÕES PADRÃO ---
        self.DOMINIO_FISICO = "ssjfarm.com.br"
        self.IP_VIRTUAL_PADRAO = "192.168.100.123"
        self.PORTA_VIRTUAL = "8181"
        # ---------------------------

        frame = ttk.Frame(root, padding="20")
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="1. Selecione o Destino:", font=('Helvetica', 10, 'bold')).pack(pady=5, anchor=tk.W)
        self.modo_var = tk.StringVar(value="VIRTUAL")
        ttk.Radiobutton(frame, text=f"Mudar para VIRTUAL ({self.IP_VIRTUAL_PADRAO}:{self.PORTA_VIRTUAL})", 
                        variable=self.modo_var, value="VIRTUAL").pack(anchor=tk.W)
        ttk.Radiobutton(frame, text=f"Retornar para FÍSICO ({self.DOMINIO_FISICO})", 
                        variable=self.modo_var, value="FISICO").pack(anchor=tk.W)

        ttk.Label(frame, text="\n2. Confirmar IP do Servidor Virtual:", font=('Helvetica', 10, 'bold')).pack(pady=5, anchor=tk.W)
        self.ent_ip_virtual = ttk.Entry(frame, width=30)
        self.ent_ip_virtual.insert(0, self.IP_VIRTUAL_PADRAO)
        self.ent_ip_virtual.pack(pady=5, anchor=tk.W)

        self.btn_executar = ttk.Button(frame, text="ATUALIZAR ATALHOS AGORA", command=self.confirmar_execucao)
        self.btn_executar.pack(pady=15)

        ttk.Label(frame, text="Log de Atividades:", font=('Helvetica', 9, 'bold')).pack(anchor=tk.W)
        self.log_area = scrolledtext.ScrolledText(frame, height=12, width=75, font=('Consolas', 9))
        self.log_area.pack(pady=5, fill=tk.BOTH, expand=True)

    def log(self, mensagem):
        self.log_area.insert(tk.END, mensagem + "\n")
        self.log_area.see(tk.END)

    def atualizar_atalhos_windows(self, busca, troca):
        firefox = r"C:\Program Files\Mozilla Firefox\firefox.exe"
        ps_template = r'''
        $busca = [regex]::Escape("{0}"); $troca = "{1}"; $fxPath = "{2}"
        $shell = New-Object -ComObject WScript.Shell
        $locations = @("$env:USERPROFILE\Desktop", "C:\Users\Public\Desktop")
        foreach ($loc in $locations) {{
            if (Test-Path $loc) {{
                Get-ChildItem -Path $loc -Filter *.lnk | ForEach-Object {{
                    $s = $shell.CreateShortcut($_.FullName)
                    if ($s.Arguments -match $busca) {{
                        $s.TargetPath = $fxPath
                        $s.Arguments = $s.Arguments -replace $busca, $troca
                        $s.Save()
                        Write-Output $_.Name
                    }}
                }}
            }}
        }}
        '''
        script = ps_template.format(busca, troca, firefox)
        result = subprocess.run(["powershell", "-Command", script], capture_output=True, text=True)
        nomes = [n.strip() for n in result.stdout.splitlines() if n.strip()]
        for nome in nomes: self.log(f"[OK] Windows: {nome}")
        return len(nomes) > 0

    def atualizar_atalhos_linux(self, busca, troca):
        home = os.path.expanduser("~")
        
        # Lista expandida para cobrir CentOS (t minúsculo) e Ubuntu (T maiúsculo)
        locais_potenciais = [
            os.path.join(home, "Área de Trabalho"), # Ubuntu padrão
            os.path.join(home, "Área de trabalho"), # CentOS padrão
            os.path.join(home, "Desktop"),           # Inglês
            os.path.join(home, "Mesa"),              # Outras distros
            "/usr/share/applications",               # Atalhos do sistema
            os.path.join(home, ".local/share/applications") # Atalhos do usuário
        ]

        # Tenta pegar via sistema também
        try:
            cmd = subprocess.run(['xdg-user-dir', 'DESKTOP'], capture_output=True, text=True)
            if cmd.stdout.strip():
                locais_potenciais.append(cmd.stdout.strip())
        except:
            pass

        # Filtra apenas pastas que realmente existem no disco
        locais = list(set([os.path.abspath(l) for l in locais_potenciais if os.path.exists(l)]))
        
        self.log(f"[*] Escaneando: {locais}")
        encontrado = False
        
        for d in locais:
            for item in os.listdir(d):
                if item.endswith(".desktop"):
                    path = os.path.join(d, item)
                    try:
                        with open(path, 'r', encoding='utf-8', errors='ignore') as f: 
                            content = f.read()
                        
                        if busca in content:
                            new_content = content.replace(busca, troca)
                            
                            # Força o firefox e https:// se não estiver presente
                            if "Exec=" in new_content and "firefox" not in new_content.lower():
                                new_content = re.sub(r'^Exec=.*', f'Exec=firefox https://{troca}', new_content, flags=re.M)

                            with open(path, 'w', encoding='utf-8') as f: 
                                f.write(new_content)
                            self.log(f"[OK] Linux: {item} ({d})")
                            encontrado = True
                    except Exception as e: 
                        continue
        return encontrado

    def confirmar_execucao(self):
        modo = self.modo_var.get()
        ip_v = self.ent_ip_virtual.get().strip()
        host_virtual = f"{ip_v}:{self.PORTA_VIRTUAL}"
        
        if modo == "VIRTUAL":
            busca, troca = self.DOMINIO_FISICO, host_virtual
        else:
            busca, troca = host_virtual, self.DOMINIO_FISICO

        self.log(f"\n--- Migrando: {busca} -> {troca} ---")
        
        try:
            sucesso = False
            if platform.system() == "Windows":
                sucesso = self.atualizar_atalhos_windows(busca, troca)
            else:
                sucesso = self.atualizar_atalhos_linux(busca, troca)
            
            if sucesso:
                self.log("--- Concluído! ---")
                messagebox.showinfo("Sucesso", "Atalhos atualizados!")
            else:
                self.log("--- Nada encontrado. ---")
                messagebox.showwarning("Aviso", "Nenhum atalho foi alterado.")
        except Exception as e:
            self.log(f"[ERRO] {str(e)}")

if __name__ == "__main__":
    root = tk.Tk()
    app = MigradorApp(root)
    root.mainloop()