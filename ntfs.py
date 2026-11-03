r"""Recuperação em NTFS lendo a MFT: acha os registros de arquivos apagados e recupera COM o nome.

Diferente do carving (carver.py), aqui a gente lê a tabela de arquivos do NTFS (a MFT). Cada arquivo
é um "registro FILE"; um bit no cabeçalho diz se está em uso ou apagado. Pegamos os apagados, lemos
o nome ($FILE_NAME) e o conteúdo ($DATA) — que pode estar dentro do próprio registro (resident, para
arquivos pequenos) ou espalhado em clusters do disco (non-resident, pelos "data runs").

Entrada: imagem de disco (arquivo) ou volume cru no Windows ("E:" -> \\.\E:; precisa administrador).
Só funciona em partição NTFS (pen drive/cartão costumam ser FAT/exFAT: aí use o modo carving).
"""
import os

MB = 1024 * 1024
_INVALID = '<>:"/\\|?*'


class RReader:
    r"""Leitura por offset de um arquivo de imagem ou de um volume cru (\\.\E:), com alinhamento de setor."""

    def __init__(self, path):
        if len(path) == 2 and path[1] == ":":
            path = "\\\\.\\" + path
        self.device = path.startswith("\\\\.\\")
        self.bps = 512
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

    def pread(self, off, length):
        if length <= 0:
            return b""
        if not self.device:
            self.f.seek(off)
            return self.f.read(length)
        a = off - (off % self.bps)
        end = off + length
        end_a = end + (-end % self.bps)
        os.lseek(self.fd, a, os.SEEK_SET)
        want = end_a - a
        raw = b""
        while len(raw) < want:
            c = os.read(self.fd, want - len(raw))
            if not c:
                break
            raw += c
        return raw[off - a: off - a + length]

    def close(self):
        try:
            os.close(self.fd) if self.device else self.f.close()
        except OSError:
            pass


def parse_boot(b):
    if b[3:7] != b"NTFS":
        raise ValueError("Isso não parece uma partição NTFS. Para pen drive/cartão (FAT/exFAT), use o modo carving.")
    bps = int.from_bytes(b[0x0B:0x0D], "little")
    spc = b[0x0D]
    mft_lcn = int.from_bytes(b[0x30:0x38], "little")
    raw = int.from_bytes(b[0x40:0x41], "little", signed=True)
    rec_size = raw * spc * bps if raw >= 0 else (1 << (-raw))
    return bps, spc, bps * spc, mft_lcn, rec_size


def apply_fixup(rec, bps):
    """Aplica a Update Sequence Array: devolve os bytes do registro com os fins de setor corrigidos."""
    rec = bytearray(rec)
    usa_off = int.from_bytes(rec[4:6], "little")
    usa_cnt = int.from_bytes(rec[6:8], "little")
    for i in range(1, usa_cnt):
        pos = i * bps - 2
        src = usa_off + i * 2
        if pos + 2 <= len(rec) and src + 2 <= len(rec):
            rec[pos:pos + 2] = rec[src:src + 2]
    return bytes(rec)


def parse_runlist(data):
    """Lista de (lcn, n_clusters); lcn=None indica trecho esparso (buraco)."""
    runs = []
    i = 0
    lcn = 0
    while i < len(data):
        head = data[i]
        i += 1
        if head == 0:
            break
        lsz, osz = head & 0x0F, head >> 4
        length = int.from_bytes(data[i:i + lsz], "little")
        i += lsz
        if osz:
            delta = int.from_bytes(data[i:i + osz], "little", signed=True)
            i += osz
            lcn += delta
            runs.append((lcn, length))
        else:
            runs.append((None, length))
    return runs


