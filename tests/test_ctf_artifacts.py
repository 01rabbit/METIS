import base64
import gzip
import io
import sqlite3
import struct
import wave
import zipfile

import pytest
from PIL import Image
from PIL.PngImagePlugin import PngInfo

from metis.core.codex_session import CodexSession
from metis.core.contracts import ChallengeManifest
from metis.core.ctf_artifacts import ARTIFACT_ERRORS, inspect_bytes


def tiny_elf():
    ident = b"\x7fELF" + bytes([2, 1, 1, 0]) + b"\x00" * 8
    header = ident + struct.pack("<HHIQQQIHHHHHH", 2, 62, 1, 0x400000, 0, 128, 0,
                                 64, 56, 0, 64, 3, 1)
    names = b"\x00.shstrtab\x00.text\x00"
    contents = (header + b"\x90\xc3" + names).ljust(128, b"\x00")
    null = b"\x00" * 64
    table = struct.pack("<IIQQQQIIQQ", 1, 3, 0, 0, 66, len(names), 0, 0, 1, 0)
    text = struct.pack("<IIQQQQIIQQ", 11, 1, 6, 0x400000, 64, 2, 0, 0, 1, 0)
    return contents + null + table + text


def test_file_overview_strings_and_hex_are_read_only():
    content = b"\x00\x01prefix CTF{static-data}\x00\xff"
    overview = inspect_bytes(content, "overview")
    assert overview["size"] == len(content)
    assert overview["strings"][0]["offset"] == 2
    assert "CTF{static-data}" in overview["strings"][0]["text"]
    assert inspect_bytes(content, "hex", {"offset": 2, "length": 6})["utf8"] == "prefix"


def test_elf_and_disassembly_never_execute_program():
    result = inspect_bytes(tiny_elf(), "elf")
    assert result["bits"] == 64 and result["entry"] == "0x400000"
    assert any(section["name"] == ".text" for section in result["sections"])
    assert result["executed"] is False
    assembly = inspect_bytes(b"\x90\x90\xc3", "disassemble")
    assert [item["mnemonic"] for item in assembly["instructions"]] == ["nop", "nop", "ret"]
    assert assembly["executed"] is False


def test_zip_read_without_extraction_and_bomb_rejection():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("note.txt", "CTF{archive}")
        archive.writestr("../escape", "no")
        archive.writestr("bomb", "A" * 100_000)
    data = stream.getvalue()
    assert len(inspect_bytes(data, "zip_list")["members"]) == 3
    assert inspect_bytes(data, "zip_read", {"member": "note.txt"})["utf8"] == "CTF{archive}"
    for name in ("../escape", "bomb"):
        with pytest.raises(ValueError):
            inspect_bytes(data, "zip_read", {"member": name, "max_bytes": 200_000})


def test_bounded_gzip_content():
    data = gzip.compress(b"CTF{compressed}")
    assert inspect_bytes(data, "gzip")["utf8"] == "CTF{compressed}"
    with pytest.raises(ValueError):
        inspect_bytes(data, "gzip", {"max_bytes": 3})
    with pytest.raises(ValueError):
        inspect_bytes(data[:-4], "gzip")


def test_image_metadata_and_lsb():
    answer = b"flag"
    bits = [byte >> shift & 1 for byte in answer for shift in range(7, -1, -1)]
    bits += [0] * (48 - len(bits))
    image = Image.new("RGB", (16, 1))
    image.putdata([tuple(128 | bits[index + channel] for channel in range(3))
                   for index in range(0, 48, 3)])
    stream = io.BytesIO()
    info = PngInfo()
    info.add_text("Comment", "CTF{metadata}")
    image.save(stream, format="PNG", pnginfo=info)
    data = stream.getvalue()
    result = inspect_bytes(data, "image")
    assert result["info"]["Comment"] == "CTF{metadata}"
    decoded = inspect_bytes(data, "image_lsb", {"max_bytes": 4})
    assert base64.b64decode(decoded["base64"]) == answer


def test_classic_pcap_udp_payload():
    payload = b"CTF{packet}"
    udp = struct.pack("!HHHH", 1234, 9999, 8 + len(payload), 0) + payload
    ip = struct.pack("!BBHHHBBH4s4s", 0x45, 0, 20 + len(udp), 0, 0, 64, 17, 0,
                     bytes([192, 0, 2, 1]), bytes([192, 0, 2, 2])) + udp
    packet = b"\x00" * 12 + b"\x08\x00" + ip
    global_header = struct.pack("<IHHIIII", 0xa1b2c3d4, 2, 4, 0, 0, 65535, 1)
    data = global_header + struct.pack("<IIII", 1, 0, len(packet), len(packet)) + packet
    result = inspect_bytes(data, "pcap")
    assert result["packets"][0]["destination_port"] == 9999
    assert result["packets"][0]["payload_prefix"]["utf8"] == payload.decode()


def test_pcapng_enhanced_packets():
    def block(kind, content):
        length = 12 + len(content)
        return struct.pack("<II", kind, length) + content + struct.pack("<I", length)

    header = block(0x0a0d0d0a, struct.pack("<IHHq", 0x1a2b3c4d, 1, 0, -1))
    interface = block(1, struct.pack("<HHI", 1, 0, 65535))
    packet = b"\x00" * 14
    payload = struct.pack("<IIIII", 0, 0, 1_000_000, len(packet), len(packet)) + packet + b"\x00" * 2
    result = inspect_bytes(header + interface + block(6, payload), "pcap")
    assert result["format"] == "PCAPNG"
    assert len(result["packets"]) == 1
    assert result["packets"][0]["seconds"] == 1


