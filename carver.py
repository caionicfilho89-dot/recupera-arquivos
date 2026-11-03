r"""Recuperação por "carving": varre os bytes crus de um disco/imagem e extrai arquivos pelas
assinaturas (cabeçalho/rodapé) conhecidas. Sem interface, para dar para testar e reusar.

Funciona bem para arquivos contíguos (o caso típico de foto em cartão SD/pendrive). Não recupera o
nome original (isso é a parte "NTFS/MFT", para uma próxima versão) e arquivos muito fragmentados
podem sair incompletos.

Modos de entrada:
- arquivo de imagem (.img/.dd/qualquer arquivo): lê direto;
- disco/volume no Windows: passe "E:" (vira \\.\E:); precisa rodar como administrador.
"""
import os

MB = 1024 * 1024
BLOCK = 4 * MB   # múltiplo de 512: funciona para leitura crua de volume

# header = assinatura inicial; o fim é achado por rodapé ou por tamanho declarado (ver _find_end).
SPECS = {
    "jpg": {"header": b"\xff\xd8\xff", "max": 50 * MB, "label": "Fotos JPEG"},
    "png": {"header": b"\x89PNG\r\n\x1a\n", "max": 80 * MB, "label": "Imagens PNG"},
    "gif": {"header": b"GIF8", "max": 30 * MB, "label": "GIF"},
    "pdf": {"header": b"%PDF-", "max": 200 * MB, "label": "PDF"},
    "zip": {"header": b"PK\x03\x04", "max": 400 * MB, "label": "ZIP / DOCX / XLSX / PPTX"},
}
_MAXHEAD = max(len(s["header"]) for s in SPECS.values())


class Source:
    r"""Leitura sequencial de um arquivo de imagem ou de um volume cru (\\.\E:)."""

    def __init__(self, path):
        if len(path) == 2 and path[1] == ":":
            path = "\\\\.\\" + path
        self.device = path.startswith("\\\\.\\")
        if self.device:
            self.fd = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0))
            self.f = None
            try:
                self.size = os.lseek(self.fd, 0, os.SEEK_END)
                os.lseek(self.fd, 0, os.SEEK_SET)
            except OSError:
                self.size = 0
        else:
            self.f = open(path, "rb")
            self.fd = None
            self.size = os.path.getsize(path)

    def read(self, n):
        return os.read(self.fd, n) if self.device else self.f.read(n)

    def close(self):
        try:
            if self.device:
                os.close(self.fd)
            else:
                self.f.close()
        except OSError:
            pass


def _earliest_header(data, specs):
    """Menor posição (índice, tipo) de qualquer cabeçalho em `data`, ou (None, None)."""
    best_i, best_k = None, None
    for k, s in specs.items():
        i = data.find(s["header"])
        if i >= 0 and (best_i is None or i < best_i):
            best_i, best_k = i, k
    return best_i, best_k


_NEED_MORE = -1


def _find_end(kind, data, eof):
    """Comprimento do arquivo dentro de `data` (a partir do cabeçalho em 0), ou _NEED_MORE."""
    if kind == "jpg":
        i = data.find(b"\xff\xd9", 2)
        return i + 2 if i >= 0 else _NEED_MORE
    if kind == "png":
        f = b"IEND\xaeB`\x82"
        i = data.find(f, 8)
        return i + len(f) if i >= 0 else _NEED_MORE
    if kind == "gif":
        i = data.find(b"\x00\x3b", 6)
        return i + 2 if i >= 0 else _NEED_MORE
    if kind == "pdf":
        i = data.find(b"%%EOF", 5)
        if i < 0:
            return _NEED_MORE
        end = i + 5
        while end < len(data) and data[end] in (13, 10) and end - (i + 5) < 2:
            end += 1
        return end
    if kind == "zip":
        i = data.find(b"PK\x05\x06", 4)
        if i < 0:
            return _NEED_MORE
        if len(data) < i + 22:
            return _NEED_MORE if not eof else len(data)
        comment = int.from_bytes(data[i + 20:i + 22], "little")
        end = i + 22 + comment
        if len(data) < end:
            return _NEED_MORE if not eof else len(data)
        return end
    return _NEED_MORE


def carve(source_path, out_dir, types=None, progress=None, should_stop=None):
    """Varre `source_path` e extrai os arquivos achados para `out_dir`.

    types: lista de chaves de SPECS (padrão: todas). progress(lidos, total). should_stop()->True aborta.
    Devolve lista de dicts {path, kind, size, offset}.
    """
    specs = {k: SPECS[k] for k in (types or SPECS) if k in SPECS}
    if not specs:
        raise ValueError("Escolha pelo menos um tipo de arquivo.")
    os.makedirs(out_dir, exist_ok=True)
    src = Source(source_path)
    recovered = []
    n = 0
    scanned = 0
    data = b""
    state = "search"
    kind = None
    base_offset = 0   # offset no disco onde `data` começa (para informar onde o arquivo estava)

    def emit(buf, k, disk_off):
        nonlocal n
        n += 1
        ext = "zip" if k == "zip" else k
        path = os.path.join(out_dir, f"recuperado_{n:05d}.{ext}")
        with open(path, "wb") as f:
            f.write(buf)
        recovered.append({"path": path, "kind": k, "size": len(buf), "offset": disk_off})

    try:
        eof = False
        while not eof:
            if should_stop and should_stop():
                break
            block = b""
            want = BLOCK
            while len(block) < want:
                chunk = src.read(want - len(block))
                if not chunk:
                    break
                block += chunk
            if not block:
                eof = True
            else:
                data += block
                scanned += len(block)
                if progress:
                    progress(scanned, src.size)
            # processa o máximo possível com o que já temos
            while True:
                if state == "search":
                    i, k = _earliest_header(data, specs)
                    if i is None:
                        keep = 0 if eof else _MAXHEAD - 1
                        base_offset += len(data) - keep
                        data = data[len(data) - keep:] if keep else b""
                        break
                    base_offset += i
                    data = data[i:]
                    state, kind = "carve", k
                else:
                    end = _find_end(kind, data, eof)
                    if end == _NEED_MORE:
                        if not eof and len(data) <= specs[kind]["max"]:
                            break   # espera mais bytes
                        # sem rodapé (grande demais ou acabou o disco): descarta e procura adiante
                        base_offset += 1
                        data = data[1:]
                        state = "search"
                        continue
                    emit(data[:end], kind, base_offset)
                    base_offset += end
                    data = data[end:]
                    state = "search"
    finally:
        src.close()
    if progress:
        progress(src.size or scanned, src.size or scanned)
    return recovered
