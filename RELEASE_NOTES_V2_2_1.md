# Release v2.2.1

Date/time: 2026-08-30 04:32 +03:00  
Tool: Codex  
Model: GPT-5.6  
Operation ID: `f07-v2-2-1-hash-portability-20260830`

This release is a byte-level provenance portability patch for v2.2.0.

- The six corrected OPSSAT-AD and KDDCup99 transfer CSVs are LF-normalized.
- Both `signature_repair_provenance.json` records now contain SHA-256 values
  computed from the exact released LF bytes.
- The provenance hashes and `checksums.sha256` therefore agree in a fresh clone.
- Reported scientific values, detector predictions, V4/V5 protocols and
  property-gate outcomes, manuscript estimates, and the no-endpoint/no-rescue
  conclusions are unchanged.