def parse_record(rec, rec_size):
    """Lê um registro FILE já com fixup aplicado. Devolve dict ou None se não for um FILE válido."""
    if rec[:4] != b"FILE":
        return None
    flags = int.from_bytes(rec[0x16:0x18], "little")
    first = int.from_bytes(rec[0x14:0x16], "little")
    name, name_ns, data = None, -1, None
    pos = first
    while pos + 8 <= rec_size:
        atype = int.from_bytes(rec[pos:pos + 4], "little")
        if atype == 0xFFFFFFFF:
            break
        alen = int.from_bytes(rec[pos + 4:pos + 8], "little")
        if alen < 8 or pos + alen > rec_size:
            break
        non_res = rec[pos + 8]
        if atype == 0x30 and non_res == 0:   # $FILE_NAME (sempre resident)
            coff = int.from_bytes(rec[pos + 0x14:pos + 0x16], "little")
            c = pos + coff
            nlen = rec[c + 0x40]
            ns = rec[c + 0x41]
            nm = rec[c + 0x42:c + 0x42 + nlen * 2].decode("utf-16-le", "ignore")
            if ns != 2 and ns > name_ns:   # prefere nome longo (Win32/POSIX), não o 8.3 (DOS=2)
                name, name_ns = nm, ns
        elif atype == 0x80 and rec[pos + 9] == 0 and data is None:   # $DATA sem nome
            if non_res == 0:
                clen = int.from_bytes(rec[pos + 0x10:pos + 0x14], "little")
                coff = int.from_bytes(rec[pos + 0x14:pos + 0x16], "little")
                data = ("res", bytes(rec[pos + coff:pos + coff + clen]))
            else:
                roff = int.from_bytes(rec[pos + 0x20:pos + 0x22], "little")
                real = int.from_bytes(rec[pos + 0x30:pos + 0x38], "little")
                data = ("nonres", parse_runlist(rec[pos + roff:pos + alen]), real)
        pos += alen
    return {"deleted": not (flags & 0x01), "dir": bool(flags & 0x02), "name": name, "data": data}


def _read_data(reader, data, cluster, cap):
    kind = data[0]
    if kind == "res":
        return data[1]
    _, runs, real = data
    real = min(real, cap)
    out = bytearray()
    for lcn, length in runs:
        if len(out) >= real:
            break
        if lcn is None:
            out += b"\x00" * min(length * cluster, real - len(out))
        else:
            out += reader.pread(lcn * cluster, length * cluster)
    return bytes(out[:real])


def _save(out_dir, name, content):
    safe = "".join("_" if ch in _INVALID or ord(ch) < 32 else ch for ch in name).strip() or "sem_nome"
    path = os.path.join(out_dir, safe)
    base, ext = os.path.splitext(path)
    k = 1
    while os.path.exists(path):
        path = f"{base}_{k}{ext}"
        k += 1
    with open(path, "wb") as f:
        f.write(content)
    return path


def scan_ntfs(source_path, out_dir, progress=None, should_stop=None, cap=512 * MB):
    """Percorre a MFT e recupera os arquivos apagados (com nome) para out_dir.
    Devolve lista de dicts {name, path, size, resident}."""
    os.makedirs(out_dir, exist_ok=True)
    reader = RReader(source_path)
    try:
        bps, spc, cluster, mft_lcn, rec_size = parse_boot(reader.pread(0, 512))
        reader.bps = bps
        rec0 = apply_fixup(reader.pread(mft_lcn * cluster, rec_size), bps)
        info0 = parse_record(rec0, rec_size)
        if not info0 or not info0["data"] or info0["data"][0] != "nonres":
            raise ValueError("Não consegui ler a MFT (o $MFT está resident? volume incomum).")
        mft_runs = info0["data"][1]
        total_est = sum(l for lcn, l in mft_runs if lcn is not None) * cluster // rec_size or 1
        recovered = []
        idx = 0
        for lcn, length in mft_runs:
            if lcn is None:
                continue
            run_bytes = length * cluster
            read = 0
            while read + rec_size <= run_bytes:
                if should_stop and should_stop():
                    return recovered
                chunk = reader.pread(lcn * cluster + read, rec_size)
                read += rec_size
                idx += 1
                if progress and idx % 200 == 0:
                    progress(idx, total_est)
                if chunk[:4] != b"FILE":
                    continue
                try:
                    info = parse_record(apply_fixup(chunk, bps), rec_size)
                except Exception:  # noqa: BLE001
                    continue
                if not info or not info["deleted"] or info["dir"]:
                    continue
                name, data = info["name"], info["data"]
                if not name or name.startswith("$") or not data:
                    continue
                content = _read_data(reader, data, cluster, cap)
                if not content:
                    continue
                recovered.append({"name": name, "path": _save(out_dir, name, content),
                                  "size": len(content), "resident": data[0] == "res"})
        if progress:
            progress(total_est, total_est)
        return recovered
    finally:
        reader.close()
