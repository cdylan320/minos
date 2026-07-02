"""Generate local eval truth + mutations VCFs without an on-chain validator.

Mirrors the platform model at a high level:
  1. GIAB open-source benchmark variants in the region (public baseline)
  2. Oracle variant call on the task BAM (sensitive bcftools — fixed, not user config)
  3. Synthetic mutations = oracle calls NOT in GIAB (approximates HelixForge injections)
  4. mutations.vcf.gz = synthetic-only (SYNTHETIC INFO flag)
  5. truth.vcf.gz = GIAB subset + synthetic merged

Scores are for *relative* config tuning locally. They will not match mainnet exactly
unless the platform publishes the official truth bundle — but they use the same hap.py
+ AdvancedScorer pipeline and mutations-only filtering.
"""

from __future__ import annotations

import gzip
import hashlib
import logging
import os
import shlex
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from utils.file_utils import download_file_with_fallback
from utils.scoring import BCFTOOLS_DOCKER_IMAGE, slice_truth_vcf

logger = logging.getLogger(__name__)

# NIST GIAB HG002 v4.2.1 benchmark (GRCh38, chr1-22) — public open-source truth
# NCBI moved files from /ReferenceSamples/giab/release/... to /giab/ftp/release/...
GIAB_BENCHMARK_URL = (
    "https://ftp-trace.ncbi.nlm.nih.gov/giab/ftp/release/"
    "AshkenazimTrio/HG002_NA24385_son/NISTv4.2.1/GRCh38/"
    "HG002_GRCh38_1_22_v4.2.1_benchmark.vcf.gz"
)
GIAB_BENCHMARK_URL_LEGACY = (
    "https://ftp-trace.ncbi.nlm.nih.gov/ReferenceSamples/giab/release/"
    "AshkenazimTrio/HG002_NISTv4.2.1/GRCh38/"
    "HG002_GRCh38_1_22_v4.2.1_benchmark.vcf.gz"
)

# Fixed oracle caller config — deliberately separate from miner tuning configs
ORACLE_MPILEUP_FLAGS = "-Q 1 -q 1 --max-depth 8000"
ORACLE_CALL_FLAGS = "-mv --ploidy GRCh38"

VCF_COLNAMES = "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE\n"


def _chrom_from_region(region: str) -> str:
    if region and ":" in region:
        return region.split(":")[0]
    return "chr20"


def _vcf_meta_header(chrom: str) -> str:
    """Minimal VCF meta-lines required by bcftools merge and hap.py vcfcheck."""
    return (
        "##fileformat=VCFv4.2\n"
        f"##contig=<ID={chrom}>\n"
        '##INFO=<ID=SYNTHETIC,Number=0,Type=Flag,Description="Synthetic mutation">\n'
        '##INFO=<ID=SVTYPE,Number=1,Type=String,Description="Variant type">\n'
        '##INFO=<ID=SOURCE,Number=1,Type=String,Description="Provenance">\n'
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
    )


def _reheader_vcf(vcf_path: Path, ref_path: Path) -> None:
    """Add reference contig lines so hap.py vcfcheck accepts the VCF."""
    fai = Path(f"{ref_path}.fai")
    if not fai.exists():
        return
    work = vcf_path.parent
    tmp = work / f".{vcf_path.name}.reheader"
    result = _run_docker_bcftools([
        "-v", f"{work}:/data",
        "-v", f"{ref_path.parent}:/ref",
        BCFTOOLS_DOCKER_IMAGE,
        "bash", "-c",
        (
            f"bcftools reheader -f /ref/{fai.name} -o /data/{tmp.name} /data/{vcf_path.name} && "
            f"mv /data/{tmp.name} /data/{vcf_path.name} && "
            f"bcftools index -t /data/{vcf_path.name}"
        ),
    ])
    if result.returncode != 0:
        logger.warning("bcftools reheader failed for %s: %s", vcf_path.name, result.stderr[-300:])


