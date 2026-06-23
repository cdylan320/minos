"""Parse output VCF files for the results panel."""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any, Dict, List, Optional


def find_latest_vcf(output_dir: Path) -> Optional[Path]:
    if not output_dir.exists():
        return None
    candidates = sorted(
        output_dir.rglob("output.vcf.gz"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def summarize_vcf(vcf_path: Path, preview_limit: int = 12) -> Dict[str, Any]:
    total = 0
    snp = 0
    indel = 0
    preview: List[Dict[str, Any]] = []

    opener = gzip.open if str(vcf_path).endswith(".gz") else open
    with opener(vcf_path, "rt") as handle:
        for line in handle:
            if line.startswith("#"):
                continue
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 5:
                continue
            chrom, pos, _vid, ref, alt = parts[:5]
            qual = parts[5] if len(parts) > 5 else "."
            is_snp = len(ref) == 1 and len(alt) == 1
            total += 1
            if is_snp:
                snp += 1
            else:
                indel += 1
            if len(preview) < preview_limit:
                preview.append({
                    "chrom": chrom,
                    "pos": pos,
                    "ref": ref,
                    "alt": alt,
                    "qual": qual,
                    "type": "SNP" if is_snp else "INDEL",
                })

    meta_path = vcf_path.parent / "output.meta.json"
    meta = None
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            meta = None

    return {
        "path": str(vcf_path),
        "round_dir": str(vcf_path.parent),
        "size_bytes": vcf_path.stat().st_size,
        "variant_count": total,
        "snp_count": snp,
        "indel_count": indel,
        "preview": preview,
        "meta": meta,
    }