def test_intake_derive_and_context_reopen(tmp_path):
    source = tmp_path / "challenge.zip"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("nested.txt", "CTF{derived-data}")
    database = tmp_path / "session.sqlite"
    session = CodexSession(database)
    context = session.intake(title="Forensics archive", description="Inspect this archive",
                             paths=[source], categories=["forensics"])
    run_id = context["run_id"]
    artifact = context["challenge"]["artifacts"][0]
    source.unlink()  # Intake retains its own snapshot.
    derived = session.derive(run_id, artifact, "zip_read", {"member": "nested.txt"})
    assert derived["ok"]
    restored = CodexSession(database)
    result = restored.artifact(run_id, derived["artifact"], "text")
    assert result["result"]["text"] == "CTF{derived-data}"
    assert derived["artifact"] in restored.context(run_id)["challenge"]["artifacts"]


def test_pe_static_header_inspection():
    dos = bytearray(128)
    dos[:2] = b"MZ"
    struct.pack_into("<I", dos, 60, 128)
    coff = b"PE\x00\x00" + struct.pack("<HHIIIHH", 0x8664, 1, 0, 0, 0, 240, 0x22)
    optional = bytearray(240)
    struct.pack_into("<H", optional, 0, 0x20b)
    struct.pack_into("<I", optional, 16, 0x1000)
    struct.pack_into("<Q", optional, 24, 0x140000000)
    struct.pack_into("<H", optional, 70, 0x140)
    section = bytearray(40)
    section[:5] = b".text"
    struct.pack_into("<IIII", section, 8, 2, 0x1000, 2, 512)
    data = (bytes(dos) + coff + optional + section).ljust(512, b"\x00") + b"\x90\xc3"
    result = inspect_bytes(data, "pe")
    assert result["bits"] == 64 and result["entry_rva"] == "0x1000"
    assert result["mitigation_indicators"]["nx"] is True
    assert result["executed"] is False


def test_java_constant_pool_without_execution():
    text = b"CTF{java-data}"
    data = b"\xca\xfe\xba\xbe" + struct.pack(">HHH", 0, 61, 2) + b"\x01" + struct.pack(">H", len(text)) + text
    result = inspect_bytes(data, "java_class")
    assert result["utf8_constants"][0]["text"] == text.decode()
    assert result["executed"] is False


def test_wav_metadata_and_low_bits():
    message = b"CTF{pcm}"
    values = bytes(128 | ((byte >> shift) & 1) for byte in message for shift in range(7, -1, -1))
    output = io.BytesIO()
    with wave.open(output, "wb") as sound:
        sound.setnchannels(1)
        sound.setsampwidth(1)
        sound.setframerate(8000)
        sound.writeframes(values)
    data = output.getvalue()
    assert inspect_bytes(data, "wav")["sample_rate"] == 8000
    assert inspect_bytes(data, "wav_lsb", {"max_bytes": len(message)})["utf8"] == message.decode()


def test_sqlite_reads_tables_without_mutating_input_or_running_views(tmp_path):
    path = tmp_path / "evidence.sqlite"
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE "notes" (id INTEGER, note TEXT)')
        db.execute("INSERT INTO notes VALUES (1, 'CTF{sqlite-data}')")
        db.execute("CREATE VIEW hostile AS SELECT load_extension('/untrusted')")
    data = path.read_bytes()
    result = inspect_bytes(data, "sqlite")
    assert result["read_only"]
    assert any(item["name"] == "notes" for item in result["schema"])
    assert inspect_bytes(data, "sqlite", {"table": "notes"})["rows"] == [[1, "CTF{sqlite-data}"]]
    with pytest.raises(ValueError):
        inspect_bytes(data, "sqlite", {"table": "hostile"})
    assert path.read_bytes() == data


def test_scoped_artifacts_and_failed_analysis_leave_session_usable(tmp_path):
    root = tmp_path / "files"
    root.mkdir()
    (root / "data.bin").write_bytes(b"CTF{authorized-file}")
    (root / "other").write_bytes(b"not in scope")
    manifest = ChallengeManifest.model_validate({
        "challenge_id": "file", "title": "File", "description": "Analyze the supplied file",
        "artifacts": ["data.bin"], "categories": ["forensics"],
        "scope": {"authorized": True, "granted_by": "test", "challenge_id": "file"},
    })
    session = CodexSession(tmp_path / "session.sqlite")
    run_id = session.start(manifest, artifact_root=root)["run_id"]
    assert session.artifact(run_id, "data.bin", "strings")["ok"]
    with pytest.raises(ValueError, match="declared scope"):
        session.artifact(run_id, "other", "overview")
    assert not session.artifact(run_id, "data.bin", "elf")["ok"]
    assert session.context(run_id)["status"] == "planning"
    assert "CTF{authorized-file}" not in session.store.export_jsonl(run_id)
    (root / "data.bin").unlink()
    (root / "data.bin").symlink_to(root / "other")
    assert not session.artifact(run_id, "data.bin", "strings")["ok"]


@pytest.mark.parametrize("tool", ["elf", "image", "zip_list", "gzip", "pcap"])
def test_malformed_formats_rejected(tool):
    with pytest.raises(ARTIFACT_ERRORS):
        inspect_bytes(b"not a valid file", tool)