def _bam_fingerprint(bam_path: Path) -> str:
    h = hashlib.sha256()
    with bam_path.open("rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def _run_docker_bcftools(args: List[str], timeout: int = 600) -> subprocess.CompletedProcess:
    cmd = ["docker", "run", "--rm", *args]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _index_vcf(vcf_path: Path, mount_dir: Path) -> bool:
    result = _run_docker_bcftools([
        "-v", f"{mount_dir}:/data",
        BCFTOOLS_DOCKER_IMAGE,
        "bcftools", "index", "-t", f"/data/{vcf_path.name}",
    ])
    return result.returncode == 0


def fetch_giab_benchmark(cache_dir: Path) -> Path:
    """Download full GIAB benchmark VCF once (cached)."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    dest = cache_dir / "HG002_GRCh38_1_22_v4.2.1_benchmark.vcf.gz"
    if dest.exists() and dest.stat().st_size > 1_000_000:
        return dest

    logger.info("Downloading GIAB HG002 benchmark VCF (~149 MB, one-time)...")
    ok = download_file_with_fallback(
        GIAB_BENCHMARK_URL, dest, backup_url=GIAB_BENCHMARK_URL_LEGACY, show_progress=True,
    )
    if not ok or not dest.exists():
        raise RuntimeError(
            "Failed to download GIAB benchmark VCF. "
            f"Try manually: {GIAB_BENCHMARK_URL}"
        )
    _index_vcf(dest, cache_dir)
    return dest


def subset_giab_to_region(giab_vcf: Path, region: str, dest: Path) -> Path:
    """Slice GIAB benchmark to eval region."""
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    if not slice_truth_vcf(giab_vcf, dest, region):
        raise RuntimeError(f"Failed to subset GIAB VCF to region {region}")
    return dest


def run_oracle_call(bam_path: Path, ref_path: Path, region: str, dest_vcf: Path) -> Path:
    """Sensitive bcftools call on BAM — discovers variants actually in the reads."""
    bam_path = bam_path.resolve()
    ref_path = ref_path.resolve()
    dest_vcf = dest_vcf.resolve()
    dest_vcf.parent.mkdir(parents=True, exist_ok=True)

    bam_dir = bam_path.parent
    ref_dir = ref_path.parent
    out_dir = dest_vcf.parent

    bam_index = Path(str(bam_path) + ".bai")
    if not bam_index.exists():
        idx = _run_docker_bcftools([
            "-v", f"{bam_dir}:/data",
            "quay.io/biocontainers/samtools:1.20--h50ea8bc_0",
            "samtools", "index", f"/data/{bam_path.name}",
        ], timeout=300)
        if idx.returncode != 0:
            raise RuntimeError(f"Failed to index BAM: {idx.stderr}")

    shell_cmd = (
        f"bcftools mpileup --threads 4 -f /ref/{shlex.quote(ref_path.name)} "
        f"-r {shlex.quote(region)} {ORACLE_MPILEUP_FLAGS} -Ou /data/{shlex.quote(bam_path.name)} "
        f"| bcftools call --threads 4 {ORACLE_CALL_FLAGS} -Ou "
        f"| bcftools norm --threads 4 -f /ref/{shlex.quote(ref_path.name)} "
        f"-Oz -o /out/{shlex.quote(dest_vcf.name)} && "
        f"bcftools index -t /out/{shlex.quote(dest_vcf.name)}"
    )

    result = subprocess.run(
        [
            "docker", "run", "--rm",
            "-v", f"{bam_dir}:/data",
            "-v", f"{ref_dir}:/ref",
            "-v", f"{out_dir}:/out",
            BCFTOOLS_DOCKER_IMAGE,
            "bash", "-c", shell_cmd,
        ],
        capture_output=True,
        text=True,
        timeout=3600,
    )
    if result.returncode != 0 or not dest_vcf.exists():
        raise RuntimeError(f"Oracle bcftools call failed: {result.stderr[-500:]}")

    return dest_vcf


def _load_vcf_variants(vcf_path: Path) -> List[dict]:
    variants = []
    opener = gzip.open if str(vcf_path).endswith(".gz") else open
    with opener(vcf_path, "rt") as handle:
        for line in handle:
            if line.startswith("#"):
                continue
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 8:
                continue
            chrom, pos, _id, ref, alt, qual, filt, info = parts[:8]
            for a in alt.split(","):
                if a == ".":
                    continue
                variants.append({
                    "chrom": chrom,
                    "pos": int(pos),
                    "ref": ref,
                    "alt": a,
                    "qual": qual,
                    "filter": filt,
                    "info": info,
                })
    return variants


def _variant_key(v: dict) -> Tuple[str, int, str, str]:
    return (v["chrom"], v["pos"], v["ref"], v["alt"])


def _position_key(v: dict) -> Tuple[str, int]:
    return (v["chrom"], v["pos"])


def _write_vcf(variants: List[dict], dest: Path, sample: str = "TRUTH") -> Path:
    """Write variants to a tabix-indexed bgzip VCF (required by bcftools/hap.py)."""
    dest = dest.resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)
    plain_vcf = dest.parent / f".{dest.stem}.plain.vcf"
    chrom = variants[0]["chrom"] if variants else "chr20"
    with plain_vcf.open("wt") as out:
        out.write(_vcf_meta_header(chrom))
        out.write(VCF_COLNAMES.replace("SAMPLE", sample))
        for v in sorted(variants, key=lambda x: (x["chrom"], x["pos"])):
            is_indel = len(v["ref"]) != len(v["alt"])
            svtype = "INDEL" if is_indel else "SNP"
            info = v.get("info") or f"SYNTHETIC;SVTYPE={svtype};SOURCE=local_eval"
            if "SYNTHETIC" not in info:
                info = f"SYNTHETIC;SVTYPE={svtype};{info}"
            qual = v.get("qual") or "60"
            filt = v.get("filter") or "PASS"
            out.write(
                f"{v['chrom']}\t{v['pos']}\t.\t{v['ref']}\t{v['alt']}\t{qual}\t{filt}\t{info}\tGT\t0/1\n"
            )

    work = dest.parent
    result = _run_docker_bcftools([
        "-v", f"{work}:/data",
        BCFTOOLS_DOCKER_IMAGE,
        "bash", "-c",
        (
            f"bcftools view -Oz -o /data/{dest.name} /data/{plain_vcf.name} && "
            f"bcftools index -t /data/{dest.name}"
        ),
    ])
    plain_vcf.unlink(missing_ok=True)
    if result.returncode != 0 or not dest.exists():
        raise RuntimeError(f"Failed to write bgzip VCF {dest.name}: {result.stderr[-500:]}")
    return dest


def extract_synthetic_mutations(oracle_vcf: Path, giab_vcf: Path, dest: Path) -> Path:
    """Variants in oracle but not in GIAB at same position = synthetic (local HelixForge proxy)."""
    giab_positions = set()
    for v in _load_vcf_variants(giab_vcf):
        giab_positions.add(_position_key(v))

    synthetic = []
    for v in _load_vcf_variants(oracle_vcf):
        if _position_key(v) not in giab_positions:
            is_indel = len(v["ref"]) != len(v["alt"])
            svtype = "INDEL" if is_indel else "SNP"
            v["info"] = f"SYNTHETIC;SVTYPE={svtype};SOURCE=local_oracle"
            synthetic.append(v)

    if not synthetic:
        # Fallback: top-confidence oracle SNPs/INDELs if GIAB covers everything
        oracle_vars = _load_vcf_variants(oracle_vcf)
        oracle_vars.sort(key=lambda x: float(x.get("qual") or 0) if x.get("qual") not in (".", "") else 0, reverse=True)
        cap = min(99, len(oracle_vars))
        for v in oracle_vars[:cap]:
            is_indel = len(v["ref"]) != len(v["alt"])
            svtype = "INDEL" if is_indel else "SNP"
            v["info"] = f"SYNTHETIC;SVTYPE={svtype};SOURCE=local_oracle_fallback"
            synthetic.append(v)

    if not synthetic:
        raise RuntimeError("Oracle call found no variants — cannot build mutations VCF")

    return _write_vcf(synthetic, dest, sample="MUTATIONS")


def merge_truth_vcf(giab_subset: Path, mutations: Path, dest: Path) -> Path:
    """Merge GIAB + synthetic into truth.vcf.gz (bcftools concat)."""
    giab_subset = giab_subset.resolve()
    mutations = mutations.resolve()
    dest = dest.resolve()
    work = dest.parent

    merged_nogz = work / "truth_merged.vcf"
    result = _run_docker_bcftools([
        "-v", f"{work}:/data",
        BCFTOOLS_DOCKER_IMAGE,
        "bash", "-c",
        (
            "echo HG002 > /data/.merge_sample && "
            f"bcftools reheader -s /data/.merge_sample -o /data/.mutations_hg002.vcf.gz /data/{mutations.name} && "
            "bcftools index -t /data/.mutations_hg002.vcf.gz && "
            f"bcftools concat -a -D -Oz -o /data/{dest.name} "
            f"/data/{giab_subset.name} /data/.mutations_hg002.vcf.gz && "
            f"bcftools index -t /data/{dest.name} && "
            "rm -f /data/.mutations_hg002.vcf.gz /data/.mutations_hg002.vcf.gz.csi /data/.merge_sample"
        ),
    ], timeout=300)

    if result.returncode != 0 or not dest.exists():
        raise RuntimeError(f"Failed to merge truth VCF: {result.stderr[-500:]}")

    return dest


def generate_local_truth(
    bam_path: Path,
    ref_path: Path,
    region: str,
    work_dir: Path,
    giab_cache_dir: Optional[Path] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """Full pipeline: GIAB subset + oracle call → mutations + truth."""
    bam_path = Path(bam_path).resolve()
    ref_path = Path(ref_path).resolve()
    work_dir = Path(work_dir).resolve()
    work_dir.mkdir(parents=True, exist_ok=True)

    fp = _bam_fingerprint(bam_path)
    meta_path = work_dir / "local_truth_meta.json"
    truth_out = work_dir / "truth.vcf.gz"
    mut_out = work_dir / "mutations.vcf.gz"

    if not force and truth_out.exists() and mut_out.exists() and meta_path.exists():
        import json
        meta = json.loads(meta_path.read_text())
        if meta.get("bam_fingerprint") == fp:
            return {
                "truth_vcf": str(truth_out),
                "mutations_vcf": str(mut_out),
                "cached": True,
                "log": ["Reusing cached locally-generated truth (same BAM fingerprint)"],
                **meta,
            }

    log: List[str] = []
    giab_cache = giab_cache_dir or (work_dir.parent.parent / "giab")

    log.append(f"Step 1/4: Oracle variant call on BAM ({region})...")
    oracle_vcf = work_dir / "oracle.vcf.gz"
    run_oracle_call(bam_path, ref_path, region, oracle_vcf)
    oracle_count = len(_load_vcf_variants(oracle_vcf))
    log.append(f"Oracle found {oracle_count} variant alleles")

    log.append("Step 2/4: Downloading GIAB HG002 benchmark (open-source baseline)...")
    giab_full = fetch_giab_benchmark(giab_cache)
    giab_subset = work_dir / "giab_subset.vcf.gz"
    subset_giab_to_region(giab_full, region, giab_subset)
    giab_count = len(_load_vcf_variants(giab_subset))
    log.append(f"GIAB subset: {giab_count} variants in region")

    log.append("Step 3/4: Extracting synthetic mutations (oracle \\ GIAB)...")
    extract_synthetic_mutations(oracle_vcf, giab_subset, mut_out)
    mut_count = len(_load_vcf_variants(mut_out))
    log.append(f"Synthetic mutations: {mut_count} variants")

    log.append("Step 4/4: Merging truth VCF (GIAB + synthetic)...")
    merge_truth_vcf(giab_subset, mut_out, truth_out)
    _reheader_vcf(mut_out, ref_path)
    _reheader_vcf(truth_out, ref_path)
    truth_count = len(_load_vcf_variants(truth_out))
    log.append(f"Merged truth: {truth_count} variants")

    meta = {
        "bam_fingerprint": fp,
        "region": region,
        "oracle_variants": oracle_count,
        "giab_variants": giab_count,
        "synthetic_mutations": mut_count,
        "truth_variants": truth_count,
        "source": "local_generator",
        "giab_url": GIAB_BENCHMARK_URL,
    }
    import json
    meta_path.write_text(json.dumps(meta, indent=2))

    return {
        "truth_vcf": str(truth_out),
        "mutations_vcf": str(mut_out),
        "cached": False,
        "log": log,
        **meta,
    }
