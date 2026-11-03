# Recupera Arquivos ⏮

Recupera arquivos **apagados** de um pendrive, cartão SD ou imagem de disco — fotos, PDFs e
documentos que ainda estão gravados no espaço "livre". Tudo no seu PC, offline.

Funciona por **carving**: varre os bytes crus do disco procurando as assinaturas dos arquivos
(cabeçalho e rodapé) e extrai o que acha. Tipos suportados: **JPEG, PNG, GIF, PDF e ZIP/DOCX/XLSX/PPTX**.

Feito em Python + PyQt6. Roda no Windows.

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

1. Em **Onde procurar**, escolha um disco (`E:` etc.) ou uma imagem de disco (`.img/.dd/.iso`).
2. Em **Salvar os recuperados em…**, escolha uma pasta **em outro disco**.
3. Marque os tipos e clique em **Recuperar**. Dá pra **Parar** quando quiser.

Os arquivos saem como `recuperado_00001.jpg`, etc. (o carving não recupera o nome original — isso
depende de ler a tabela do sistema de arquivos, planejado para uma próxima versão).

## Limites (seja realista)

- Recupera bem arquivos **contíguos** (o caso comum em cartão/pendrive). Arquivos muito
  **fragmentados** podem sair incompletos.
- **Não recupera o nome** nem a data original.
- Se os dados já foram **sobregravados**, não há o que recuperar — nenhum programa faz milagre.
- Para casos difíceis, vale conhecer o [PhotoRec/TestDisk](https://www.cgsecurity.org/) (gratuito).

## Como funciona

Leitura sequencial em blocos de 4 MB (de um arquivo ou de `\\.\E:`), uma máquina de estados que
acha o cabeçalho, coleta até o rodapé (ou o tamanho declarado, no caso do ZIP) e grava o arquivo.
Sem seek nem escrita no disco de origem.

## Licença

MIT.
