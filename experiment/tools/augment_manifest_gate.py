#!/usr/bin/env python3
"""Add quantized acoustic gate parameters to the public manifest."""

import json
import sys
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path


EXPERIMENT_DIR = Path(__file__).resolve().parent.parent
MANIFEST_PATH = EXPERIMENT_DIR / "audio1char_manifest.json"
ANSWER_KEY_PATH = EXPERIMENT_DIR / "answer_key_merged.json"
ONSETS_PATH = EXPERIMENT_DIR / "audio1char_onsets.json"


def load_json(path):
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def round_half_up(value, quantum):
    return Decimal(str(value)).quantize(Decimal(quantum), rounding=ROUND_HALF_UP)


def main():
    manifest = load_json(MANIFEST_PATH)
    answer_key = load_json(ANSWER_KEY_PATH)
    onsets = load_json(ONSETS_PATH)

    id_to_kana = {
        key.split("|")[1]: value["char"]
        for key, value in answer_key.items()
        if key.startswith("audio1char|") and value.get("pool") == "cand108"
    }

    errors = []
    gate_onsets = []
    gate_gains = []
    stimuli = manifest.get("stimuli", [])
    for stim in stimuli:
        stim_id = stim.get("id")
        kana = id_to_kana.get(stim_id)
        if kana is None:
            errors.append(f"id={stim_id!r}: cand108 のかな対応がありません")
            continue
        onset = onsets.get(kana)
        if onset is None:
            errors.append(f"id={stim_id!r}, かな={kana!r}: onsetエントリがありません")
            continue
        if "acoustic_onset_ms" not in onset or "gain" not in onset:
            errors.append(f"id={stim_id!r}, かな={kana!r}: acoustic_onset_ms または gain がありません")
            continue

        gate_onset_ms = int(round_half_up(onset["acoustic_onset_ms"] / 10, "1") * 10)
        gate_gain = float(round_half_up(onset["gain"], "0.1"))
        stim["gate_onset_ms"] = gate_onset_ms
        stim["gate_gain"] = gate_gain
        gate_onsets.append(gate_onset_ms)
        gate_gains.append(gate_gain)

    if errors:
        print("マニフェストの全刺激を解決できませんでした:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    with MANIFEST_PATH.open("w", encoding="utf-8") as file:
        json.dump(manifest, file, ensure_ascii=False, indent=1)
        file.write("\n")

    print(
        f"gate_onset_ms: min={min(gate_onsets)} max={max(gate_onsets)} count={len(gate_onsets)}",
        file=sys.stderr,
    )
    print(
        f"gate_gain: min={min(gate_gains):.1f} max={max(gate_gains):.1f} count={len(gate_gains)}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
