"""Convert the frozen P6.8 ready/beep sources into flash PCM, never TTS."""
import hashlib
import pathlib
import subprocess
import sys

ASSETS = {
    "ready_01": ("17727761db1100511d7728038d5212ec896e1aa141e666283a1c474d12e92d80", 47402),
    "ready_02": ("f4e90f5588f87d23b49adf76fca2907422bf92e41da77ab76b8c352326a88c67", 47784),
    "ready_03": ("22e7ec8ce43ee406de94f95b46a988ac7a44cf0c838d93b05cfed80a166634a7", 53254),
    "followup_01": ("67b5d7ccced82fa74b52dc0e0fe56388dbc6386022f662f54f855b66674cb978", 30720),
    "local_success_01": ("0a4b1d793bb085b3425a1f6d4194925acc7a9035c38277a2e4e7c55e1ece3e50", 53952),
    "local_failure_01": ("6dd0c6c3a215dcca78855da52bd8bd266bf02973bee9627da287c8b49957dc83", 83788),
}
REQUIRED_ASSETS = {"local_success_01", "local_failure_01"}


def generate(source: pathlib.Path, target: pathlib.Path):
    target.mkdir(parents=True, exist_ok=True)
    print(subprocess.check_output(["ffmpeg", "-version"], text=True).splitlines()[0])
    assembly = ['    .section .rodata.embedded,"a",@progbits']
    for name, (sha, size) in ASSETS.items():
        src, dst = source / (name + ".mp3"), target / (name + ".pcm")
        if src.exists():
            if hashlib.sha256(src.read_bytes()).hexdigest() != sha:
                raise ValueError(f"{src.name}: source differs from the frozen contract")
            pcm = subprocess.check_output([
                "ffmpeg", "-nostdin", "-v", "error", "-i", str(src),
                "-f", "s16le", "-ac", "1", "-ar", "32000", "pipe:1",
            ])
            if len(pcm) != size:
                raise ValueError(f"{src.name}: unexpected PCM size {len(pcm)}")
        else:
            if name in REQUIRED_ASSETS:
                raise FileNotFoundError(f"required prompt asset missing: {src.name}")
            print(f"{src.name}: missing, embed empty asset (skip)")
            pcm = b""
        if not dst.exists() or dst.read_bytes() != pcm:
            dst.write_bytes(pcm)
        print(f"{dst.name}: {len(pcm)} B sha256={hashlib.sha256(pcm).hexdigest()}")
        # Explicit alignment permits native s16 reads from mapped flash.
        assembly.extend(["    .balign 4", f"    .global {name}_start",
                         f"{name}_start:", f'    .incbin "{dst.resolve()}"',
                         f"    .global {name}_end", f"{name}_end:"])
    asm = target / "p68_prompt_assets.S"
    content = "\n".join(assembly) + "\n"
    if not asm.exists() or asm.read_text() != content:
        asm.write_text(content)


if __name__ == "__main__":
    generate(pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]))
