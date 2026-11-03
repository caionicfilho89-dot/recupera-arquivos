# Recupera Arquivos ⏮

Recupera arquivos **apagados** de um pendrive, cartão SD ou imagem de disco — fotos, PDFs e
documentos que ainda estão gravados no espaço "livre". Tudo no seu PC, offline.

Tem dois modos:

- **Por conteúdo (carving)** — varre os bytes crus do disco procurando as assinaturas dos arquivos
  (cabeçalho e rodapé). Funciona em **qualquer disco** (pen drive e cartão costumam ser FAT/exFAT).
  Tipos: **JPEG, PNG, GIF, PDF e ZIP/DOCX/XLSX/PPTX**. Não recupera o nome original.
- **NTFS (recupera com o nome)** — lê a MFT (a tabela de arquivos do NTFS), acha os registros
  apagados e recupera **com o nome e a extensão originais**, de qualquer tipo. Só em **partição
  NTFS** (o HD do Windows, normalmente).

Feito em Python + PyQt6 (o modo NTFS é só biblioteca padrão). Roda no Windows.

## ⚠️ Antes de usar (importante)

- **Pare de usar o disco apagado na hora.** Cada coisa nova gravada pode escrever por cima do que
  você quer recuperar. Quanto antes recuperar, melhor.
- **Nunca salve os recuperados no mesmo disco** de onde está recuperando (o app te obriga a escolher
  outro disco — justamente por isso).
- Para ler um pendrive/cartão/HD direto (ex.: `E:`), rode **como administrador** (acesso bruto ao
  disco). Imagens de disco (arquivo) não precisam de admin.

## Instalar e usar

```sh
pip install -r requirements.txt
python recupera.pyw
```

1. Escolha o **Modo** (carving para cartão/pen drive; NTFS para o HD do Windows).
2. Em **Onde procurar**, escolha um disco (`E:` etc.) ou uma imagem de disco (`.img/.dd/.iso`).
3. Em **Salvar os recuperados em…**, escolha uma pasta **em outro disco**.
4. (No carving) marque os tipos, e clique em **Recuperar**. Dá pra **Parar** quando quiser.

No carving os arquivos saem como `recuperado_00001.jpg`; no modo NTFS, com o nome original.

## Limites (seja realista)

- O carving recupera bem arquivos **contíguos** (o caso comum em cartão/pen drive). Arquivos muito
  **fragmentados** podem sair incompletos, e ele não recupera o nome.
- O modo NTFS recupera o nome, mas se os clusters do arquivo já foram **reusados**, o conteúdo pode
  vir sobregravado.
- Se os dados já foram **sobregravados**, não há o que recuperar — nenhum programa faz milagre.
- Para casos difíceis, vale conhecer o [PhotoRec/TestDisk](https://www.cgsecurity.org/) (gratuito).

## Como funciona

**Carving** (`carver.py`): leitura sequencial em blocos de 4 MB (de um arquivo ou de `\\.\E:`), uma
máquina de estados que acha o cabeçalho, coleta até o rodapé (ou o tamanho declarado, no ZIP) e
grava o arquivo. Sem seek nem escrita no disco de origem.

**NTFS** (`ntfs.py`): lê o boot sector (tamanho de setor/cluster, onde fica a MFT), percorre os
registros `FILE` da MFT, aplica o *fixup* (Update Sequence Array), pega os marcados como apagados e
lê o `$FILE_NAME` (nome) e o `$DATA` — resident (dentro do registro) ou non-resident (seguindo os
*data runs* pelos clusters do disco). Nada é escrito no disco de origem.

## Licença

MIT.
